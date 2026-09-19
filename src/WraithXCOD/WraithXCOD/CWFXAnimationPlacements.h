#pragma once
#include "CWNonStaticPlacements.h"
#include <cctype>
#include <set>

namespace CWFXAnimationPlacements
{
    using json=nlohmann::json;
    inline std::string Lower(std::string S){for(auto& C:S)C=char(std::tolower(static_cast<unsigned char>(C)));return S;}
    inline bool Anim(const std::string& S){const auto L=Lower(S);return L.find("anim")!=std::string::npos||L.find("anm")!=std::string::npos;}
    inline bool FX(const std::string& S){const auto L=Lower(S);return L.find("fx")!=std::string::npos||L.find("effect")!=std::string::npos;}
    inline bool ModelHint(const std::string& S){const auto L=Lower(S);return L.find("fxanim")!=std::string::npos||L.find("fxanm")!=std::string::npos;}
    inline uint64_t Hash(const std::string& S){uint64_t H=0xCBF29CE484222325ull;for(unsigned char C:S)H=(H^C)*0x100000001B3ull;return H&0xFFFFFFFFFFFFFFFull;}
    inline json Build(const json& Static,const json& Models,const json& Entities)
    {
        json Result={{"animation_model_placements",json::array()},{"animation_entity_references",json::array()},
            {"fx_entity_references",json::array()},{"named_animation_references",json::array()}};
        std::map<std::string,json> ByEntity;
        for(const auto& E:Entities)
        {
            json AR=json::object(),FR=json::object();
            for(const auto& KV:E.at("Properties").items())
            {
                const auto Value=KV.value().is_string()?KV.value().get<std::string>():std::string();
                if(Anim(KV.key())||ModelHint(Value))AR[KV.key()]=KV.value();
                if(FX(KV.key())||ModelHint(Value))FR[KV.key()]=KV.value();
                if(Anim(KV.key())&&!Value.empty())Result["named_animation_references"].push_back({
                    {"SourceEntityId",E.at("EntityId")},{"Property",KV.key()},{"Name",Value},
                    {"LookupHash",CWNonStaticPlacements::Hex(Hash(Value))},
                    {"Meaning","verbatim entity property; may name an animation, script or authoring preview, not necessarily playback"}});
            }
            ByEntity[E.at("EntityId").get<std::string>()]=E;
            for(bool IsAnim:{true,false})
            {
                const auto& Refs=IsAnim?AR:FR;if(Refs.empty())continue;
                auto Row=E;Row["MatchedReferenceProperties"]=Refs;
                Row["PlacementMeaning"]="authored entity transform and attached properties; no playback or current pose inferred";
                Result[IsAnim?"animation_entity_references":"fx_entity_references"].push_back(Row);
            }
        }
        for(bool IsStatic:{true,false})
        {
            const auto& Rows=IsStatic?Static:Models;
            for(size_t I=0;I<Rows.size();++I)
            {
                auto Row=Rows[I];json E=nullptr;bool PropertyMatch=false;
                if(!IsStatic&&Row.contains("SourceEntityId"))
                {
                    const auto It=ByEntity.find(Row["SourceEntityId"].get<std::string>());
                    if(It!=ByEntity.end())
                    {
                        E=It->second;for(const auto& KV:E["Properties"].items())
                            if(Anim(KV.key())||(KV.value().is_string()&&ModelHint(KV.value().get<std::string>())))PropertyMatch=true;
                    }
                }
                const bool Hint=ModelHint(Row.value("Name",std::string()))||ModelHint(Row.value("SourceName",std::string()));
                if(!Hint&&!PropertyMatch)continue;
                Row["SourcePlacementFile"]=IsStatic?"static_models.json":"non_static_models.json";Row["SourcePlacementIndex"]=I;
                Row["SelectionEvidence"]={{"model_name_hint",Hint},{"entity_animation_properties",PropertyMatch}};
                Row["AttachedEntityProperties"]=E.is_null()?json(nullptr):E["Properties"];
                Row["AnimationStatus"]="placement with animation-related names/properties; active playback not inferred";
                Result["animation_model_placements"].push_back(Row);
            }
        }
        return Result;
    }
}
