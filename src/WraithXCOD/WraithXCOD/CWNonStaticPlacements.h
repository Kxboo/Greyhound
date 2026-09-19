#pragma once
#include "json.hpp"
#include <cmath>
#include <functional>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>

// Pure conversion of typed entity evidence. Never infer animation state from
// an XModel name, or turn a script spawn marker into a confirmed visible model.
namespace CWNonStaticPlacements
{
    using json = nlohmann::json;
    using Resolver = std::function<std::string(uint64_t)>;

    inline std::string ClassFile(const std::string& Class)
    {
        std::string Out = "class_";
        const char* Hex = "0123456789ABCDEF";
        for (unsigned char C : Class)
            if ((C >= 'a' && C <= 'z') || (C >= 'A' && C <= 'Z') ||
                (C >= '0' && C <= '9') || C == '_' || C == '-') Out += char(C);
            else { Out += '%'; Out += Hex[C >> 4]; Out += Hex[C & 15]; }
        return Out + ".json";
    }
    inline std::string Hex(uint64_t H)
    { std::ostringstream S; S << "0x" << std::hex << H; return S.str(); }
    inline bool Vector(const json& V)
    {
        if (!V.is_array() || V.size() != 3) return false;
        for (const auto& X : V)
            if (!X.is_number() || !std::isfinite(X.get<double>()) || std::abs(X.get<double>()) > 1e7) return false;
        return true;
    }
    inline json XYZ(const json& V) { return {{"X",V[0]}, {"Y",V[1]}, {"Z",V[2]}}; }
    inline json Quaternion(const json& Angles)
    {
        // CoD angles are pitch, yaw, roll; placement Euler XYZ is roll, pitch, yaw.
        constexpr double HalfRadians = 3.14159265358979323846 / 360.0;
        const double P = Angles[0].get<double>() * HalfRadians;
        const double Y = Angles[1].get<double>() * HalfRadians;
        const double R = Angles[2].get<double>() * HalfRadians;
        const double CP=cos(P), SP=sin(P), CY=cos(Y), SY=sin(Y), CR=cos(R), SR=sin(R);
        return {{"X",SR*CP*CY-CR*SP*SY}, {"Y",CR*SP*CY+SR*CP*SY},
            {"Z",CR*CP*SY-SR*SP*CY}, {"W",CR*CP*CY+SR*SP*SY}};
    }
    inline json Value(const json& P)
    {
        switch (P.value("type_tag", 0))
        {
        case 2:
            if (P.contains("string_candidate") && P["string_candidate"].value("terminated",false)
                && P["string_candidate"].contains("text")) return P["string_candidate"]["text"];
            break;
        case 3: if (P.contains("vector_candidate")) return P["vector_candidate"]; break;
        case 4: if (P.contains("asset_hash_candidate")) return P["asset_hash_candidate"]; break;
        case 5: if (P.contains("float_candidate")) return P["float_candidate"]; break;
        case 6: if (P.contains("int32_candidate")) return P["int32_candidate"]; break;
        }
        return nullptr;
    }
    inline json Mapping()
    {
        return {{"schema","cw-bo3-placement-mapping-v1"},
            {"coordinates",{{"units","CoD world units (inches)"},{"up_axis","Z"},
                {"translation","identity; no scaling, axis swap or recentering"},
                {"source_angles","pitch yaw roll in degrees"},
                {"RotationDegrees","X=roll, Y=pitch, Z=yaw"},
                {"RotationQuaternion","x y z w; Rz(yaw) * Ry(pitch) * Rx(roll)"}}},
            {"bo3_keys",{{"origin","Position X Y Z"},{"angles","SourceAngles pitch yaw roll"},
                {"modelscale","uniform ModelScale"},{"model","Name; requires an imported BO3 XModel/GDT asset"}}},
            {"entity_classes",{{"script_model","script_model: transform reference only; port scripts separately"},
                {"script_origin","script_origin: marker, not a confirmed visible model"},
                {"script_struct","script_struct: authored marker; scripts decide whether its model spawns"},
                {"other","unmapped; original classname and typed properties retained"}}},
            {"reference_key","SourceEntityId joins model placements to entities/<pool>/<class file>, EntityId"},
            {"bo3_references",json::array({"docs_modtools/Lighting_Parameters.pdf, pages 1-3, 8-11",
                "docs_modtools/FX_Lights.pdf, pages 1-2", "docs_modtools/Lighting_Probe_Workflow.pdf, pages 1-3",
                "docs_modtools/Probe/Reflection_Probes.pdf, pages 1-6"})},
            {"lights",{{"classname","light"},{"verified_BO3_keys",json::array({"_color","PRIMARY_TYPE","PRIMARY_SCRIPTABLE","PRIMARY_NOSHADOWMAP","fov_outer","radius","falloffdistance","def"})},
                {"intensity","BO3 authoring uses stops; do not copy CW linear RGB magnitude into stops"},
                {"CW_type_enum","unmapped; retain raw numeric type"},
                {"FX_lights","BO3 .efx Dynamic Light: color/intensity/radius/FOV curves and rotation are asset data, not placement data"}}},
            {"reflection_probes",{{"classname","reflection_probe"},
                {"authored_keys",json::array({"origin","angles","size_min","size_max","blend_mins","blend_maxs","grid_density"})},
                {"compiled_outer_extents","include blend margins; do not copy directly into size_min/size_max"},
                {"cube_capture_origin","independent from influence box center; preserve both"},
                {"bounds_file","reflection_probe_bounds.json; explicit SourceProbeId and start/count ownership, separate inner extents and blend margins"},
                {"bounds_basis","axis rows are local basis vectors in world coordinates; world = origin + sum(local[i]*axis[i])"},
                {"multiple_volumes","BO3 parent/child reflection probes; retain shared source probe identity instead of inventing independent cubemaps"},
                {"multiface","InfluencePlanes are clipping planes, not parallax reflection planes; BO3 facePlane/faceBlend conversion remains unverified"},
                {"local_references",json::array({"docs_modtools/Probe/Reflection_Probes.pdf","docs_modtools/Probe/Multiface_Probes.pdf","docs_modtools/Probe/Subtract_Probes.pdf","map_source/_prefabs/zm/zm_giant/zm_giant_light.map"})},
                {"global_probe","belongs to sun_volume; may target info_null; rebake BO3 cubemaps and GI"}}},
            {"limits",json::array({"Authored initial transforms, not current animated poses or live spawned entity transforms.",
                "CW FX, animation assets, script bundles, AI, vehicles and trigger behavior require separate BO3 ports.",
                "A model or bundle name containing fxanim/fxanm is a name hint, not proof of an active animation.",
                "Trigger origins alone do not define brush hulls. Keep typed trigger geometry and source indices."})}};
    }

