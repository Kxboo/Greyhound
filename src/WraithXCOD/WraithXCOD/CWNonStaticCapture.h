#pragma once
#include "CWNonStaticPlacements.h"
#include "CWMapCandidateCapture.h"
#include "CWPoolProbe.h"
#include "ModelExportNaming.h"
#include "CWProbeBounds.h"
#include "CWFXAnimationPlacements.h"
#include "CWLightPlacements.h"

namespace CWNonStaticCapture
{
    using TerrainResearch::json;
    struct Pool
    {
        uint64_t Base=0, Descriptor=0;
        uint32_t Stride=0, Capacity=0, Loaded=0;
        std::vector<uint8_t> Desc, Headers;
        CWPoolProbe::Occupancy Slots;
    };
    inline bool Save(const std::string& Root, const std::string& Name, const json& Doc)
    {
        const auto Path=FileSystems::CombinePath(Root,Name);
        FileSystems::CreateDirectory(FileSystems::GetDirectoryName(Path));
        std::ofstream Out(Path,std::ios::binary); Out<<Doc.dump(2); Out.close(); return bool(Out);
    }
    inline bool ReadPool(TerrainResearch::Capture& C, uint64_t Pools, uint32_t Index, uint32_t Stride, Pool& P)
    {
        P.Descriptor=Pools+32ull*Index;
        P.Desc=C.Span(P.Descriptor,32,"pool_descriptor.bin","counted asset pool descriptor");
        if(P.Desc.size()!=32) return false;
        P.Base=TerrainResearch::U64(P.Desc,0); P.Stride=TerrainResearch::U32(P.Desc,8);
        P.Capacity=TerrainResearch::U32(P.Desc,12); P.Loaded=TerrainResearch::U32(P.Desc,20);
        if(P.Stride!=Stride || P.Capacity>32768 || P.Loaded>P.Capacity) return false;
        if (!P.Capacity) return P.Loaded==0;
        P.Headers=C.Span(P.Base,uint64_t(P.Capacity)*Stride,"pool_headers.bin","complete pool including free slots");
        if(P.Headers.size()!=uint64_t(P.Capacity)*Stride) return false;
        P.Slots=CWPoolProbe::FreeSlots(P.Headers,Stride,P.Base,TerrainResearch::U64(P.Desc,24),P.Loaded);
        return P.Slots.Valid;
    }
    inline bool Stable(TerrainResearch::Capture& C,const Pool& P)
    {
        const bool D=C.VerifySpan(P.Descriptor,P.Desc,"pool_descriptor.bin");
        const bool H=P.Headers.empty() || C.VerifySpan(P.Base,P.Headers,"pool_headers.bin");
        return D&&H;
    }
    inline std::string RawHex(const uint8_t* Data,size_t Size)
    {
        std::string R; R.reserve(Size*2); const char* H="0123456789abcdef";
        for(size_t I=0;I<Size;++I) {R+=H[Data[I]>>4];R+=H[Data[I]&15];} return R;
    }
    inline float Float(const uint8_t* B,size_t O) {float V;memcpy(&V,B+O,4);return V;}
    inline json Vec(const uint8_t* B,size_t O) {return json::array({Float(B,O),Float(B,O+4),Float(B,O+8)});}
    inline json Lighting(uint64_t Pools,const std::string& Directory,uint64_t MapHash,
        const std::function<void(uint32_t)>& Progress)
    {
        const auto Root=FileSystems::CombinePath(Directory,"diagnostics/non_static/lighting");
        TerrainResearch::Capture C(Root,Progress); Pool P;
        bool Okay=ReadPool(C,Pools,0xAA,472,P) && P.Loaded<=1;
        json Report={{"pool",0xAA},{"complete",false},{"semantic_status","measured CW layouts; unverified BO3 field conversions remain null"}};
        json Lights=json::array(), DecodedLights=json::array(), Probes=json::array(), Bounds=json::array(), SunVolumes=json::array();
        size_t ValidProbes=0; std::set<std::string> UniqueProbes;
        if(Okay && P.Loaded==1) for(uint32_t Slot=0;Slot<P.Capacity;++Slot) if(!P.Slots.Free.count(Slot))
        {
            std::vector<uint8_t> H(P.Headers.begin()+size_t(Slot)*472,P.Headers.begin()+size_t(Slot+1)*472);
            if((TerrainResearch::U64(H,0)&0xFFFFFFFFFFFFFFFull)!=MapHash) {Okay=false;break;}
            const auto Count=TerrainResearch::U32(H,8); const auto Address=TerrainResearch::U64(H,16);
            if(Count>32768) {Okay=false;break;}
            const auto B=Count?C.Span(Address,uint64_t(Count)*688,"primary_lights.bin","688-byte measured primary light records",false,"resident_scene"):std::vector<uint8_t>();
            if(B.size()!=uint64_t(Count)*688) {Okay=false;break;}
            for(uint32_t I=0;I<Count;++I)
            {
                const auto R=B.data()+size_t(I)*688;
                const auto Position=Vec(R,0x68), Color=Vec(R,0xC8);
                bool Valid=CWNonStaticPlacements::Vector(Position) && memcmp(R+0xC8,R+0x284,12)==0;
                for(size_t K=0;K<3;++K)
                    if(!std::isfinite(Float(R,0xC8+K*4)) || Float(R,0xC8+K*4)<0) Valid=false;
                auto Decoded=CWLightPlacements::Decode(R,688);
                Decoded["SourceId"]=TerrainResearch::Hex(MapHash)+":primary_light:"+std::to_string(I);
                Decoded["RecordAddress"]=TerrainResearch::Hex(Address+uint64_t(I)*688);
                Decoded["SourcePlacementFile"]="light_placement_candidates.json";
                Decoded["SourcePlacementIndex"]=I;
                DecodedLights.push_back(Decoded);
                Lights.push_back({{"SourceId",TerrainResearch::Hex(MapHash)+":primary_light:"+std::to_string(I)},
                    {"Index",I},{"RecordAddress",TerrainResearch::Hex(Address+uint64_t(I)*688)},
                    {"CandidatePosition",Position},{"CandidateLinearRGB",Color},{"TypeRaw",R[0x40]},
                    {"CandidateDirection",Vec(R,0x74)},{"CandidateRadius",Float(R,0x200)},
                    {"StructuralValidation",Valid},{"RawRecordHex",RawHex(R,688)},
                    {"BO3",{{"classname","light"},{"origin",Valid?Position:json(nullptr)},{"PRIMARY_TYPE",nullptr},{"stops",nullptr},
                        {"status","origin is a measured CW candidate; intensity and type conversion not verified; review before BO3 placement"}}}});
            }
            if(Count) Okay=C.VerifySpan(Address,B,"primary_lights.bin")&&Okay;
            const auto GuidCount=TerrainResearch::U32(H,0x60); const auto GuidAddress=TerrainResearch::U64(H,0x68);
            const auto VolumeCount=TerrainResearch::U32(H,0x38); const auto VolumeAddress=TerrainResearch::U64(H,0x40);
            if(GuidCount>200000 || VolumeCount>256) {Okay=false;break;}
            const auto G=GuidCount?C.Span(GuidAddress,uint64_t(GuidCount)*4,"probe_guids.bin","compiled probe GUID reference table",false,"resident_scene"):std::vector<uint8_t>();
            const auto V=VolumeCount?C.Span(VolumeAddress,uint64_t(VolumeCount)*0x26A0,"sun_volumes.bin","measured sun volume headers and probe descriptors",false,"resident_scene"):std::vector<uint8_t>();
            if(G.size()!=uint64_t(GuidCount)*4 || V.size()!=uint64_t(VolumeCount)*0x26A0) {Okay=false;break;}
            std::set<uint32_t> Guids;for(uint32_t I=0;I<GuidCount;++I)Guids.insert(TerrainResearch::U32(G,I*4));
            for(uint32_t Volume=0;Volume<VolumeCount;++Volume)
            {
                const auto Base=V.data()+size_t(Volume)*0x26A0;
                SunVolumes.push_back({{"SunVolumeIndex",Volume},{"RecordAddress",TerrainResearch::Hex(VolumeAddress+uint64_t(Volume)*0x26A0)},
                    {"CandidateGlobalProbeOrigin",Vec(Base,0x24)},{"RawHeaderHex",RawHex(Base,0x26A0)},
                    {"BO3Mapping","sun_volume with global probe; brush planes and other compiled fields require verified decoding"}});
                // Three observed probe descriptors. Their runtime semantics
                // are not asserted to be BO3's numbered lighting-state toggles.
                for(uint32_t State=0;State<3;++State)
                {
                    const auto O=size_t(Volume)*0x26A0+0x2340+State*88;
                    const auto N=TerrainResearch::U32(V,O);const auto A=TerrainResearch::U64(V,O+16);
                    if(N>200000) {Okay=false;continue;}
                    const auto File="probes_v"+std::to_string(Volume)+"_s"+std::to_string(State)+".bin";
                    const auto Data=N?C.Span(A,uint64_t(N)*376,File,"376-byte measured reflection probe array",false,"resident_scene"):std::vector<uint8_t>();
                    if(Data.size()!=uint64_t(N)*376) {Okay=false;continue;}
                    const auto BoundCount=TerrainResearch::U32(V,O+84);const auto BoundAddress=TerrainResearch::U64(V,O+24);
                    if(BoundCount>200000){Okay=false;continue;}
                    const auto BoundFile="probe_bounds_v"+std::to_string(Volume)+"_s"+std::to_string(State)+".bin";
                    const auto BoundData=BoundCount?C.Span(BoundAddress,uint64_t(BoundCount)*604,BoundFile,"604-byte reflection probe influence volumes; descriptor +84 count, +24 pointer",false,"resident_scene"):std::vector<uint8_t>();
                    if(BoundData.size()!=uint64_t(BoundCount)*604){Okay=false;continue;}
                    std::vector<int> Owners;const bool Joined=CWProbeBounds::Owners(Data,BoundCount,Owners);
                    Okay=Joined&&Okay;
                    const auto Prefix=TerrainResearch::Hex(MapHash)+":probe:"+std::to_string(Volume)+":"+std::to_string(State)+":";
                    const auto BoundPrefix=TerrainResearch::Hex(MapHash)+":probe_bound:"+std::to_string(Volume)+":"+std::to_string(State)+":";
                    json BoundRows=json::array();
                    for(uint32_t I=0;I<BoundCount;++I)
                    {
                        const auto B=BoundData.data()+size_t(I)*604;auto Row=CWProbeBounds::Decode(B,604);
                        Row["SourceId"]=BoundPrefix+std::to_string(I);Row["SourceProbeId"]=Joined?json(Prefix+std::to_string(Owners[I])):json(nullptr);
                        Row["SunVolumeIndex"]=Volume;Row["ProbeDescriptorSlot"]=State;Row["BoundIndex"]=I;
                        Row["OwnershipValidated"]=Joined;Row["RecordAddress"]=TerrainResearch::Hex(BoundAddress+uint64_t(I)*604);
                        Row["RawRecordHex"]=RawHex(B,604);
                        Row["SourceProbeFile"]="reflection_probes/volume_"+std::to_string(Volume)+"_descriptor_"+std::to_string(State)+".json";
                        Okay=Row.value("StructuralValidation",false)&&Okay;BoundRows.push_back(Row);Bounds.push_back(Row);
                    }
                    json StateRows=json::array();
                    for(uint32_t I=0;I<N;++I)
                    {
                        const auto R=Data.data()+size_t(I)*376;uint32_t Guid;memcpy(&Guid,R+0x148,4);
                        const auto Position=Vec(R,0x5C), Minus=Vec(R,0x8C), Plus=Vec(R,0x98);
                        bool Valid=CWNonStaticPlacements::Vector(Position)&&CWNonStaticPlacements::Vector(Minus)&&CWNonStaticPlacements::Vector(Plus)&&Guids.count(Guid);
                        json Axes=json::array({Vec(R,0x68),Vec(R,0x74),Vec(R,0x80)});
                        for(int J=0;J<3;++J)for(int K=0;K<3;++K)
                        {
                            double Dot=0;for(int L=0;L<3;++L)Dot+=Float(R,0x68+J*12+L*4)*Float(R,0x68+K*12+L*4);
                            if(!std::isfinite(Dot)||std::abs(Dot-(J==K?1.0:0.0))>0.002)Valid=false;
                        }
                        json Row={{"SourceId",TerrainResearch::Hex(MapHash)+":probe:"+std::to_string(Volume)+":"+std::to_string(State)+":"+std::to_string(I)},
                            {"SunVolumeIndex",Volume},{"ProbeDescriptorSlot",State},{"ProbeIndex",I},{"Guid",Guid},
                            {"RecordAddress",TerrainResearch::Hex(A+uint64_t(I)*376)},
                            {"Position",Valid?Position:json(nullptr)},{"Axes",Axes},{"CompiledOuterExtentMin",Minus},{"CompiledOuterExtentMax",Plus},
                            {"StructuralValidation",Valid},{"LayoutStatus",Valid?"GUID membership and orthonormal axes checked; origin cross-checked with authored probe":"unresolved_or_inactive_record; no placement published"},
                            {"RawRecordHex",RawHex(R,376)},
                            {"BO3",{{"classname",Guid==0?json(nullptr):json("reflection_probe")},{"origin",Valid?Position:json(nullptr)},
                                {"angles",nullptr},{"size_min",nullptr},{"size_max",nullptr},{"blend_mins",nullptr},{"blend_maxs",nullptr},
                                {"status","origin reference; outer extents include blend; rebuild cubemap/GI; descriptor purpose and rotation mapping unverified"}}}};
                        const auto First=CWProbeBounds::U16(R,0x58),OwnedCount=CWProbeBounds::U16(R,0x5A);
                        Row["InfluenceVolumeStart"]=First;Row["InfluenceVolumeCount"]=OwnedCount;
                        Row["BoundsOwnershipValidated"]=Joined;Row["InfluenceVolumeIds"]=json::array();
                        Row["BoundsFile"]="reflection_probe_bounds/volume_"+std::to_string(Volume)+"_descriptor_"+std::to_string(State)+".json";
                        if(Joined)for(uint32_t J=First;J<uint32_t(First)+OwnedCount;++J)Row["InfluenceVolumeIds"].push_back(BoundPrefix+std::to_string(J));
                        // Only publish parent box keys directly when one box has
                        // the same origin and basis as the cubemap capture record.
                        if(Valid&&Joined&&OwnedCount==1)
                        {
                            const auto& Bound=BoundRows[First];bool Same=Bound.value("StructuralValidation",false)&&Bound["PlaneCount"]==0&&Bound["SubtractRaw"]==0;
                            for(int J=0;J<3;++J)
                            {
                                if(std::abs(Bound["VolumeOrigin"][J].get<double>()-Position[J].get<double>())>0.001)Same=false;
                                for(int K=0;K<3;++K)if(std::abs(Bound["Axes"][J][K].get<double>()-Axes[J][K].get<double>())>0.001)Same=false;
                            }
                            if(Same)
                            {
                                for(const char* Key:{"angles","size_min","size_max","blend_mins","blend_maxs","box"})Row["BO3"][Key]=Bound["BO3"][Key];
                                Row["BO3"]["status"]="single box influence volume matched to capture origin and basis; bounds ready as BO3 reference; rebake cubemap and GI";
                            }
                        }
                        if(Valid) {++ValidProbes;UniqueProbes.insert(std::to_string(Guid)+":"+Position.dump());}
                        StateRows.push_back(Row);Probes.push_back(Row);
                    }
                    Okay=Save(Directory,"reflection_probes/volume_"+std::to_string(Volume)+"_descriptor_"+std::to_string(State)+".json",StateRows)&&Okay;
                    Okay=Save(Directory,"reflection_probe_bounds/volume_"+std::to_string(Volume)+"_descriptor_"+std::to_string(State)+".json",BoundRows)&&Okay;
                    if(BoundCount)Okay=C.VerifySpan(BoundAddress,BoundData,BoundFile)&&Okay;
                    if(N) Okay=C.VerifySpan(A,Data,File)&&Okay;
                }
            }
            if(GuidCount) Okay=C.VerifySpan(GuidAddress,G,"probe_guids.bin")&&Okay;
            if(VolumeCount) Okay=C.VerifySpan(VolumeAddress,V,"sun_volumes.bin")&&Okay;
            Report["probe_guid_count"]=GuidCount;
        }
        const bool Unchanged=Stable(C,P);const bool Evidence=C.Finish();
        Okay=Save(Directory,"light_placement_candidates.json",Lights)&&Okay;
        Okay=Save(Directory,"light_placements.json",DecodedLights)&&Okay;
        Okay=Save(Directory,"reflection_probes.json",Probes)&&Okay;
        Okay=Save(Directory,"reflection_probe_bounds.json",Bounds)&&Okay;
        Okay=Save(Directory,"sun_volumes.json",SunVolumes)&&Okay;
        Report["primary_light_records"]=Lights.size();Report["reflection_probe_records"]=Probes.size();
        Report["validated_light_records"]=std::count_if(Lights.begin(),Lights.end(),[](const json& L){return L.value("StructuralValidation",false);});
        Report["decoded_light_placements"]=std::count_if(DecodedLights.begin(),DecodedLights.end(),[](const json& L){return L.value("PlacementValidated",false);});
        Report["validated_probe_records"]=ValidProbes;Report["unique_guid_positions"]=UniqueProbes.size();
        Report["unresolved_probe_records"]=Probes.size()-ValidProbes;
        Report["probe_influence_volume_records"]=Bounds.size();
        Report["validated_probe_bound_records"]=std::count_if(Bounds.begin(),Bounds.end(),[](const json& B){return B.value("StructuralValidation",false)&&B.value("OwnershipValidated",false);});
        Report["probe_bound_shape_note"]="Boxes include separate inner extents and blend margins. For multiface volumes, box corners are enclosing bounds; InfluencePlanes define the clipping shape. Repeated descriptors are not unique probes.";
        Report["sun_volumes"]=SunVolumes.size();Report["source_unchanged"]=Unchanged;
        Report["evidence_saved"]=Evidence;Report["complete"]=Okay&&Unchanged&&Evidence;
        return Report;
    }
    inline json Capture(uint64_t Pools,const std::string& Directory,uint64_t MapHash,
        const std::function<void(uint32_t)>& Progress)
    {
        json Report={{"schema","cw-non-static-capture-v1"},{"map_hash",TerrainResearch::Hex(MapHash)},
            {"name_database",GameBlackOpsCW::ActiveNameDatabase},{"sources",json::object()},
            {"complete",true},{"files",json::array()}, {"scope","authored entities and trigger records; additional FX/dynmodel/lighting evidence"},
            {"completeness_scope","requested counted arrays and saved evidence only; not all live spawned entities or complete BO3 conversion"}};
        bool Complete=true;
        const auto Publish=[&](const std::string& Name,const json& Doc)
        { const bool Okay=Save(Directory,Name,Doc); Report["files"].push_back({{"file",Name},{"saved",Okay}}); Complete&=Okay; return Okay; };
        Publish("bo3_mapping.json",CWNonStaticPlacements::Mapping());
        json Models=json::array(), AllEntities=json::array(); size_t TotalEntities=0;
        const auto Resolve=[](uint64_t Hash)
        {
            const auto& DB=GameBlackOpsCW::AssetNameCache.NameDatabase;
            const auto It=DB.find(Hash&0xFFFFFFFFFFFFFFFull);
            return It==DB.end()?std::string():It->second;
        };
        for (const auto Index : {0x8Eu,0x80u})
        {
            const std::string Name=Index==0x8E?"entitylist":"triggers";
            const auto Root=FileSystems::CombinePath(Directory,"diagnostics/non_static/"+Name);
            TerrainResearch::Capture C(Root,Progress); Pool P;
            bool Okay=ReadPool(C,Pools,Index,Index==0x8E?24:72,P);
            json Source={{"pool",Index},{"loaded_assets",P.Loaded},{"entity_count",0},{"model_placements",0}};
            // Per-map singleton: never merge another map or overwrite a capture.
            if (Okay && P.Loaded==1)
            {
                for(uint32_t I=0;I<P.Capacity;++I) if(!P.Slots.Free.count(I))
                {
                    std::vector<uint8_t> Header(P.Headers.begin()+size_t(I)*P.Stride,P.Headers.begin()+size_t(I+1)*P.Stride);
                    if((TerrainResearch::U64(Header,0)&0xFFFFFFFFFFFFFFFull)!=MapHash) {Okay=false;Source["error"]="map_hash_mismatch";break;}
                    CWMapCandidateCapture::Capture(C,Index,Header);
                }
                const auto Typed=C.Report.value("typed_candidates",json::object());
                Okay=Okay && Typed.value("saved",false);
                if (Okay)
                {
                    json Decoded; std::ifstream Input(FileSystems::CombinePath(Root,"decoded_candidates.json")); Input>>Decoded;
                    auto Converted=CWNonStaticPlacements::Convert(Decoded,Name,Resolve);
                    Source["entity_count"]=Converted["entity_count"]; TotalEntities+=Converted["entity_count"].get<size_t>();
                    Source["model_placements"]=Converted["models"].size();
                    Source["rejected_model_entities"]=Converted["rejected_model_entities"];
                    for(auto& Group:Converted["entities"].items())
                    {
                        Publish("entities/"+Name+"/"+Group.key(),Group.value());
                        for(const auto& Entity:Group.value())AllEntities.push_back(Entity);
                    }
                    for(auto Row:Converted["models"])
                    {
                        ModelExportNaming::PublishPlacementName(Row); Row["BO3"]["model"]=Row["Name"];
                        Models.push_back(Row);
                    }
                    if(Index==0x80)
                    {
                        json Geometry=Decoded; Geometry.erase("entities");
                        Geometry["entity_reference_field"]="raw_reference_u32; semantics retained as candidate until verified";
                        Publish("trigger_geometry_candidates.json",Geometry);
                    }
                    Okay=Typed.value("complete",false) && Converted["rejected_model_entities"].empty();
                }
            }
            else if(Okay && P.Loaded!=0) {Okay=false;Source["error"]="expected_per_map_singleton";}
            const bool Unchanged=Stable(C,P); const bool Evidence=C.Finish();
            Source["source_unchanged"]=Unchanged; Source["evidence_saved"]=Evidence;
            Source["complete"]=Okay&&Unchanged&&Evidence; Complete&=Okay&&Unchanged&&Evidence;
            Report["sources"][Name]=Source;
        }
        Publish("non_static_models.json",Models);
        std::map<std::string,json> Classes;
        for(const auto& Row:Models)
        {
            const auto File=CWNonStaticPlacements::ClassFile(Row.at("ClassName"));
            if(!Classes.count(File)) Classes[File]=json::array();
            Classes[File].push_back(Row);
        }
        for(const auto& Group:Classes) Publish("non_static_models/"+Group.first,Group.second);
        Report["entity_count"]=TotalEntities; Report["model_placements"]=Models.size();
        // FX records are intentionally separate from model import JSON. This
        // measured layout has structural checks, but no BO3 semantic claim.
        {
            TerrainResearch::Capture C(FileSystems::CombinePath(Directory,"diagnostics/non_static/level_fx"),Progress); Pool P;
            bool Okay=ReadPool(C,Pools,0x7F,40,P) && P.Loaded<=1;
            json Rows=json::array(),EffectAssets=json::array();
            if(Okay && P.Loaded==1) for(uint32_t I=0;I<P.Capacity;++I) if(!P.Slots.Free.count(I))
            {
                std::vector<uint8_t> H(P.Headers.begin()+I*40,P.Headers.begin()+(I+1)*40);
                const auto Count=TerrainResearch::U32(H,8); const auto Address=TerrainResearch::U64(H,16);
                if((TerrainResearch::U64(H,0)&0xFFFFFFFFFFFFFFFull)!=MapHash || Count>200000) {Okay=false;break;}
                const auto Bytes=Count?C.Span(Address,uint64_t(Count)*80,"fx_records.bin","candidate 80-byte level FX records",false,"resident_scene"):std::vector<uint8_t>();
                if(Bytes.size()!=uint64_t(Count)*80) {Okay=false;break;}
                const auto Effects=CoDAssets::GameInstance->Read<uint64_t>(Pools+0x33*32);
                const auto EffectStride=CoDAssets::GameInstance->Read<uint32_t>(Pools+0x33*32+8);
                const auto EffectCapacity=CoDAssets::GameInstance->Read<uint32_t>(Pools+0x33*32+12);
                std::map<uint64_t,uint64_t> Hashes;
                std::map<uint64_t,json> AttachedNames;
                for(uint32_t J=0;J<Count;++J)
                {
                    const auto B=Bytes.data()+size_t(J)*80; uint64_t Effect=0; memcpy(&Effect,B,8);
                    float V[6]; memcpy(V,B+8,24); bool Valid=EffectStride==144 && Effect>=Effects &&
                        Effect-Effects<uint64_t(EffectCapacity)*144 && (Effect-Effects)%144==0;
                    for(float X:V) if(!std::isfinite(X)||std::abs(X)>1e7) Valid=false;
                    if(!Valid) Okay=false;
                    if(Valid && !Hashes.count(Effect))
                    {
                        const auto E=C.Span(Effect,144,"effects/"+std::to_string(Effect)+".bin","referenced FX asset header and name hash",false,"resident_scene");
                        if(E.size()!=144) {Okay=false;Valid=false;} else
                        {
                            Hashes[Effect]=TerrainResearch::U64(E,0);const auto Masked=Hashes[Effect]&0xFFFFFFFFFFFFFFFull;
                            auto Name=Resolve(Masked);
                            if(Name.empty()){const auto It=GameBlackOpsCW::StringCache.NameDatabase.find(Masked);if(It!=GameBlackOpsCW::StringCache.NameDatabase.end())Name=It->second;}
                            EffectAssets.push_back({{"EffectPointer",TerrainResearch::Hex(Effect)},{"EffectHash",TerrainResearch::Hex(Hashes[Effect])},
                                {"EffectHashMasked",TerrainResearch::Hex(Masked)},{"Name",Name.empty()?json(nullptr):json(Name)},{"NameResolved",!Name.empty()},
                                {"RawHeaderHex",RawHex(E.data(),144)},{"PlacementMeaning","asset definition; placements reference EffectPointer"}});
                            Okay=C.VerifySpan(Effect,E,"FX asset header")&&Okay;
                        }
                    }
                    std::string Raw; const char* Digits="0123456789abcdef";
                    for(size_t K=0;K<80;++K) {Raw+=Digits[B[K]>>4];Raw+=Digits[B[K]&15];}
                    Rows.push_back({{"SourceId",TerrainResearch::Hex(MapHash)+":level_fx:"+std::to_string(J)},
                        {"RecordIndex",J},{"RecordAddress",TerrainResearch::Hex(Address+uint64_t(J)*80)},
                        {"EffectPointer",TerrainResearch::Hex(Effect)}, {"EffectHash",Valid?json(TerrainResearch::Hex(Hashes[Effect])):json(nullptr)},
                        {"EffectHashMasked",Valid?json(TerrainResearch::Hex(Hashes[Effect]&0xFFFFFFFFFFFFFFFull)):json(nullptr)},
                        {"CandidatePosition",{V[0],V[1],V[2]}},{"CandidateAngles",{V[3],V[4],V[5]}},
                        {"StructuralValidation",Valid},{"RawRecordHex",Raw},
                        {"BO3Mapping",{{"status","unverified_layout_and_effect_asset_port_required"},{"classname",nullptr},{"origin",{V[0],V[1],V[2]}},{"angles",{V[3],V[4],V[5]}}}}});
                    auto& Row=Rows.back();Row["AttachedNameRecords"]=json::array();
                    const auto AttachedCount=CWMapCandidateCapture::U32(B+56);const auto AttachedAddress=CWMapCandidateCapture::U64(B+72);
                    Row["AttachedNameCountRaw"]=AttachedCount;Row["AttachedNamePointer"]=TerrainResearch::Hex(AttachedAddress);
                    if(AttachedCount>64){Okay=false;Row["AttachedNameStatus"]="count exceeds bounded candidate layout";continue;}
                    if(AttachedCount)
                    {
                        const auto AF="fx_names/records_"+std::to_string(J)+".bin";
                        const auto AB=C.Span(AttachedAddress,uint64_t(AttachedCount)*32,AF,"FX +56 count / +72 pointer: candidate 32-byte attached name records",false,"resident_scene");
                        if(AB.size()!=uint64_t(AttachedCount)*32){Okay=false;continue;}
                        for(uint32_t K=0;K<AttachedCount;++K)
                        {
                            const auto Q=AB.data()+K*32;const auto NP=CWMapCandidateCapture::U64(Q);
                            if(!AttachedNames.count(NP))
                            {
                                json Name=nullptr;MEMORY_BASIC_INFORMATION Region{};
                                if(TerrainResearch::Pointer(NP)&&VirtualQueryEx(CoDAssets::GameInstance->GetCurrentProcess(),reinterpret_cast<const void*>(NP),&Region,sizeof(Region)))
                                {
                                    const uint64_t End=reinterpret_cast<uint64_t>(Region.BaseAddress)+Region.RegionSize;
                                    if(End>NP)
                                    {
                                        const auto NF="fx_names/string_"+std::to_string(NP)+".bin";
                                        const auto NB=C.Span(NP,std::min<uint64_t>(1024,End-NP),NF,"bounded attached FX name string",false,"resident_scene");
                                        const auto Terminator=std::find(NB.begin(),NB.end(),0);
                                        if(Terminator!=NB.end()&&std::all_of(NB.begin(),Terminator,[](uint8_t X){return X>=32&&X<127;}))
                                        {
                                            Name=std::string(NB.begin(),Terminator);
                                            Okay=C.VerifySpan(NP,std::vector<uint8_t>(NB.begin(),Terminator+1),NF)&&Okay;
                                        }
                                    }
                                }
                                AttachedNames[NP]=Name;if(Name.is_null())Okay=false;
                            }
                            json Fields=json::object();for(size_t Offset=8;Offset<32;Offset+=4)Fields[TerrainResearch::Hex(Offset)]=CWMapCandidateCapture::U32(Q+Offset);
                            Row["AttachedNameRecords"].push_back({{"Index",K},{"RecordAddress",TerrainResearch::Hex(AttachedAddress+uint64_t(K)*32)},
                                {"NamePointer",TerrainResearch::Hex(NP)},{"Name",AttachedNames[NP]},{"RawFieldsU32",Fields},{"RawRecordHex",RawHex(Q,32)},
                                {"Meaning","attached name reference; event/state semantics and accompanying integer units unverified; not the FX asset name"}});
                        }
                        Okay=C.VerifySpan(AttachedAddress,AB,AF)&&Okay;
                    }
                }
                if(Count) Okay=C.VerifySpan(Address,Bytes,"fx_records.bin")&&Okay;
            }
            const bool Unchanged=Stable(C,P); const bool Evidence=C.Finish();
            Publish("fx_placement_candidates.json",Rows);
            for(auto& Row:Rows)
            {
                Row["EffectName"]=nullptr;Row["NameResolved"]=false;
                for(const auto& Asset:EffectAssets)if(Asset["EffectPointer"]==Row["EffectPointer"]){Row["EffectName"]=Asset["Name"];Row["NameResolved"]=Asset["NameResolved"];break;}
                Row["EffectAssetFile"]="fx_assets.json";
            }
            Publish("fx_placements.json",Rows);Publish("fx_assets.json",EffectAssets);
            Report["sources"]["level_fx"]={{"pool",0x7F},{"records",Rows.size()},
                {"structural_checks_passed",Okay},{"source_unchanged",Unchanged},{"evidence_saved",Evidence},
                {"semantic_status","candidate transforms; not model instances or a verified BO3 FX mapping"}};
            Complete&=Okay&&Unchanged&&Evidence;
        }
        {
            TerrainResearch::Capture C(FileSystems::CombinePath(Directory,"diagnostics/non_static/dynmodel"),Progress); Pool P;
            const bool Okay=ReadPool(C,Pools,0xD1,288,P); json Rows=json::array();
            if(Okay) for(uint32_t I=0;I<P.Capacity;++I) if(!P.Slots.Free.count(I))
            {
                json Fields=json::object();
                for(size_t O=0;O<288;O+=8) Fields[TerrainResearch::Hex(O)]=TerrainResearch::Hex(TerrainResearch::U64(P.Headers,size_t(I)*288+O));
                json Row={{"AssetSlot",I},{"AssetAddress",TerrainResearch::Hex(P.Base+uint64_t(I)*288)},
                    {"NameHashRaw",Fields["0xE0"]},{"RawQwords",Fields},
                    {"PlacementStatus","asset_definition; instance transforms not decoded"}};
                for(const auto Model:{true,false})
                {
                    const auto Ref=TerrainResearch::U64(P.Headers,size_t(I)*288+(Model?0xC8:0xD8));
                    const auto Descriptor=CoDAssets::GameInstance->Read<uint64_t>(Pools+(Model?6:2)*32);
                    const auto Stride=CoDAssets::GameInstance->Read<uint32_t>(Pools+(Model?6:2)*32+8);
                    const auto Capacity=CoDAssets::GameInstance->Read<uint32_t>(Pools+(Model?6:2)*32+12);
                    if(!Ref) continue;
                    json Link={{"pointer",TerrainResearch::Hex(Ref)},{"status","unresolved"}};
                    const uint32_t Expected=Model?232:112;
                    if(Stride==Expected && Ref>=Descriptor && Ref-Descriptor<uint64_t(Capacity)*Stride && (Ref-Descriptor)%Stride==0)
                    {
                        const auto HashBytes=C.Span(Ref,8,
                            std::string(Model?"models/":"physics/")+std::to_string(Ref)+".bin","referenced asset name hash",false,"resident_scene");
                        if(HashBytes.size()==8)
                        {
                            const auto Hash=TerrainResearch::U64(HashBytes,0)&0xFFFFFFFFFFFFFFFull;
                            Link["hash"]=TerrainResearch::Hex(Hash);Link["name"]=Resolve(Hash);
                            Link["status"]="pointer aligns with expected asset pool; reference candidate, not an instance";
                        }
                    }
                    Row[Model?"ModelReference":"PhysicsReference"]=Link;
                }
                Rows.push_back(Row);
            }
            const bool Unchanged=Stable(C,P); const bool Evidence=C.Finish();
            Publish("dynmodel_assets.json",Rows);
            Report["sources"]["dynmodel"]={{"pool",0xD1},{"assets",Rows.size()},
                {"complete",Okay&&Unchanged&&Evidence},{"placement_status","definitions only; not world placements"}};
            Complete&=Okay&&Unchanged&&Evidence;
        }
        {
            json Static;std::ifstream Input(FileSystems::CombinePath(Directory,"static_models.json"));Input>>Static;
            auto Focus=CWFXAnimationPlacements::Build(Static,Models,AllEntities);
            std::set<uint64_t> Requested,Found;
            for(const auto& Ref:Focus["named_animation_references"])Requested.insert(CWFXAnimationPlacements::Hash(Ref["Name"].get<std::string>()));
            TerrainResearch::Capture C(FileSystems::CombinePath(Directory,"diagnostics/non_static/animation_references"),Progress);Pool P;
            bool Okay=ReadPool(C,Pools,5,288,P);json Assets=json::array();
            if(Okay)for(uint32_t I=0;I<P.Capacity;++I)if(!P.Slots.Free.count(I))
            {
                const auto B=P.Headers.data()+size_t(I)*288;
                const auto Hash=TerrainResearch::U64(P.Headers,size_t(I)*288+0x70)&0xFFFFFFFFFFFFFFFull;
                const auto Name=Resolve(Hash);const bool Hint=CWFXAnimationPlacements::ModelHint(Name);
                if(!Requested.count(Hash)&&!Hint)continue;
                Found.insert(Hash);
                Assets.push_back({{"AnimationHash",TerrainResearch::Hex(Hash)},{"Name",Name.empty()?json(nullptr):json(Name)},
                    {"AssetSlot",I},{"RecordAddress",TerrainResearch::Hex(P.Base+uint64_t(I)*288)},
                    {"FrameRate",Float(B,0xB0)},{"Frequency",Float(B,0xB4)},{"FrameCount",CWProbeBounds::U16(B,0x104)},
                    {"BoneCount",CWProbeBounds::U16(B,0xFE)},{"NotificationCount",B[0x100]},
                    {"RawRecordHex",RawHex(B,288)},{"SelectionEvidence",{{"referenced_by_entity_property",Requested.count(Hash)>0},{"fxanim_name_hint",Hint}}},
                    {"PlacementMeaning","animation asset metadata; use named entity references for placement links; a name hint alone is not a link"}});
            }
            for(auto& Ref:Focus["named_animation_references"])
            {
                const auto Hash=CWFXAnimationPlacements::Hash(Ref["Name"].get<std::string>());
                Ref["LoadedAnimationMatch"]=Found.count(Hash)>0;
                Ref["AnimationHash"]=Found.count(Hash)?json(TerrainResearch::Hex(Hash)):json(nullptr);
            }
            const bool Unchanged=Stable(C,P),Evidence=C.Finish();Okay=Okay&&Unchanged&&Evidence;
            Publish("animation_assets.json",Assets);
            for(const auto& Group:Focus.items())Publish(Group.key()+".json",Group.value());
            json Catalog={{"schema","cw-fx-anm-placement-catalog-v1"},{"map_hash",TerrainResearch::Hex(MapHash)},
                {"files",json::array({"fx_placements.json","fx_assets.json","fx_entity_references.json","animation_model_placements.json","animation_entity_references.json","named_animation_references.json","animation_assets.json"})},
                {"animation_model_placements",Focus["animation_model_placements"].size()},
                {"animation_entities",Focus["animation_entity_references"].size()},{"fx_entities",Focus["fx_entity_references"].size()},
                {"named_animation_references",Focus["named_animation_references"].size()},{"animation_assets",Assets.size()},
                {"scope","placements, names, hashes, attached entity properties and animation metadata; no playback reconstruction"},
                {"complete",Okay}};
            Publish("fx_anm_catalog.json",Catalog);Report["sources"]["animation_references"]=Catalog;Complete&=Okay;
        }
        Report["sources"]["lighting"]=Lighting(Pools,Directory,MapHash,Progress);
        Complete&=Report["sources"]["lighting"].value("complete",false);
        for(const char* File:{"light_placement_candidates.json","light_placements.json","reflection_probes.json","reflection_probe_bounds.json","sun_volumes.json"})
            Report["files"].push_back({{"file",File},{"saved",FileSystems::FileExists(FileSystems::CombinePath(Directory,File))}});
        Report["complete"]=Complete;
        if(!Save(Directory,"non_static_report.json",Report)) Report["complete"]=false;
        return Report;
    }
}
