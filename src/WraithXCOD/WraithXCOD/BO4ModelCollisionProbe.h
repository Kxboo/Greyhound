#pragma once

// Focused read-only follow-up: preserve the clipmap's model references and
// transforms, then inspect their actual BO4 model headers. No CW layouts.
template <typename PoolList, typename ResolveName>
bool CaptureBO4ModelCollisionReferences(const PoolList& Pools, const std::string& Path,
    ResolveName Resolve, bool PhysicsOnly = false)
{
    const auto Hex = [](uint64_t V) { return Strings::Format("0x%llX", V); };
    const auto Save = [&](const int8_t* Data, uint64_t Size, const std::string& Name) {
        BinaryWriter W;
        if (!W.Create(FileSystems::CombinePath(Path, Name))) return false;
        W.Write(Data, uint32_t(Size)); W.Close(); return true;
    };
    const auto StableRead = [&](uint64_t Pointer, uint64_t Size) -> std::unique_ptr<int8_t[]> {
        if (!Pointer || !Size || Size > (8ull << 20)) return nullptr;
        uintptr_t A = 0, B = 0;
        std::unique_ptr<int8_t[]> First(CoDAssets::GameInstance->Read(Pointer, Size, A));
        std::unique_ptr<int8_t[]> Second(CoDAssets::GameInstance->Read(Pointer, Size, B));
        if (!First || !Second || A != Size || B != Size || std::memcmp(First.get(), Second.get(), size_t(Size))) return nullptr;
        return First;
    };
    const auto& ClipPool = Pools[11];
    const auto& ModelPool = Pools[4];
    if (ClipPool.AssetSize != 728 || ClipPool.AssetsLoaded != 1 || ModelPool.AssetSize != sizeof(BO4XModel)) return false;
    const auto Span = uint64_t(ClipPool.AssetSize) * ClipPool.PoolSize;
    auto PoolData = StableRead(ClipPool.PoolPtr, Span);
    if (!PoolData) return false;
    std::set<uint32_t> Free;
    uint64_t Next = ClipPool.PoolFreeHeadPtr;
    while (Next) {
        if (Next < ClipPool.PoolPtr || Next-ClipPool.PoolPtr >= Span || (Next-ClipPool.PoolPtr)%728) return false;
        const auto Slot = uint32_t((Next-ClipPool.PoolPtr)/728);
        if (!Free.insert(Slot).second) return false;
        std::memcpy(&Next, PoolData.get()+uint64_t(Slot)*728, 8);
    }
    if (Free.size()+1 != ClipPool.PoolSize) return false;
    uint32_t ClipSlot = 0;
    while (Free.count(ClipSlot)) ++ClipSlot;
    const auto Header = PoolData.get()+uint64_t(ClipSlot)*728;
    uint32_t Count = 0; uint64_t Pointer = 0, MapHash = 0;
    std::memcpy(&Count, Header+0x20, 4); std::memcpy(&Pointer, Header+0x28, 8);
    std::memcpy(&MapHash, Header, 8); MapHash &= 0x0fffffffffffffffull;
    auto Instances = StableRead(Pointer, uint64_t(Count)*96);
    if (!Instances || !Save(Header, 728, "clipmap_header.bin") ||
        !Save(Instances.get(), uint64_t(Count)*96, "collision_instances.bin")) return false;
    nlohmann::json Report = {{"schema",PhysicsOnly ? "greyhound-bo4-model-physics-probe-v1" : "greyhound-bo4-model-collision-probe-v2"},
        {"map_hash", Hex(MapHash)}, {"instance_count",Count}, {"instance_stride",96},
        {"instance_pointer",Hex(Pointer)}, {"instance_file","collision_instances.bin"},
        {"model_pool",{{"index",4},{"pointer",Hex(ModelPool.PoolPtr)},
                       {"asset_size",ModelPool.AssetSize},{"capacity",ModelPool.PoolSize}}},
        {"models",nlohmann::json::array()}, {"unresolved_references",nlohmann::json::array()}};
    std::set<uint64_t> Models;
    for (uint32_t I=0; I<Count; ++I) {
        uint64_t P=0; std::memcpy(&P,Instances.get()+uint64_t(I)*96,8); Models.insert(P);
    }
    std::vector<int8_t> Headers;
    std::vector<int8_t> SurfaceHeaders;
    std::vector<int8_t> TriangleData;
    std::vector<int8_t> PhysicsData;
    std::map<std::pair<uint64_t,uint64_t>, uint64_t> PhysicsRanges;
    const auto PhysicsRegion = [&](uint64_t Address, uint64_t Size) {
        nlohmann::json Ref = {{"pointer",Hex(Address)},{"bytes",Size}};
        const auto Key=std::make_pair(Address,Size);
        if (PhysicsRanges.count(Key)) {
            Ref["status"]="captured_stable"; Ref["byte_offset"]=PhysicsRanges[Key];
            Ref["file"]="model_physics.bin"; return Ref;
        }
        if (!Size) { Ref["status"]="empty"; return Ref; }
        if (PhysicsData.size()+Size>(128ull<<20)) { Ref["status"]="outside_total_limit"; return Ref; }
        auto Data=StableRead(Address,Size);
        if (!Data) { Ref["status"]="unstable_or_unreadable"; return Ref; }
        const auto Offset=PhysicsData.size();
        PhysicsData.insert(PhysicsData.end(),Data.get(),Data.get()+Size);
        PhysicsRanges[Key]=Offset;
        Ref["status"]="captured_stable"; Ref["byte_offset"]=Offset; Ref["file"]="model_physics.bin";
        return Ref;
    };
    uint32_t FollowedModels = 0;
    for (auto P : Models) {
        if (P < ModelPool.PoolPtr || P-ModelPool.PoolPtr >= uint64_t(ModelPool.AssetSize)*ModelPool.PoolSize ||
            (P-ModelPool.PoolPtr)%ModelPool.AssetSize) {
            Report["unresolved_references"].push_back({{"pointer",Hex(P)},{"status","outside_model_pool"}}); continue;
        }
        auto Model = StableRead(P,ModelPool.AssetSize);
        if (!Model) { Report["unresolved_references"].push_back({{"pointer",Hex(P)},{"status","unstable_or_unreadable"}}); continue; }
        uint64_t Hash = 0; std::memcpy(&Hash, Model.get(),8); Hash &= 0x0fffffffffffffffull;
        nlohmann::json Row = {{"pointer",Hex(P)},{"slot",(P-ModelPool.PoolPtr)/ModelPool.AssetSize},
            {"hash",Hex(Hash)},{"header_offset",Headers.size()}, {"header_bytes",ModelPool.AssetSize},
            {"targets",nlohmann::json::array()}};
        const auto Name = Resolve(Hash); if (!Name.empty()) Row["name"] = Name;
        Headers.insert(Headers.end(),Model.get(),Model.get()+ModelPool.AssetSize);
        // Measured on 16 BO4 models: 56-byte collision surface records. The
        // first triangle pointer follows count*56 bytes; successive triangle
        // spans agree with the surface's own count*48 bytes. Read each pointer
        // independently rather than assuming the allocations remain adjacent.
        if (PhysicsOnly) {
            uint64_t RootPointer=0; std::memcpy(&RootPointer,Model.get()+0x60,8);
            nlohmann::json Physics={{"pointer",Hex(RootPointer)},{"entries",nlohmann::json::array()}};
            if (!RootPointer) Physics["status"]="not_present";
            else {
                Physics["root"]=PhysicsRegion(RootPointer,32);
                if (Physics["root"]["status"]!="captured_stable") Physics["status"]="root_unreadable";
                else {
                    const auto RootOffset=Physics["root"]["byte_offset"].get<uint64_t>();
                    uint64_t ListPointer=0,OtherPointer=0;
                    std::memcpy(&ListPointer,PhysicsData.data()+RootOffset,8);
                    std::memcpy(&OtherPointer,PhysicsData.data()+RootOffset+24,8);
                    Physics["list"]=PhysicsRegion(ListPointer,24);
                    if (Physics["list"]["status"]!="captured_stable") Physics["status"]="list_unreadable";
                    else {
                        const auto ListOffset=Physics["list"]["byte_offset"].get<uint64_t>();
                        uint32_t GeomCount=0; uint64_t Entries=0;
                        std::memcpy(&GeomCount,PhysicsData.data()+ListOffset,4);
                        std::memcpy(&Entries,PhysicsData.data()+ListOffset+8,8);
                        Physics["entry_count"]=GeomCount;
                        if (GeomCount>4096) Physics["status"]="count_outside_limit";
                        else {
                            Physics["entry_table"]=PhysicsRegion(Entries,uint64_t(GeomCount)*16);
                            if (GeomCount && Physics["entry_table"]["status"]!="captured_stable") Physics["status"]="entries_unreadable";
                            else {
                                Physics["status"]="captured";
                                const auto EntryOffset=GeomCount ? Physics["entry_table"]["byte_offset"].get<uint64_t>() : 0;
                                for (uint32_t G=0;G<GeomCount;++G) {
                                    uint64_t Brush=0,Primitive=0;
                                    std::memcpy(&Brush,PhysicsData.data()+EntryOffset+G*16,8);
                                    std::memcpy(&Primitive,PhysicsData.data()+EntryOffset+G*16+8,8);
                                    nlohmann::json Entry={{"index",G},{"brush_pointer",Hex(Brush)},{"primitive_pointer",Hex(Primitive)}};
                                    if (Brush && !Primitive) {
                                        Entry["kind"]="brush"; Entry["header"]=PhysicsRegion(Brush,64);
                                        if (Entry["header"]["status"]=="captured_stable") {
                                            const auto Off=Entry["header"]["byte_offset"].get<uint64_t>();
                                            uint64_t Vertices=0,Sides=0;uint16_t Nv=0,Ns=0;
                                            std::memcpy(&Sides,PhysicsData.data()+Off,8);
                                            std::memcpy(&Vertices,PhysicsData.data()+Off+8,8);
                                            std::memcpy(&Nv,PhysicsData.data()+Off+56,2);
                                            std::memcpy(&Ns,PhysicsData.data()+Off+58,2);
                                            Entry["vertex_count"]=Nv; Entry["side_count"]=Ns;
                                            Entry["vertices"]=PhysicsRegion(Vertices,uint64_t(Nv)*12);
                                            Entry["sides"]=PhysicsRegion(Sides,uint64_t(Ns)*20);
                                        }
                                    } else if (Primitive && !Brush) {
                                        Entry["kind"]="primitive"; Entry["record"]=PhysicsRegion(Primitive,64);
                                    } else Entry["kind"]="unresolved_pointer_combination";
                                    Physics["entries"].push_back(Entry);
                                }
                            }
                        }
                    }
                    // Preserve the other root pointer as bounded evidence. Its
                    // meaning is not assumed to be a preset, pose or geometry.
                    if (OtherPointer) Physics["other_root_pointer_sample"]=PhysicsRegion(OtherPointer,256);
                }
            }
            Row["physics"]=Physics;
        } else {
        uint64_t SurfacePointer = 0; uint32_t SurfaceCount = 0;
        std::memcpy(&SurfacePointer,Model.get()+0x50,8);
        std::memcpy(&SurfaceCount,Model.get()+0x140,4);
        nlohmann::json Collision = {{"pointer",Hex(SurfacePointer)},{"count",SurfaceCount},
            {"stride",56},{"surfaces",nlohmann::json::array()}};
        if (!SurfaceCount) Collision["status"]="empty";
        else if (SurfaceCount>4096) Collision["status"]="count_outside_limit";
        else {
            auto Surfaces=StableRead(SurfacePointer,uint64_t(SurfaceCount)*56);
            if (!Surfaces) Collision["status"]="unstable_or_unreadable";
            else {
                Collision["file"]="collision_surface_headers.bin";
                Collision["byte_offset"]=SurfaceHeaders.size();
                Collision["bytes"]=uint64_t(SurfaceCount)*56;
                SurfaceHeaders.insert(SurfaceHeaders.end(),Surfaces.get(),Surfaces.get()+uint64_t(SurfaceCount)*56);
                Collision["status"]="captured_stable";
                for (uint32_t S=0;S<SurfaceCount;++S) {
                    const auto Surface=Surfaces.get()+uint64_t(S)*56;
                    uint64_t TriPointer=0; uint32_t TriCount=0;
                    std::memcpy(&TriPointer,Surface,8); std::memcpy(&TriCount,Surface+16,4);
                    const auto Bytes=uint64_t(TriCount)*48;
                    nlohmann::json Tri={{"surface",S},{"pointer",Hex(TriPointer)},{"count",TriCount},{"stride",48}};
                    if (!TriCount) Tri["status"]="empty";
                    else if (TriangleData.size()+Bytes>(256ull<<20)) Tri["status"]="outside_total_limit";
                    else {
                        auto Data=StableRead(TriPointer,Bytes);
                        if (!Data) Tri["status"]="unstable_or_unreadable";
                        else {
                            Tri["file"]="model_collision_triangles.bin";
                            Tri["byte_offset"]=TriangleData.size(); Tri["bytes"]=Bytes;
                            TriangleData.insert(TriangleData.end(),Data.get(),Data.get()+Bytes);
                            Tri["status"]="captured_stable";
                        }
                    }
                    Collision["surfaces"].push_back(Tri);
                }
            }
        }
        Row["collision"]=Collision;
        }
        if (!PhysicsOnly && FollowedModels++ < 16) {
            for (uint32_t Offset=0x48; Offset+8<=ModelPool.AssetSize && Row["targets"].size()<12; Offset+=8) {
                // Already-known rendering LOD and material pointers are not the
                // collision lead; retain their bytes in the complete header.
                if (Offset>=0x78 && Offset<=0xB8) continue;
                uint64_t Target=0; std::memcpy(&Target,Model.get()+Offset,8);
                if (Target<0x10000 || Target>=0x0000800000000000ull) continue;
                auto Data=StableRead(Target,4096); if (!Data) continue;
                const auto File=Strings::Format("model_%llu_at_%X.bin",(P-ModelPool.PoolPtr)/ModelPool.AssetSize,Offset);
                if (!Save(Data.get(),4096,File)) return false;
                nlohmann::json Item={{"field_offset",Hex(Offset)},{"pointer",Hex(Target)},{"file",File},{"bytes",4096}};
                for (uint32_t K=0;K<Pools.size();++K) {
                    const auto& Q=Pools[K];
                    if (Q.AssetSize && Target>=Q.PoolPtr && Target-Q.PoolPtr<uint64_t(Q.AssetSize)*Q.PoolSize &&
                        (Target-Q.PoolPtr)%Q.AssetSize==0) { Item["pool_index"]=K; break; }
                }
                Row["targets"].push_back(Item);
            }
        }
        Report["models"].push_back(Row);
    }
    if (!Save(Headers.data(),Headers.size(),"model_headers.bin")) return false;
    if (PhysicsOnly) {
        if (!Save(PhysicsData.data(),PhysicsData.size(),"model_physics.bin")) return false;
    } else if (!Save(SurfaceHeaders.data(),SurfaceHeaders.size(),"collision_surface_headers.bin") ||
               !Save(TriangleData.data(),TriangleData.size(),"model_collision_triangles.bin")) return false;
    Report["header_file"]="model_headers.bin";
    Report["readback_unchanged"]=true;
    Report["scope"]=PhysicsOnly ? "Self-contained model physics export: references, transforms, brush/primitive lists; no terrain or triangle-surface merge" :
        "Model references, complete counted collision surface/triangle arrays and instance transforms; decode and placement validation are separate";
    std::ofstream Out(FileSystems::CombinePath(Path,PhysicsOnly ? "model_physics_probe.json" : "model_collision_probe.json"),std::ios::binary|std::ios::trunc);
    Out << Report.dump(2); Out.close(); return !Out.fail();
}