    inline json Convert(const json& Decoded, const std::string& PoolName, const Resolver& Resolve)
    {
        json Result={{"entities",json::object()},{"models",json::array()},
            {"rejected_model_entities",json::array()},{"entity_count",0}};
        for (const auto& E : Decoded.at("entities"))
        {
            json Props=json::object(); std::map<std::string,int> Types;
            bool Duplicate=false;
            for (const auto& P : E.at("properties"))
            {
                const auto Key=P.value("key",json::object()).value("text",std::string());
                if (Key.empty()) continue;
                if (Props.contains(Key)) Duplicate=true;
                Props[Key]=Value(P); Types[Key]=P.value("type_tag",0);
            }
            const std::string Class=Props.contains("classname") && Props["classname"].is_string()
                ? Props["classname"].get<std::string>() : "unknown";
            const std::string Id=Decoded.value("source_name_hash",std::string())+":"+PoolName+":"+std::to_string(E.at("index").get<size_t>());
            json Entity=E;
            Entity["EntityId"]=Id; Entity["ClassName"]=Class; Entity["Properties"]=Props;
            const auto RecordVectors=E.value("record_vector_candidates",json::array());
            bool TransformValid=RecordVectors.size()==2 && Vector(RecordVectors[0]) && Vector(RecordVectors[1]) &&
                Vector(Props.value("origin",json())) && Vector(Props.value("angles",json()));
            if(TransformValid) for(size_t I=0;I<3;++I)
                if(std::abs(RecordVectors[0][I].get<double>()-Props["origin"][I].get<double>())>0.501 ||
                    std::abs(std::remainder(RecordVectors[1][I].get<double>()-Props["angles"][I].get<double>(),360.0))>0.501) TransformValid=false;
            Entity["TransformValidated"]=TransformValid;
            Entity["Position"]=TransformValid?XYZ(RecordVectors[0]):json(nullptr);
            Entity["SourceAngles"]=TransformValid?XYZ(RecordVectors[1]):json(nullptr);
            Entity["BO3ClassMapping"]=Class=="script_model" || Class=="script_origin" || Class=="script_struct"
                ? json({{"classname",Class},{"status","transform_reference_only; script behavior not ported"}})
                : json({{"classname",nullptr},{"status","unmapped"}});
            if(Class=="reflection_probe")
            {
                Entity["BO3ClassMapping"]={{"classname","reflection_probe"},{"status","documented_authoring_keys; rebake BO3 cubemap and GI"}};
                Entity["BO3ProbeKeys"]=json::object();
                for(const char* Key:{"origin","angles","size_min","size_max","blend_mins","blend_maxs","grid_density","targetname"})
                    if(Props.contains(Key)) Entity["BO3ProbeKeys"][Key]=Props[Key];
                if(TransformValid) {Entity["BO3ProbeKeys"]["origin"]=RecordVectors[0];Entity["BO3ProbeKeys"]["angles"]=RecordVectors[1];}
            }
            const auto Reject=[&](const std::string& Reason)
            { Result["rejected_model_entities"].push_back({{"EntityId",Id},{"reason",Reason}}); };
            if (Props.contains("model"))
            {
                try
                {
                    if (Duplicate) throw std::runtime_error("duplicate_property_keys");
                    std::string Name; uint64_t Hash=0;
                    if (Types["model"]==4 && Props["model"].is_string())
                    {
                        const auto Text=Props["model"].get<std::string>(); size_t Used=0;
                        const auto Raw=std::stoull(Text,&Used,16);
                        if (Used!=Text.size()) throw std::runtime_error("invalid_model_hash");
                        Hash=Raw&0xFFFFFFFFFFFFFFFull;
                        if (!Hash) throw std::runtime_error("empty_model_hash");
                        Name=Resolve(Hash);
                        Entity["ModelHashRaw"]=Text; Entity["ModelHash"]=Hex(Hash);
                        if (Name.empty()) Name="xmodel_"+Hex(Hash).substr(2);
                    }
                    else if (Types["model"]==2 && Props["model"].is_string()) Name=Props["model"].get<std::string>();
                    else throw std::runtime_error("unsupported_model_property_type");
                    if (Name.empty() || Name[0]=='*' || Name[0]=='?') throw std::runtime_error("empty_or_inline_brush_model");
                    auto Position=Props.value("origin",json()); auto Angles=Props.value("angles",json());
                    if (!Vector(Position) || !Vector(Angles)) throw std::runtime_error("missing_or_invalid_authored_transform");
                    // The property vectors are rounded by CW. Record +24/+36
                    // retains precision; require agreement with named values.
                    const auto V=E.value("record_vector_candidates",json::array());
                    if (V.size()!=2 || !Vector(V[0]) || !Vector(V[1])) throw std::runtime_error("invalid_record_transform");
                    for (size_t I=0;I<3;++I)
                        if (std::abs(V[0][I].get<double>()-Position[I].get<double>())>0.501 ||
                            std::abs(std::remainder(V[1][I].get<double>()-Angles[I].get<double>(),360.0))>0.501)
                            throw std::runtime_error("record_property_transform_disagreement");
                    Position=V[0]; Angles=V[1];
                    double Scale=1.0;
                    if (Props.contains("modelscale"))
                    {
                        const auto& S=Props["modelscale"];
                        if (S.is_number()) Scale=S.get<double>();
                        else if (S.is_string()) { size_t Used=0; const auto T=S.get<std::string>(); Scale=std::stod(T,&Used); if(Used!=T.size()) throw std::runtime_error("invalid_scale_text"); }
                        else throw std::runtime_error("unsupported_scale_type");
                    }
                    if (!std::isfinite(Scale) || Scale<=0 || Scale>=1000) throw std::runtime_error("invalid_scale");
                    json Row={{"Name",Name},{"SourceName",Name},{"NameResolved",Name.rfind("xmodel_",0)!=0},
                        {"ModelHash",Hash?json(Hex(Hash)):json(nullptr)}, {"Position",XYZ(Position)},
                        {"SourceAngles",XYZ(Angles)}, {"RotationDegrees",{{"X",Angles[2]},{"Y",Angles[0]},{"Z",Angles[1]}}},
                        {"RotationQuaternion",Quaternion(Angles)},{"ModelScale",{{"X",Scale},{"Y",Scale},{"Z",Scale}}},
                        {"ScaleSource",Props.contains("modelscale")?"entity_property":"default_one"},
                        {"PlacementSource","authored_entity_record"},{"SourceEntityId",Id},{"ClassName",Class},
                        {"SourceEntityFile","entities/"+PoolName+"/"+ClassFile(Class)},
                        {"RuntimeVisibility","unknown"},{"AnimationState","not_captured"},
                        {"BO3",{{"origin",Position},{"angles",Angles},{"modelscale",Scale},{"model",Name},
                            {"asset_status","requires_BO3_asset_import"},{"classname",Entity["BO3ClassMapping"]["classname"]}}}};
                    Entity["ModelPlacement"]=Row;
                    Result["models"].push_back(Row);
                }
                catch(const std::exception& Error) { Reject(Error.what()); Entity["ModelPlacementStatus"]=Error.what(); }
            }
            const auto File=ClassFile(Class);
            if (!Result["entities"].contains(File)) Result["entities"][File]=json::array();
            Result["entities"][File].push_back(Entity);
        }
        Result["entity_count"]=Decoded.at("entities").size();
        return Result;
    }
}
