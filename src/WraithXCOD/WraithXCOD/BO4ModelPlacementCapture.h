#pragma once
#include <fstream>
#include "ModelExportNaming.h"

// BO4 gfxworld references and their 64-byte target records. Keep this capture
// independent of the clipmap: non-colliding render models belong here too.
template <typename PoolList, typename ResolveName>
bool CaptureBO4ModelPlacements(const PoolList& Pools, const std::string& Path, ResolveName Resolve,
    const std::string& PublishPath = {}, const std::string& NameDatabase = "bundled", std::string* Failure = nullptr)
{
    const auto Hex = [](uint64_t V) { return Strings::Format("0x%llX", V); };
    std::string Stage="begin";
    nlohmann::json Detail=nlohmann::json::object();
    const auto Fail=[&](const std::string& Reason) {
        const auto Message=Stage+": "+Reason;
        if (Failure) *Failure=Message;
        std::ofstream Out(FileSystems::CombinePath(Path,"placement_error.json"),std::ios::binary);
        Out<<nlohmann::json({{"stage",Stage},{"reason",Reason},{"details",Detail},{"complete",false}}).dump(2);
        return false;
    };
    const auto Read = [&](uint64_t P, uint64_t N) -> std::unique_ptr<int8_t[]> {
        if (!P || !N || N > (64ull << 20)) return nullptr;
        Detail["read_pointer"]=Hex(P); Detail["read_bytes"]=N;
        uintptr_t A=0,B=0;
        std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(P,N,A));
        std::unique_ptr<int8_t[]> Y(CoDAssets::GameInstance->Read(P,N,B));
        Detail["first_bytes_read"]=A; Detail["second_bytes_read"]=B;
        if (!X || !Y || A!=N || B!=N) return nullptr;
        if (std::memcmp(X.get(),Y.get(),size_t(N))) {
            for (uint64_t I=0;I<N;++I) if (X[I]!=Y[I]) { Detail["changed_offset"]=Hex(I); break; }
            return nullptr;
        }
        return X;
    };
    const auto Save = [&](const int8_t* B, uint64_t N, const std::string& File) {
        BinaryWriter W; if (!W.Create(FileSystems::CombinePath(Path,File))) return Fail("validation rejected");
        W.Write(B,uint32_t(N)); W.Close(); return true;
    };
    Stage="pool_layout";
    const auto& G=Pools[14]; const auto& M=Pools[4];
    Detail={{"gfx_asset_size",G.AssetSize},{"gfx_loaded",G.AssetsLoaded},{"gfx_capacity",G.PoolSize},{"model_asset_size",M.AssetSize}};
    if (G.AssetSize!=6832 || G.AssetsLoaded!=1 || M.AssetSize!=sizeof(BO4XModel)) return Fail("validation rejected");
    const uint64_t Span=uint64_t(G.AssetSize)*G.PoolSize;
    Stage="gfx_pool_read";
    auto Pool=Read(G.PoolPtr,Span); if (!Pool) return Fail("validation rejected");
    Stage="gfx_pool_occupancy";
    std::set<uint32_t> Free; uint64_t Next=G.PoolFreeHeadPtr;
    while (Next) {
        if (Next<G.PoolPtr || Next-G.PoolPtr>=Span || (Next-G.PoolPtr)%G.AssetSize) return Fail("validation rejected");
        auto Slot=uint32_t((Next-G.PoolPtr)/G.AssetSize);
        if (!Free.insert(Slot).second) return Fail("validation rejected");
        std::memcpy(&Next,Pool.get()+uint64_t(Slot)*G.AssetSize,8);
    }
    if (Free.size()+1!=G.PoolSize) return Fail("validation rejected");
    uint32_t Slot=0; while (Free.count(Slot)) ++Slot;
    const auto H=Pool.get()+uint64_t(Slot)*G.AssetSize;
    uint32_t Count=0; uint64_t Refs=0,Transforms=0,Hash=0;
    std::memcpy(&Count,H+0x1BC,4); std::memcpy(&Refs,H+0x400,8);
    std::memcpy(&Transforms,H+0x408,8); std::memcpy(&Hash,H,8); Hash&=0xfffffffffffffff;
    Stage="instance_count"; Detail["instance_count"]=Count;
    if (!Count || Count>500000) return Fail("validation rejected");
    Stage="references_read";
    auto R=Read(Refs,uint64_t(Count)*56); if (!R) return Fail("read failed or changed");
    Stage="transforms_read";
    auto T=Read(Transforms,uint64_t(Count)*64);
    if (!R || !T) return Fail("validation rejected");
    nlohmann::json Report={{"schema","greyhound-bo4-model-placement-capture-v1"},
        {"map_hash",Hex(Hash)},{"instance_count",Count},{"reference_stride",56},
        {"transform_stride",64},{"reference_pointer",Hex(Refs)},{"transform_pointer",Hex(Transforms)},
        {"reference_file","gfx_model_references.bin"},{"transform_file","gfx_model_transforms.bin"},
        {"models",nlohmann::json::array()}};
    Stage="transform_reference_range";
    std::set<uint64_t> Models;
    for (uint32_t I=0; I<Count; ++I) {
        uint64_t P=0,Q=0; std::memcpy(&P,R.get()+uint64_t(I)*56,8);
        std::memcpy(&Q,R.get()+uint64_t(I)*56+24,8);
        if (Q<Transforms || Q-Transforms>=uint64_t(Count)*64 || (Q-Transforms)%64) return Fail("validation rejected");
        Models.insert(P);
    }
    std::vector<int8_t> Headers;
    Stage="model_headers";
    for (auto P:Models) {
        if (P<M.PoolPtr || P-M.PoolPtr>=uint64_t(M.AssetSize)*M.PoolSize || (P-M.PoolPtr)%M.AssetSize) return Fail("validation rejected");
        auto B=Read(P,M.AssetSize); if (!B) return Fail("validation rejected");
        uint64_t MH=0; std::memcpy(&MH,B.get(),8); MH&=0xfffffffffffffff;
        auto Name=Resolve(MH);
        Report["models"].push_back({{"pointer",Hex(P)},{"hash",Hex(MH)},{"name",Name},
            {"header_offset",Headers.size()},{"header_bytes",M.AssetSize}});
        Headers.insert(Headers.end(),B.get(),B.get()+M.AssetSize);
    }
    Stage="final_readback";
    auto Final=Read(G.PoolPtr+uint64_t(Slot)*G.AssetSize,G.AssetSize);
    auto RR=Read(Refs,uint64_t(Count)*56), TT=Read(Transforms,uint64_t(Count)*64);
    if (!Final || !RR || !TT) return Fail("final source read failed or changed");
    if (std::memcmp(H,Final.get(),G.AssetSize)) {
        nlohmann::json Changes=nlohmann::json::array();
        for (uint32_t I=0;I<G.AssetSize && Changes.size()<32;I+=4)
            if (std::memcmp(H+I,Final.get()+I,4)) {
                uint32_t A=0,B=0; std::memcpy(&A,H+I,4);std::memcpy(&B,Final.get()+I,4);
                Changes.push_back({{"offset",Hex(I)},{"before",Hex(A)},{"after",Hex(B)}});
            }
        Detail["gfx_header_changes"]=Changes;
        return Fail("gfx header changed during capture");
    }
    if (std::memcmp(R.get(),RR.get(),uint64_t(Count)*56)) return Fail("references changed during capture");
    if (std::memcmp(T.get(),TT.get(),uint64_t(Count)*64)) return Fail("transforms changed during capture");
    Stage="save_capture";
    if (!Save(H,G.AssetSize,"gfxworld_header.bin") || !Save(R.get(),uint64_t(Count)*56,"gfx_model_references.bin") ||
        !Save(T.get(),uint64_t(Count)*64,"gfx_model_transforms.bin") || !Save(Headers.data(),Headers.size(),"model_headers.bin")) return Fail("validation rejected");
    Report["readback_unchanged"]=true; Report["unique_models"]=Models.size();
    auto Text=Report.dump(2);
    if (!Save(reinterpret_cast<const int8_t*>(Text.data()),Text.size(),"model_placement_capture.json")) return Fail("validation rejected");
    if (PublishPath.empty()) return true;

    // Measured in BO4: reference+24 selects a PERMUTED transform record;
    // transform+56 contains the reverse reference index (high bit is a flag).
    // 21,016 shared clipmap placements independently confirm position and
    // quaternion direction. Render scale is preserved even where clips differ.
    using json=nlohmann::json;
    std::map<uint64_t,json> Names;
    uint32_t UnknownModels=0, UnknownInstances=0;
    for (const auto& Row:Report["models"]) {
        Names[std::stoull(Row["pointer"].template get<std::string>(),nullptr,16)]=Row;
        if (Row["name"].template get<std::string>().empty()) ++UnknownModels;
    }
    Stage="decode_transforms";
    json Placements=json::array(); std::set<uint32_t> Used;
    const auto Vec=[](double X,double Y,double Z) { return json{{"X",X},{"Y",Y},{"Z",Z}}; };
    for (uint32_t I=0; I<Count; ++I) {
        uint64_t P=0,Q=0; std::memcpy(&P,R.get()+uint64_t(I)*56,8);
        std::memcpy(&Q,R.get()+uint64_t(I)*56+24,8);
        const auto Index=uint32_t((Q-Transforms)/64);
        Detail["record"]=I; Detail["transform"]=Index;
        if (!Used.insert(Index).second) return Fail("validation rejected");
        float F[16]; std::memcpy(F,T.get()+uint64_t(Index)*64,64);
        uint32_t Back=0; std::memcpy(&Back,T.get()+uint64_t(Index)*64+56,4);
        if ((Back&0x7fffffff)!=I) return Fail("validation rejected");
        for (int J=0;J<14;++J) if (!std::isfinite(F[J])) return Fail("validation rejected");
        double Norm=0; for (int J=0;J<4;++J) Norm+=double(F[J])*F[J];
        if (std::abs(Norm-1)>0.001 || F[7]<=0 || F[7]>1000) return Fail("validation rejected");
        for (int J=0;J<3;++J) if (F[8+J]>F[11+J] || std::abs(F[4+J])>1e7) return Fail("validation rejected");
        // CW-compatible XYZ Euler components of the ZYX rotation. Preserve the
        // original quaternion too; use its normalized value for Euler math.
        Norm=std::sqrt(Norm);
        const double X=F[0]/Norm,Y=F[1]/Norm,Z=F[2]/Norm,W=F[3]/Norm;
        constexpr double Deg=57.2957795130823208768;
        const double Pitch=std::max(-1.0,std::min(1.0,2*(W*Y-Z*X)));
        double EX=std::atan2(2*(W*X+Y*Z),1-2*(X*X+Y*Y))*Deg;
        double EY=std::asin(Pitch)*Deg;
        double EZ=std::atan2(2*(W*Z+X*Y),1-2*(Y*Y+Z*Z))*Deg;
        if (std::abs(Pitch)>1.0-1e-14) {
            // At +/-90 degrees the ordinary two atan2 calls both approach
            // atan2(0,0). Choose roll=0 and recover the combined heading from
            // matrix entries -R01,R11; the resulting rotation remains exact.
            EX=0; EY=Pitch>0 ? 90 : -90;
            EZ=std::atan2(2*(W*Z-X*Y),1-2*(X*X+Z*Z))*Deg;
        }
        auto Name=Names.at(P)["name"].template get<std::string>();
        const bool Resolved=!Name.empty();
        if (!Resolved) {
            ++UnknownInstances;
            Name=Strings::Format("xmodel_%llx",std::stoull(Names.at(P)["hash"].template get<std::string>(),nullptr,16));
        }
        json Row={{"Name",Name},{"NameResolved",Resolved},{"ModelHash",Names.at(P)["hash"]},
            {"Position",Vec(F[4],F[5],F[6])},
            {"RotationDegrees",Vec(EX,EY,EZ)},
            {"RotationQuaternion",{{"X",F[0]},{"Y",F[1]},{"Z",F[2]},{"W",F[3]}}},
            {"ModelScale",Vec(F[7],F[7],F[7])},{"BoundsMin",Vec(F[8],F[9],F[10])},
            {"BoundsMax",Vec(F[11],F[12],F[13])},{"RecordSlot",I},{"TransformSlot",Index},
            {"PlacementSource","live"},{"ReferenceFlagsRaw",Back&0x80000000u}};
        ModelExportNaming::PublishPlacementName(Row); Placements.push_back(std::move(Row));
    }
    json Summary={{"schema","greyhound-bo4-model-placements-v1"},{"game","BlackOps4"},{"name_database",NameDatabase},
        {"map_hash",Hex(Hash)},{"complete",true},{"placement_source_unchanged",true},
        {"instances",Count},{"unique_models",Models.size()},{"unresolved_model_names",UnknownModels},
        {"instances_with_unresolved_names",UnknownInstances},{"transform_references_bijective",Used.size()==Count},
        {"reverse_reference_indices_match",true},{"coordinate_system","BO4 world coordinates, unmodified"},
        {"rotation_convention","quaternion XYZW; RotationDegrees XYZ components of ZYX rotation"},
        {"limitations",{"Static gfxworld instances only; dynamic/script-spawned models are not included.",
            "Unresolved model names retain exact hash identifiers; no substitute models are assigned.",
            "Runtime visibility/proxy replacement and deformation are not decoded."}}};
    Stage="save_json";
    std::ofstream Out(FileSystems::CombinePath(PublishPath,"static_models.json"),std::ios::binary);
    Out<<Placements.dump(2); Out.close(); if (!Out) return Fail("validation rejected");
    std::ofstream Stats(FileSystems::CombinePath(PublishPath,"placement_report.json"),std::ios::binary);
    Stats<<Summary.dump(2); Stats.close(); return bool(Stats);
}
