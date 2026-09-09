#pragma once
#include <map>
#include <set>
#include <stdexcept>
#include "TerrainResearchCapture.h"
#include "CWClipModelExport.h"

// Current-build collision query path, independent of map-specific counts.
// This exports collision ownership/transforms, not render XModel placement.
namespace CWCollisionWorldCapture
{
    using TerrainResearch::json;
    using TerrainResearch::Hex;
    using CWClipModelExport::U32;
    using CWClipModelExport::U64;
    using CWClipModelExport::F32;
    inline void Capture(TerrainResearch::Capture& C, const std::vector<uint8_t>& Header, const json& Models)
    {
        json Result={{"schema","cw-collision-world-instances-v1"},{"status","incomplete"},
            {"layout_profile","current CW build: root RVA 0x1a109e60, stream table RVA 0x1907cbc8"},
            {"scope","Collision instances; no render model owner inferred. Stable reads are not an atomic game snapshot."}};
        uint64_t Charged=0;
        try
        {
            const auto Base=CoDAssets::GameInstance->GetMainModuleAddress();
            auto Take=[&](uint64_t At,uint64_t Size,const std::string& Label)
            {
                if (!TerrainResearch::Pointer(At) || !Size || Size>16ull*1024*1024 || Charged+Size*2>96ull*1024*1024)
                    throw std::runtime_error("Collision-world read bound exceeded");
                Charged+=Size*2;
                const std::string Prefix="typed/collision_worlds/"+Label;
                auto A=C.Span(At,Size,Prefix+"_a.bin","collision query-path data",false,"structure",true);
                auto B=C.Span(At,Size,Prefix+"_b.bin","independent collision readback",false,"structure",true);
                if (A.size()!=Size || B!=A) throw std::runtime_error("Unreadable or changed collision-world span: "+Label);
                return A;
            };
            if (Header.size()!=472 || Models.empty()) throw std::runtime_error("Missing CLIP_MAP header/model inventory");
            const auto RootPointer=Take(Base+0x1a109e60,8,"root_pointer");
            const auto Root=U64(RootPointer.data());
            if (Take(Root,472,"header")!=Header) throw std::runtime_error("Current-build root does not match exported CLIP_MAP");
            const uint32_t ModelCount=U32(Header.data()+0x1a8);
            const uint64_t ModelTable=U64(Header.data()+0x40);
            if (!ModelCount || ModelCount>65536 || Models.size()!=ModelCount) throw std::runtime_error("Incomplete collision model inventory");
            const auto ModelPointers=Take(ModelTable,ModelCount*8ull,"model_pointers");
            std::map<uint64_t,size_t> Lookup;
            for (size_t I=0;I<Models.size();++I)
            {
                const auto Address=std::stoull(Models[I].at("record_address").get<std::string>(),nullptr,0);
                if (!Lookup.emplace(Address,I).second) throw std::runtime_error("Duplicate collision record address");
            }
            for (uint32_t I=0;I<ModelCount;++I)
                if (!Lookup.count(U64(ModelPointers.data()+I*8ull))) throw std::runtime_error("Collision table differs from decoded model inventory");
            uint16_t Count;memcpy(&Count,Header.data()+0x1ce,2);
            if (!Count || Count>128) throw std::runtime_error("Invalid collision world count");
            const auto SelectorAt=U64(Header.data()+16);
            const auto Selectors=Take(SelectorAt,Count*4ull,"selectors");
            std::set<uint32_t> IDs;uint32_t MaxID=0;
            for (uint16_t I=0;I<Count;++I) {auto ID=U32(Selectors.data()+I*4);if(ID>=4096 || !IDs.insert(ID).second) throw std::runtime_error("Invalid world selector");MaxID=std::max(MaxID,ID);}
            auto Active=[&](const std::string& Phase)
            {
                // Keep disk writes outside the selector/header/IDs stability window.
                // The double-buffer selector can flip every frame even when IDs agree.
                std::vector<std::pair<json,std::vector<uint8_t>>> Pending;
                auto Flush=[&]()
                {
                    bool Saved=true;
                    for(auto& Item:Pending)
                    {
                        const bool Ok=C.Write(Item.first["file"].get<std::string>(),Item.second.data(),Item.second.size());
                        Item.first["status"]=Ok?"captured":"write_failed";
                        C.Report["reads"].push_back(Item.first);Saved=Saved && Ok;
                    }
                    Pending.clear();return Saved;
                };
                auto ReadActive=[&](uint64_t At,uint64_t Size,const std::string& Label)
                {
                    if(Charged+Size>96ull*1024*1024)
                        throw std::runtime_error("Active-list read bound exceeded");
                    Charged+=Size;json R;
                    auto Bytes=C.DeferredSmallRead(At,Size,"typed/collision_worlds/"+Label+".bin",R);
                    if(Bytes.size()!=Size)
                    {
                        C.Report["reads"].push_back(R);
                        throw std::runtime_error("Incomplete active-list read");
                    }
                    Pending.push_back({R,Bytes});
                    return Bytes;
                };
                try
                {
                for (int Retry=0;Retry<8;++Retry)
                {
                    const auto Tag=Phase+"_"+std::to_string(Retry);
                    const auto Index=ReadActive(Base+0x19076a3c,4,Tag+"_index");const auto Slot=U32(Index.data());
                    if (Slot>=8) throw std::runtime_error("Invalid active-list selector");
                    const auto At=Base+0x1907ab40+Slot*0x1040ull;const auto H=ReadActive(At,24,Tag+"_header");const auto N=U32(H.data());
                    if (!N || N>1024) throw std::runtime_error("Invalid active-world count");
                    const auto Data=ReadActive(U64(H.data()+16),N*4ull,Tag+"_ids");
                    const auto DataFinal=ReadActive(U64(H.data()+16),N*4ull,Tag+"_ids_final");
                    const auto HeaderFinal=ReadActive(At,24,Tag+"_header_final");
                    const auto IndexFinal=ReadActive(Base+0x19076a3c,4,Tag+"_index_final");
                    const bool Stable=DataFinal==Data && HeaderFinal==H && IndexFinal==Index;
                    C.Report["collision_active_list_checks"].push_back({{"phase",Phase},{"attempt",Retry},
                        {"selector_unchanged",IndexFinal==Index},{"header_unchanged",HeaderFinal==H},{"ids_unchanged",DataFinal==Data}});
                    if (!Flush()) throw std::runtime_error("Active-list evidence write failed");
                    if (!Stable) continue;
                    std::set<uint32_t> Found;for(uint32_t I=0;I<N;++I) Found.insert(U32(Data.data()+I*4));return Found;
                }
                }
                catch(...) {Flush();throw;}
                throw std::runtime_error("Active list did not stabilize");
            };
            const auto ActiveBefore=Active("active_before");
            for(auto ID:IDs) if(!ActiveBefore.count(ID)) throw std::runtime_error("Collision world not active");
            const auto Stream=Take(Base+0x1907cbc8,(MaxID+1ull)*80,"stream_table");
            json Instances=json::array(),Worlds=json::array();uint64_t Total=0;
            for(uint16_t W=0;W<Count;++W)
            {
                const auto ID=U32(Selectors.data()+W*4);const auto At=U64(Stream.data()+ID*80ull+72);
                const auto Label="world_"+std::to_string(W);const auto H=Take(At,64,Label+"_header");
                const auto N=U32(H.data()+48);const auto Ptr=U64(H.data()+40);
                if(N>200000 || Total+N>1000000) throw std::runtime_error("Collision instance count exceeds bound");
                Total+=N;const auto Bytes=N?Take(Ptr,N*80ull,Label+"_instances"):std::vector<uint8_t>{};
                for(uint32_t I=0;I<N;++I)
                {
                    const auto R=Bytes.data()+I*80ull;const auto Collision=U64(R);const auto Found=Lookup.find(Collision);
                    if(Found==Lookup.end()) throw std::runtime_error("Collision instance points outside exported inventory");
                    const float Inv=F32(R+24);double Norm=0;
                    for(size_t O=12;O<68;O+=4) if(!std::isfinite(F32(R+O))) throw std::runtime_error("Nonfinite collision transform");
                    for(size_t O=28;O<44;O+=4) Norm+=double(F32(R+O))*F32(R+O);
                    if(Inv<=0 || std::fabs(Norm-1)>0.000002) throw std::runtime_error("Invalid collision scale/quaternion");
                    Instances.push_back({{"collision_world",W},{"global_world_id",ID},{"instance_index",I},
                        {"record_address",Hex(Ptr+I*80ull)},{"collision_pointer",Hex(Collision)},{"model_index",Found->second},
                        {"name_hash",Models[Found->second].at("name_hash")},{"raw_word_08",Hex(U32(R+8))},
                        {"position",{F32(R+12),F32(R+16),F32(R+20)}},{"stored_inverse_scale",Inv},{"uniform_scale",1.0/double(Inv)},
                        {"quaternion_xyzw",{F32(R+28),F32(R+32),F32(R+36),F32(R+40)}},
                        {"stored_world_mins",{F32(R+44),F32(R+48),F32(R+52)}},{"stored_world_maxs",{F32(R+56),F32(R+60),F32(R+64)}}});
                }
                if(Take(At,64,Label+"_header_final")!=H) throw std::runtime_error("World header changed");
                Worlds.push_back({{"world",W},{"global_world_id",ID},{"instances",N}});
            }
            if(Take(Root,472,"header_final")!=Header || Take(ModelTable,ModelCount*8ull,"model_pointers_final")!=ModelPointers ||
                Take(SelectorAt,Count*4ull,"selectors_final")!=Selectors || Take(Base+0x1907cbc8,Stream.size(),"stream_table_final")!=Stream ||
                Take(Base+0x1a109e60,8,"root_pointer_final")!=RootPointer || Active("active_after")!=ActiveBefore)
                throw std::runtime_error("Collision root/active worlds changed during capture");
            Result["status"]="captured";Result["map_hash"]=Hex(U64(Header.data()));Result["worlds"]=Worlds;Result["instances"]=Instances;
            Result["summary"]={{"collision_assets",ModelCount},{"collision_worlds",Count},{"collision_instances",Total},{"all_pointer_joins_verified",true}};
        }
        catch(const std::exception& Error) { Result["status"]="failed";Result["error"]=Error.what(); }
        Result["read_bytes"]=Charged;
        const auto Text=Result.dump(2);const bool Saved=C.Write("collision_world_instances.json",reinterpret_cast<const uint8_t*>(Text.data()),Text.size());
        C.Report["collision_world_instances"]={{"file","collision_world_instances.json"},{"saved",Saved},{"status",Result["status"]},{"read_bytes",Charged}};
    }
}
