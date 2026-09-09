#pragma once
#include "TerrainResearchCapture.h"
#include "CWMapCandidateCapture.h"
#include "CWPoolProbe.h"

// Current-build field profile. Captured with the payloads, never joined to an
// older map's filter table. Null-pointer shapes are handled as unresolved offline.
namespace CWBrushTypeCapture
{
    using namespace TerrainResearch;
    inline uint32_t U32(const uint8_t* P) {uint32_t V;memcpy(&V,P,4);return V;}
    inline uint64_t U64(const uint8_t* P) {uint64_t V;memcpy(&V,P,8);return V;}
    struct Types
    {
        struct Span {uint64_t Address;std::vector<uint8_t> Bytes;std::string File;};
        std::vector<Span> Spans;
        json Data;
        bool Ready=false;
        std::vector<uint8_t> Read(Capture& C,uint64_t Address,uint64_t Size,const std::string& File)
        {
            auto B=C.Span(Address,Size,File,"capture-paired collision type metadata",false,"structure");
            if(B.size()==Size)Spans.push_back({Address,B,File});
            return B;
        }
        void Begin(Capture& C,uint64_t PoolTable,const std::vector<uint8_t>& Header)
        {
            const auto Base=CoDAssets::GameInstance->GetMainModuleAddress();
            Data={{"schema","cw-native-brush-types-v2"},{"readback_unchanged",false},
                  {"status","unsupported_build_or_short_read"},{"named_flags",json::array()},
                  {"traversal_flags",json::array()},{"traversal_mask","0x38000000"},
                  {"filter_entries",json::array()}};
            if(PoolTable-Base!=0x1273C9F0 || Header.size()!=472)return;
            Data["map_hash"]=Hex(U64(Header.data()));
            auto Root=Read(C,Base+0x1A109E60,8,"types/clip_root.bin");
            if(Root.size()!=8 || !Pointer(U64(Root.data())))return;
            auto Identity=Read(C,U64(Root.data()),8,"types/map_identity.bin");
            if(Identity.size()!=8 || U64(Identity.data())!=U64(Header.data()))return;
            auto Count=Read(C,Base+0x1A108880,4,"types/filter_count.bin");
            if(Count.size()!=4 || !U32(Count.data()) || U32(Count.data())>1024)return;
            auto Filters=Read(C,Base+0x1A109E70,uint64_t(U32(Count.data()))*8,"types/filters.bin");
            auto Names=Read(C,Base+0xD66B770,39*24,"types/named_flags.bin");
            if(Filters.size()!=uint64_t(U32(Count.data()))*8 || Names.size()!=39*24)return;
            bool Slick=false,Player=false;
            for(uint32_t I=0;I<39;++I)
            {
                const auto P=Names.data()+I*24;
                if(!Pointer(U64(P)))return;
                auto B=Read(C,U64(P),96,"types/name_"+std::to_string(I)+".bin");
                auto End=std::find(B.begin(),B.end(),0);
                if(B.size()!=96 || End==B.end() || End==B.begin() ||
                    !std::all_of(B.begin(),End,[](uint8_t V){return V>=32 && V<127;}))return;
                std::string Name(B.begin(),End);
                Data["named_flags"].push_back({{"name",Name},{"field_8",U32(P+8)},
                    {"field_12",Hex(U32(P+12))},{"field_16",Hex(U32(P+16))},{"field_20",Hex(U32(P+20))}});
                Slick|=Name=="slick" && U32(P+12)==2;
                Player|=Name=="playerClip" && U32(P+16)==0x10000;
            }
            for(size_t I=0;I<Filters.size()/8;++I)
                Data["filter_entries"].push_back({{"index",I},{"surface_raw",Hex(U32(Filters.data()+I*8))},
                    {"contents_raw",Hex(U32(Filters.data()+I*8+4))}});
            // These are mutually exclusive values, not independent flags:
            // mantleOver (3) must not also decode as ladder (1) and mantleOn (2).
            auto Traversal=Read(C,Base+0xD66B6F0,5*24,"types/traversal_flags.bin");
            if(Traversal.size()!=5*24)return;
            const char* Expected[]={"ladder","mantleOn","mantleOver","climbWall","climbPipe"};
            for(uint32_t I=0;I<5;++I)
            {
                const auto P=Traversal.data()+I*24;
                if(!Pointer(U64(P)) || U32(P+12)!=((I+1)<<27))return;
                auto B=Read(C,U64(P),96,"types/traversal_name_"+std::to_string(I)+".bin");
                auto End=std::find(B.begin(),B.end(),0);
                if(B.size()!=96 || End==B.end())return;
                std::string Name(B.begin(),End);
                if(Name!=Expected[I])return;
                Data["traversal_flags"].push_back({{"name",Name},{"field_8",U32(P+8)},
                    {"field_12",Hex(U32(P+12))},{"field_16",Hex(U32(P+16))},{"field_20",Hex(U32(P+20))}});
            }
            Ready=Slick && Player;
        }
        bool Finish(Capture& C)
        {
            bool Stable=Ready;
            for(const auto& S:Spans)if(!C.VerifySpan(S.Address,S.Bytes,S.File))Stable=false;
            Data["readback_unchanged"]=Stable;Data["status"]=Stable?"captured":"failed";
            Data["scope"]="Global table candidates; only pointer-backed shapes with matching contents unions may use surface labels";
            const auto Text=Data.dump(2);
            const bool Saved=C.Write("brush_type_capture.json",reinterpret_cast<const uint8_t*>(Text.data()),Text.size());
            C.Report["brush_type_capture"]={{"saved",Saved},{"readback_unchanged",Stable},{"file","brush_type_capture.json"}};
            return Saved && Stable;
        }
    };

