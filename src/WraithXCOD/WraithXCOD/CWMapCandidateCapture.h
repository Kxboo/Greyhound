#pragma once
#include <cmath>
#include "TerrainResearchCapture.h"
#include "CWMapCandidateLayout.h"
#include "CWMapEntityExport.h"

// Candidate layouts measured from live CW captures. Preserve bytes and unknown
// fields; these are deliberately not represented as validated BO3 geometry.
namespace CWMapCandidateCapture
{
    inline uint64_t U64(const uint8_t* P) { uint64_t V; memcpy(&V,P,8); return V; }
    inline uint32_t U32(const uint8_t* P) { uint32_t V; memcpy(&V,P,4); return V; }
    inline void Capture(TerrainResearch::Capture& C, uint32_t Pool,
        const std::vector<uint8_t>& Header)
    {
        using namespace TerrainResearch;
        if ((Pool != 0x80 && Pool != 0x8E) || Header.size() != (Pool == 0x80 ? 72 : 24)) return;
        json Result = {{"schema", "cw-map-layout-candidates-v2"},
            {"layout_status", "candidate layout; checked counts and readable ranges, semantics require cross-map validation"},
            {"source_pool", Pool}, {"source_name_hash", Hex(U64(Header.data()))},
            {"complete", false}, {"entities", json::array()}, {"arrays", json::array()}};
        bool Complete = true;
        struct VerifyRecord {uint64_t Address; std::string File; std::vector<uint8_t> Bytes;};
        std::vector<VerifyRecord> Verify;
        uint64_t VerifyBytes=0;
        auto Remember = [&](uint64_t A,const std::string& F,const std::vector<uint8_t>& B)
        {
            if(B.size()>32ull*1024*1024-VerifyBytes) {Complete=false; return;}
            if(!B.empty()) {Verify.push_back({A,F,B}); VerifyBytes+=B.size();}
        };
        auto Array = [&](uint64_t Address, uint32_t Count, uint32_t Stride, const std::string& File)
        {
            std::vector<uint8_t> B;
            if (Count > 200000 || (Count && !Pointer(Address))) Complete = false;
            else if (Count) B = C.Span(Address, uint64_t(Count)*Stride, File,
                "counted candidate layout; raw bytes authoritative, stride hypothesis recorded", false, "resident_scene");
            if (B.size() != uint64_t(Count)*Stride) Complete = false;
            Remember(Address,File,B);
            Result["arrays"].push_back({{"address", Hex(Address)}, {"count", Count},
                {"candidate_stride", Stride}, {"file", File}, {"captured_bytes", B.size()}});
            return B;
        };
        // Header count/pointer pairs; trigger arrays end exactly where the next
        // begins in the first live sample (323*8, 357*32, 576*20 bytes).
        if (Pool == 0x80)
        {
            const auto Models=Array(U64(Header.data()+16), U32(Header.data()+8), 8, "typed/trigger_models.bin");
            const auto Hulls=Array(U64(Header.data()+32), U32(Header.data()+24), 32, "typed/trigger_hulls.bin");
            const auto Slabs=Array(U64(Header.data()+48), U32(Header.data()+40), 20, "typed/trigger_slabs.bin");
            const auto Check=CWMapCandidateLayout::Check(Models,Hulls,Slabs);
            Result["geometry_validation"]={{"candidate_layout_valid",Check.Valid()},
                {"record_sizes_valid",Check.RecordSizesValid},{"bad_model_ranges",Check.BadModelRanges},
                {"bad_hull_ranges",Check.BadHullRanges},{"bad_bounds",Check.BadBounds},
                {"bad_slabs",Check.BadSlabs},{"referenced_hulls",Check.ReferencedHulls},
                {"referenced_slabs",Check.ReferencedSlabs},
                {"interpretation","model +4/+6: u16 hull count/start; hull +28/+30: u16 slab count/start; unproven gameplay semantics"}};
            if(!Check.Valid()) Complete=false;
            Result["trigger_models"]=json::array();
            for(size_t I=0;I<Models.size()/8;++I)
            {
                const auto B=Models.data()+I*8;
                Result["trigger_models"].push_back({{"index",I},{"raw_contents_u32",U32(B)},
                    {"hull_count",CWMapCandidateLayout::U16(B+4)},{"first_hull",CWMapCandidateLayout::U16(B+6)}});
            }
        }
        const auto CountOffset = Pool == 0x80 ? 56 : 8;
        const auto Count = U32(Header.data()+CountOffset);
        const auto Address = U64(Header.data()+CountOffset+8);
        const auto Records = Array(Address, Count, 48, "typed/entity_records.bin");
        std::map<uint64_t, json> Strings;
        auto String = [&](uint64_t P) -> json
        {
            const auto Found = Strings.find(P); if (Found != Strings.end()) return Found->second;
            json S = {{"address", Hex(P)}, {"terminated", false}};
            MEMORY_BASIC_INFORMATION M{};
            if (Pointer(P) && VirtualQueryEx(CoDAssets::GameInstance->GetCurrentProcess(),
                reinterpret_cast<const void*>(P), &M, sizeof(M)))
            {
                const auto Base = reinterpret_cast<uint64_t>(M.BaseAddress);
                if (Base <= P && M.RegionSize <= UINT64_MAX - Base && Base+M.RegionSize>P)
                {
                    const auto B = C.Span(P, std::min<uint64_t>(1024,Base+M.RegionSize-P),
                        "typed/strings/"+Hex(P)+".bin", "candidate C string; bounded 1024-byte prefix", false, "resident_scene");
                    const auto End = std::find(B.begin(), B.end(), 0);
                    if (End != B.end())
                    {
                        Remember(P,"typed/strings/"+Hex(P)+".bin",std::vector<uint8_t>(B.begin(),End+1));
                        // Do not hand invalid UTF-8 to the JSON writer. Preserve
                        // non-ASCII bytes in the source file for later decoding.
                        S["terminated"] = true;
                        if (std::all_of(B.begin(), End, [](uint8_t Ch){return Ch >= 32 && Ch < 127;}))
                            S["text"] = std::string(B.begin(), End);
                        else S["encoding"] = "non_ascii_or_control_bytes; see raw capture";
                    }
                }
            }
            if (!S.value("terminated", false)) Complete = false;
            Strings[P]=S; return S;
        };
        uint64_t PropertyTotal = 0;
        for (size_t I=0; I<Records.size()/48; ++I)
        {
            const auto R = Records.data()+I*48;
            const auto N = U32(R); const auto Properties = U64(R+8);
            json E = {{"index", I}, {"record_address", Hex(Address+I*48)},
                {"raw_reference_u32", U32(R+16)}, {"raw_id_u32", U32(R+20)},
                {"property_count", N}, {"properties", json::array()}};
            E["record_vector_candidates"]=json::array();
            for(size_t V=24;V<48;V+=12)
            {
                float XYZ[3];memcpy(XYZ,R+V,12);
                if(std::isfinite(XYZ[0])&&std::isfinite(XYZ[1])&&std::isfinite(XYZ[2]))
                    E["record_vector_candidates"].push_back({XYZ[0],XYZ[1],XYZ[2]});
                else {E["record_vector_candidates"].push_back(nullptr);Complete=false;}
            }
            PropertyTotal += N;
            if (N>4096 || PropertyTotal>1000000) { Complete=false; E["error"]="property_count_limit"; }
            else
            {
                const auto B = Array(Properties,N,32,"typed/properties_"+std::to_string(I)+".bin");
                for(size_t J=0; J<B.size()/32; ++J)
                {
                    const auto K=B.data()+J*32;
                    uint16_t Type; memcpy(&Type,K+24,2);
                    json V={{"key",String(U64(K))},{"type_tag",Type}, {"raw_tag_u32",U32(K+24)}};
                    std::string Raw;static const char HexDigits[]="0123456789abcdef";
                    for(size_t X=8;X<24;++X){Raw+=HexDigits[K[X]>>4];Raw+=HexDigits[K[X]&15];}
                    V["raw_value_hex"]=Raw;
                    if(Type==2) V["string_candidate"]=String(U64(K+8));
                    else if(Type==3)
                    {
                        float XYZ[3]; memcpy(XYZ,K+8,12);
                        if(std::isfinite(XYZ[0])&&std::isfinite(XYZ[1])&&std::isfinite(XYZ[2]))
                            V["vector_candidate"]={XYZ[0],XYZ[1],XYZ[2]};
                        else {V["error"]="nonfinite_vector"; Complete=false;}
                    }
                    else if(Type==4) V["asset_hash_candidate"]=Hex(U64(K+8));
                    else if(Type==5)
                    {
                        const auto F=CWMapCandidateLayout::F32(K+8);
                        if(std::isfinite(F))V["float_candidate"]=F;
                        else {V["error"]="nonfinite_float";Complete=false;}
                    }
                    else if(Type==6)
                    {
                        int32_t Signed;memcpy(&Signed,K+8,4);
                        V["int32_candidate"]=Signed;V["uint32_candidate"]=U32(K+8);
                    }
                    else V["value_status"]="unknown_type; retained in property bytes";
                    E["properties"].push_back(V);
                }
            }
            Result["entities"].push_back(E);
        }
        bool Stable=true;
        for(const auto& V:Verify)if(!C.VerifySpan(V.Address,V.Bytes,V.File))Stable=false;
        Result["capture_reads_complete"]=Complete;
        Result["readback_unchanged"]=Stable;
        Result["verification_ranges"]=Verify.size();
        Result["verification_bytes"]=VerifyBytes;
        Result["complete"] = Complete && Stable;
        Result["completeness_scope"] = "candidate counted arrays, terminated strings, range checks and second-read equality; not atomic or proof of semantics";
        Result["unique_strings"] = Strings.size();
        const auto Text = Result.dump(2);
        const bool Saved = C.Write("decoded_candidates.json", reinterpret_cast<const uint8_t*>(Text.data()),Text.size());
        C.Report["typed_candidates"]={{"file","decoded_candidates.json"},{"saved",Saved},
            {"complete",Complete&&Stable},{"readback_unchanged",Stable},
            {"entity_records",Records.size()/48},{"unique_strings",Strings.size()}};
        // Same values, rendered as a flat key/value document for diffing
        // against an independent export of the same map.
        CWMapEntityExport::Emit(C, Pool, Result);
    }
}