    inline bool Volumes(const std::string& Directory,uint64_t PoolTable,uint64_t MapHash)
    {
        if(!CreateDirectoryA(Directory.c_str(),nullptr))return false;
        Capture C(Directory,{});C.Report["pool_index"]=0x80;
        const auto Address=PoolTable+0x80*32;
        const auto Start=C.Span(Address,32,"descriptor_start.bin","TRIGGERLIST pool descriptor");
        if(Start.size()!=32){C.Finish();return false;}
        const auto Base=U64(Start.data());const auto Stride=U32(Start.data()+8),Capacity=U32(Start.data()+12);
        // The pool descriptor's loaded count and free head use the same layout
        // as GameBlackOpsCW::ExportResearchPool.
        const auto Loaded=U32(Start.data()+20);const auto FreeHead=U64(Start.data()+24);
        if(Stride!=72 || !Capacity || Capacity>200000 || Loaded!=1 || !Pointer(Base)){C.Finish();return false;}
        const auto Headers=C.Span(Base,uint64_t(Stride)*Capacity,"headers.bin","complete trigger pool including free slots");
        C.Report["pool"]={{"address",Hex(Base)},{"asset_size",Stride},{"capacity",Capacity},
            {"loaded",Loaded},{"free_head",Hex(FreeHead)}};
        const auto Occupancy=CWPoolProbe::FreeSlots(Headers,Stride,Base,FreeHead,Loaded);
        bool Found=false;
        if(Headers.size()==uint64_t(Stride)*Capacity && Occupancy.Valid)
            for(uint32_t I=0;I<Capacity;++I)if(!Occupancy.Free.count(I))
            {
                std::vector<uint8_t> H(Headers.begin()+I*Stride,Headers.begin()+(I+1)*Stride);
                if(U64(H.data())==MapHash){CWMapCandidateCapture::Capture(C,0x80,H);Found=true;}
            }
        const auto End=C.Span(Address,32,"descriptor_end.bin","trigger descriptor readback",true);
        const bool Stable=End==Start && C.VerifySpan(Base,Headers,"headers.bin");
        C.Report["descriptor_unchanged"]=End==Start;C.Report["headers_readback_unchanged"]=Stable;
        const auto Typed=C.Report.value("typed_candidates",json::object());
        const bool Complete=Found && Stable && Typed.value("complete",false) && Typed.value("saved",false) && Typed.value("readback_unchanged",false);
        C.Report["required_reads_saved"]=Complete;
        const bool Saved=C.Finish();return Complete && Saved;
    }
}
