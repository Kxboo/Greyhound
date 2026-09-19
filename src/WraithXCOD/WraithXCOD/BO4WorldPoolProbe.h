#pragma once

// Read-only BO4 producer probe. This captures evidence for Greyhound's existing
// brush pipeline; it does not interpret these headers using CW member offsets.
// Pool names: atian-cod-tools, src/core/shared/games/bo4/pool.hpp.
template <typename PoolList, typename ResolveName>
bool CaptureBO4WorldPools(const PoolList& Pools, const std::string& ExportPath,
    const std::string& TerrainName, ResolveName Resolve, bool FlagsOnly=false)
{
    struct Target { uint32_t Index; const char* Name; };
    const Target Targets[] = {
        {11, "clipmap"}, {12, "comworld"}, {13, "gameworld"},
        {14, "gfxworld"}, {147, "streamerworld"}, {118, "entity_list"}, {107, "trigger_list"}
    };
    constexpr uint64_t PoolByteLimit = 4ull << 20;
    constexpr uint32_t AssetLimit = 32;
    constexpr uint32_t PointerLimit = 24;
    constexpr uint32_t TargetBytes = 4096;
    const auto Hex = [](uint64_t n) { return Strings::Format("0x%llX", n); };
    const auto Save = [&](const void* Data, uint32_t Bytes, const std::string& Name) {
        BinaryWriter Writer;
        if (!Writer.Create(FileSystems::CombinePath(ExportPath, Name))) return false;
        Writer.Write(reinterpret_cast<const int8_t*>(Data), Bytes);
        Writer.Close();
        return true;
    };
    nlohmann::json Report = {
        {"schema", "greyhound-bo4-world-pool-probe-v8"},
        {"terrain_asset", TerrainName},
        {"enum_reference", "https://github.com/ate47/atian-cod-tools/blob/main/src/core/shared/games/bo4/pool.hpp"},
        {"scope", "Pool headers, selected stable arrays and bounded one-hop samples; decoded separately"},
        {"limits", {{"pool_bytes", PoolByteLimit}, {"assets_per_pool", AssetLimit},
                    {"targets_per_asset", PointerLimit}, {"bytes_per_target", TargetBytes}}},
        {"pools", nlohmann::json::array()}
    };
    bool IOOkay = true;
    for (const auto& Target : Targets)
    {
        if(FlagsOnly)break;
        const auto& Pool = Pools[Target.Index];
        nlohmann::json Row = {{"pool_index", Target.Index}, {"enum_name", Target.Name},
            {"pool_pointer", Hex(Pool.PoolPtr)}, {"asset_size", Pool.AssetSize},
            {"capacity", Pool.PoolSize}, {"loaded", Pool.AssetsLoaded},
            {"free_head", Hex(Pool.PoolFreeHeadPtr)}, {"assets", nlohmann::json::array()}};
        const uint64_t Span = uint64_t(Pool.AssetSize) * Pool.PoolSize;
        if (!Pool.PoolPtr || Pool.AssetSize < 8 || !Span || Span > PoolByteLimit)
        {
            Row["status"] = "empty_or_outside_probe_limit";
            Report["pools"].push_back(Row);
            continue;
        }
        uintptr_t Got = 0;
        std::unique_ptr<int8_t[]> Data(CoDAssets::GameInstance->Read(Pool.PoolPtr, Span, Got));
        if (!Data || Got != Span)
        {
            Row["status"] = "pool_read_incomplete";
            Row["bytes_read"] = Got;
            Report["pools"].push_back(Row);
            continue;
        }
        const auto PoolFile = Strings::Format("world_pool_%u.bin", Target.Index);
        IOOkay = Save(Data.get(), uint32_t(Span), PoolFile) && IOOkay;
        Row["file"] = PoolFile;
        Row["bytes"] = Span;
        std::set<uint32_t> Free;
        uint64_t Next = Pool.PoolFreeHeadPtr;
        bool FreeValid = true;
        while (Next)
        {
            if (Next < Pool.PoolPtr || Next - Pool.PoolPtr >= Span ||
                (Next - Pool.PoolPtr) % Pool.AssetSize)
            { FreeValid = false; break; }
            const auto Index = uint32_t((Next - Pool.PoolPtr) / Pool.AssetSize);
            if (!Free.insert(Index).second) { FreeValid = false; break; }
            std::memcpy(&Next, Data.get() + size_t(Index) * Pool.AssetSize, 8);
        }
        Row["free_chain_valid"] = FreeValid;
        Row["free_slots"] = Free.size();
        Row["active_count_matches_directory"] = FreeValid && Pool.PoolSize - Free.size() == Pool.AssetsLoaded;
        // If allocation cannot be established, retain the full pool for offline
        // inspection but do not label arbitrary slots as loaded map assets.
        if (!Row["active_count_matches_directory"].get<bool>())
        {
            Row["status"] = "allocation_unresolved";
            Report["pools"].push_back(Row);
            continue;
        }
        uint32_t Captured = 0;
        for (uint32_t i = 0; i < Pool.PoolSize && Captured < AssetLimit; ++i)
        {
            if (Free.count(i)) continue;
            ++Captured;
            const int8_t* Header = Data.get() + size_t(i) * Pool.AssetSize;
            uint64_t Hash = 0;
            std::memcpy(&Hash, Header, 8);
            Hash &= 0x0fffffffffffffffull;
            nlohmann::json Asset = {{"slot", i}, {"header_offset", uint64_t(i) * Pool.AssetSize},
                {"pointer", Hex(Pool.PoolPtr + uint64_t(i) * Pool.AssetSize)},
                {"name_hash_candidate", Hex(Hash)}, {"targets", nlohmann::json::array()}};
            const auto Name = Resolve(Hash);
            if (!Name.empty()) Asset["hash_resolved_name"] = Name;
            // Explicit BO4 reference tables and measured clipmap candidates.
            // Candidate strides come from adjacent pointer distances divided by
            // the header's own counts. They are not borrowed CW member layouts.
            struct Table {
                uint32_t Pool, CountOffset, PointerOffset, Stride, HeaderBytes;
                const char* Label;
                const char* Basis;
            };
            const Table Tables[] = {
                {107, 0x10, 0x18, 8, 80, "trigger_models", "BO4 trigger reference; validate hull ranges"},
                {107, 0x20, 0x28, 32, 80, "trigger_hulls", "BO4 trigger reference; validate bounds and slab ranges"},
                {107, 0x30, 0x38, 20, 80, "trigger_slabs", "BO4 trigger reference; validate direction and intervals"},
                {107, 0x40, 0x48, 48, 80, "trigger_entities", "BO4 spawnvar records; preserve runtime offsets"},
                {11, 0x2C0, 0x2C8, 64, 728, "material_table_candidate", "bounded candidate sample; stride not yet decoded"},
                {118, 0x10, 0x18, 48, 32, "entities", "atian BO4 LinkerSpawnVar; sample transforms checked"},
                {14, 0x590, 0x598, 216, 6832, "volume_decals", "atian BO4 GfxVolumeDecal reference"},
                {14, 0x1BC, 0x400, 56, 6832, "static_models", "atian BO4 GfxStaticModelDrawInst reference"},
                {14, 0x180, 0x188, 80, 6832, "brush_models_candidate", "candidate stride; validate against clipmodel bounds"},
                {11, 0x20, 0x28, 96, 728, "instances_candidate", "adjacent span divided by 22594 entries equals 96"},
                {11, 0x30, 0x38, 8, 728, "pointer_table_30", "8-byte pointer entries in sample"},
                {11, 0x40, 0x48, 8, 728, "pointer_table_40", "8-byte pointer entries in sample"},
                {11, 0x50, 0x58, 24, 728, "planes_candidate_50", "adjacent span divided by 19 entries equals 24"},
                {11, 0x60, 0x68, 56, 728, "records_candidate_60", "adjacent span divided by 233 entries equals 56"},
                {11, 0x70, 0x78, 12, 728, "vertices_candidate", "float3 sample and exact next-pointer span"},
                {11, 0x80, 0x88, 12, 728, "triangles_candidate", "uint32 triples sample and exact next-pointer span"},
                {11, 0x90, 0x98, 36, 728, "bounds_candidate", "adjacent span divided by 9869 entries equals 36"},
                {11, 0xB0, 0xB8, 88, 728, "clip_models_candidate", "214 entries; next-pointer span fits 88 plus 8 padding"},
                {11, 0x260, 0x268, 20, 728, "planes_candidate_260", "unit-normal float4 plus u32; exact adjacent span"},
                {11, 0x270, 0x278, 32, 728, "brushes_candidate", "exact adjacent span divided by 11715 equals 32"},
                {11, 0x280, 0x288, 4, 728, "leaf_brush_indices_candidate", "u32 leaf-list candidate; validate each referenced range independently"},
                {11, 0x290, 0x298, 12, 728, "triples_candidate_290", "exact adjacent span divided by count equals 12"},
                {11, 0x2A0, 0x2A8, 4, 728, "indices_candidate_2A0", "exact adjacent span divided by count equals 4"},
                {11, 0x2B0, 0x2B8, 64, 728, "records_candidate_2B0", "adjacent span fits count times 64 plus 64 padding"}
            };
            Asset["tables"] = nlohmann::json::array();
            for (const auto& Table : Tables)
            {
                if (Table.Pool != Target.Index || Table.HeaderBytes != Pool.AssetSize) continue;
                uint32_t Count = 0;
                uint64_t Pointer = 0;
                std::memcpy(&Count, Header + Table.CountOffset, 4);
                std::memcpy(&Pointer, Header + Table.PointerOffset, 8);
                const uint64_t Wanted = uint64_t(Count) * Table.Stride;
                nlohmann::json T = {{"label", Table.Label}, {"basis", Table.Basis},
                    {"count", Count}, {"stride", Table.Stride}, {"pointer", Hex(Pointer)},
                    {"count_offset", Hex(Table.CountOffset)}, {"pointer_offset", Hex(Table.PointerOffset)}};
                if (!Count) T["status"] = "empty";
                else if (!Pointer || Wanted > (16ull << 20)) T["status"] = "outside_probe_limit";
                else
                {
                    uintptr_t FirstRead = 0, SecondRead = 0;
                    std::unique_ptr<int8_t[]> First(CoDAssets::GameInstance->Read(Pointer, Wanted, FirstRead));
                    std::unique_ptr<int8_t[]> Second(CoDAssets::GameInstance->Read(Pointer, Wanted, SecondRead));
                    T["bytes_read"] = FirstRead;
                    if (!First || FirstRead != Wanted || !Second || SecondRead != Wanted)
                        T["status"] = "read_incomplete";
                    else if (std::memcmp(First.get(), Second.get(), size_t(Wanted)))
                        T["status"] = "changed_during_capture";
                    else
                    {
                        const auto File = Strings::Format("world_pool_%u_slot_%u_%s.bin", Target.Index, i, Table.Label);
                        const bool Saved = Save(First.get(), uint32_t(Wanted), File);
                        IOOkay = Saved && IOOkay;
                        T["status"] = Saved ? "captured_stable" : "write_failed";
                        T["file"] = File;
                        T["bytes"] = Wanted;
                        T["readback_unchanged"] = true;
                        if ((Target.Index==118 || Target.Index==107) && Table.Stride==48) {
                            nlohmann::json Entities=nlohmann::json::array(), Texts=nlohmann::json::object();
                            std::vector<int8_t> Properties;
                            const auto TextAt=[&](uint64_t P) {
                                const auto Key=Hex(P);
                                if (Texts.contains(Key) || P<0x10000 || P>=0x0000800000000000ull) return;
                                uintptr_t A=0,B=0;
                                std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(P,512,A));
                                std::unique_ptr<int8_t[]> Y(CoDAssets::GameInstance->Read(P,512,B));
                                if(!X || !Y || !A || A!=B || std::memcmp(X.get(),Y.get(),A)) return;
                                size_t N=0; while(N<A && X[N]) ++N;
                                bool Plain=N<A;
                                for(size_t K=0;K<N;++K) if(uint8_t(X[K])<32 || uint8_t(X[K])>126) Plain=false;
                                nlohmann::json V={{"read_bytes",A},{"terminated",N<A}};
                                if(Plain) V["text"]=std::string(reinterpret_cast<char*>(X.get()),N);
                                else { std::string Raw; for(size_t K=0;K<(std::min)(size_t(A),size_t(128));++K) Raw+=Strings::Format("%02X",uint8_t(X[K])); V["raw_prefix"]=Raw; }
                                Texts[Key]=V;
                            };
                            for(uint32_t E=0;E<Count;++E) {
                                uint32_t N=0;uint64_t P=0;
                                std::memcpy(&N,First.get()+uint64_t(E)*48,4);
                                std::memcpy(&P,First.get()+uint64_t(E)*48+8,8);
                                nlohmann::json V={{"entity",E},{"count",N},{"pointer",Hex(P)},{"candidate_stride",32}};
                                if(!N) V["status"]="empty";
                                else if(N>512 || Properties.size()+uint64_t(N)*32>(16ull<<20)) V["status"]="outside_capture_limit";
                                else {
                                    uintptr_t A=0,B=0;
                                    std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(P,uint64_t(N)*32,A));
                                    std::unique_ptr<int8_t[]> Y(CoDAssets::GameInstance->Read(P,uint64_t(N)*32,B));
                                    if(!X || !Y || A!=uint64_t(N)*32 || B!=A || std::memcmp(X.get(),Y.get(),A)) V["status"]="read_failed_or_changed";
                                    else {
                                        V["status"]="captured_stable";V["offset"]=Properties.size();
                                        Properties.insert(Properties.end(),X.get(),X.get()+A);
                                        for(uint32_t J=0;J<N;++J) {
                                            uint64_t Key=0,Value=0;std::memcpy(&Key,X.get()+J*32,8);std::memcpy(&Value,X.get()+J*32+8,8);
                                            TextAt(Key);TextAt(Value);
                                        }
                                    }
                                }
                                Entities.push_back(V);
                            }
                            const auto PropertyFile=Strings::Format("world_pool_%u_slot_%u_properties.bin",Target.Index,i);
                            IOOkay=Save(Properties.data(),uint32_t(Properties.size()),PropertyFile)&&IOOkay;
                            Asset["properties"]={{"file",PropertyFile},{"entities",Entities},{"strings",Texts}};
                        }
                    }
                }
                Asset["tables"].push_back(T);
            }
            if(Target.Index==11 && Pool.AssetSize==728) {
                uint64_t Pointer=0;std::memcpy(&Pointer,Header+0x2C8,8);
                if(Pointer>=0x11000) {
                    uintptr_t A=0,B=0;
                    std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(Pointer-4096,4096,A));
                    std::unique_ptr<int8_t[]> Y(CoDAssets::GameInstance->Read(Pointer-4096,4096,B));
                    if(X && Y && A==4096 && B==A && !std::memcmp(X.get(),Y.get(),A)) {
                        const auto File=Strings::Format("world_pool_%u_slot_%u_filter_prefix.bin",Target.Index,i);
                        IOOkay=Save(X.get(),uint32_t(A),File)&&IOOkay;
                        Asset["filter_prefix"]={{"file",File},{"pointer",Hex(Pointer-4096)},{"bytes",A},{"readback_unchanged",true}};
                    }
                }
            }
            uint32_t Followed = 0;
            for (uint32_t Offset = 8; Offset + 8 <= Pool.AssetSize; Offset += 8)
            {
                uint64_t Pointer = 0;
                std::memcpy(&Pointer, Header + Offset, 8);
                if (Pointer < 0x10000 || Pointer >= 0x0000800000000000ull) continue;
                if (Followed >= PointerLimit) { Asset["pointer_limit_reached"] = true; break; }
                uintptr_t Read = 0;
                std::unique_ptr<int8_t[]> Bytes(CoDAssets::GameInstance->Read(Pointer, TargetBytes, Read));
                if (!Bytes || !Read) continue;
                ++Followed;
                const auto File = Strings::Format("world_pool_%u_slot_%u_at_%X.bin", Target.Index, i, Offset);
                IOOkay = Save(Bytes.get(), uint32_t(Read), File) && IOOkay;
                uint32_t Previous = 0;
                std::memcpy(&Previous, Header + Offset - 4, 4);
                nlohmann::json Hit = {{"field_offset", Hex(Offset)}, {"pointer", Hex(Pointer)},
                    {"file", File}, {"bytes", Read}, {"requested_bytes", TargetBytes},
                    {"preceding_u32_uninterpreted", Previous},
                    {"status", Read == TargetBytes ? "sampled" : "partial_sample"}};
                for (uint32_t pi = 0; pi < Pools.size(); ++pi)
                {
                    const auto& Other = Pools[pi];
                    const auto OtherSpan = uint64_t(Other.AssetSize) * Other.PoolSize;
                    if (Other.AssetSize && Pointer >= Other.PoolPtr && Pointer - Other.PoolPtr < OtherSpan &&
                        (Pointer - Other.PoolPtr) % Other.AssetSize == 0)
                    {
                        Hit["target_pool"] = pi;
                        Hit["target_asset_index"] = (Pointer - Other.PoolPtr) / Other.AssetSize;
                        break;
                    }
                }
                Asset["targets"].push_back(Hit);
            }
            Row["assets"].push_back(Asset);
        }
        Row["status"] = "captured";
        Row["asset_limit_reached"] = Captured < Pool.AssetsLoaded;
        Report["pools"].push_back(Row);
    }
    // Find BO4's own named surface/contents declarations. No CW RVAs or
    // bit meanings are used: save the raw neighbouring records for validation.
    nlohmann::json Named=nlohmann::json::array();
    const auto Module=CoDAssets::GameInstance->GetMainModuleAddress();
    const auto ModuleBytes=CoDAssets::GameInstance->GetMainModuleMemorySize();
    for(const auto* Label:{"playerClip","slick","nonColliding","mantleOn"}) {
        std::string Pattern;
        for(const auto* P=Label;;++P) { Pattern+=Strings::Format("%02X ",uint8_t(*P)); if(!*P) break; }
        const auto NameAddress=CoDAssets::GameInstance->Scan(Pattern,true);
        if(NameAddress<0) continue;
        std::string PointerPattern;
        const uint64_t NamePointer=uint64_t(NameAddress);
        for(unsigned J=0;J<8;++J) PointerPattern+=Strings::Format("%02X ",uint8_t(NamePointer>>(8*J)));
        auto Start=Module;
        for(unsigned Hit=0;Hit<8 && Start<Module+ModuleBytes;++Hit) {
            const auto At=CoDAssets::GameInstance->Scan(PointerPattern,Start,Module+ModuleBytes-Start);
            if(At<0) break;Start=uint64_t(At)+8;
            if(uint64_t(At)<Module+24*64)continue;
            const uint64_t Begin=uint64_t(At)-24*64, Size=24*128;
            uintptr_t A=0,B=0;
            std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(Begin,Size,A));
            std::unique_ptr<int8_t[]> Y(CoDAssets::GameInstance->Read(Begin,Size,B));
            if(!X || !Y || A!=Size || B!=Size || std::memcmp(X.get(),Y.get(),Size)) continue;
            nlohmann::json Rows=nlohmann::json::array();
            // Adjacent declaration tables have padding between them; retain
            // pointer alignment rather than assuming one shared 24-byte phase.
            for(uint32_t J=0;J+24<=Size;J+=8) {
                uint64_t P=0; std::memcpy(&P,X.get()+J,8);
                if(P<Module || P>=Module+ModuleBytes) continue;
                uintptr_t N=0;std::unique_ptr<int8_t[]> S(CoDAssets::GameInstance->Read(P,96,N));
                if(!S || N!=96) continue;size_t L=0;while(L<N && S[L]) ++L;
                if(!L || L==N)continue;
                bool Plain=true;for(size_t K=0;K<L;++K)if(uint8_t(S[K])<32 || uint8_t(S[K])>126)Plain=false;
                if(!Plain)continue;
                uint32_t F[4];std::memcpy(F,X.get()+J+8,16);
                if(F[0]>1)continue;
                Rows.push_back({{"offset",J},{"record_module_rva",Hex(Begin+J-Module)},{"name",std::string(reinterpret_cast<char*>(S.get()),L)},
                    {"field_8",Hex(F[0])},{"field_12",Hex(F[1])},{"field_16",Hex(F[2])},{"field_20",Hex(F[3])}});
            }
            const auto File=Strings::Format("named_flags_%s_%u.bin",Label,Hit);
            IOOkay=Save(X.get(),uint32_t(Size),File)&&IOOkay;
            Named.push_back({{"label",Label},{"module_rva",Hex(Begin-Module)},{"file",File},{"rows",Rows}});
        }
    }
    // Brush-side indices may address the renderer/physics global filter array,
    // not the clipmap's tail pointer. Locate a run of four unambiguous observed
    // contents values and preserve the candidate for an ALL-brush union check.
    for(const auto& PoolRow:Report["pools"]) if(PoolRow["pool_index"]==11)
        for(const auto& Asset:PoolRow["assets"]) for(const auto& Table:Asset["tables"])
            if(Table["label"]=="records_candidate_2B0" && Table["status"]=="captured_stable") {
                const auto Count=Table["count"].template get<uint32_t>();
                const auto Pointer=std::stoull(Table["pointer"].template get<std::string>(),nullptr,16);
                uintptr_t Got=0;std::unique_ptr<int8_t[]> B(CoDAssets::GameInstance->Read(Pointer,uint64_t(Count)*64,Got));
                if(!B || Got!=uint64_t(Count)*64)continue;
                std::map<uint16_t,std::set<uint32_t>> Contents;
                for(uint32_t I=0;I<Count;++I) {
                    uint32_t C=0;uint16_t Ids[6];std::memcpy(&C,B.get()+I*64+28,4);std::memcpy(Ids,B.get()+I*64+44,12);
                    for(const auto Id:Ids)Contents[Id].insert(C);
                }
                unsigned Tried=0;
                for(const auto& Entry:Contents) {
                    bool Okay=true;std::string Pattern;
                    for(unsigned J=0;J<4;++J) {
                        const auto It=Contents.find(uint16_t(Entry.first+J));
                        if(It==Contents.end() || It->second.size()!=1){Okay=false;break;}
                        Pattern+="?? ?? ?? ?? ";const auto C=*It->second.begin();
                        for(unsigned K=0;K<4;++K)Pattern+=Strings::Format("%02X ",uint8_t(C>>(K*8)));
                    }
                    if(!Okay)continue;
                    const auto Found=CoDAssets::GameInstance->Scan(Pattern,true);++Tried;
                    if(Found>=0) {
                        const uint64_t Base=uint64_t(Found)-uint64_t(Entry.first)*8;
                        // Include non-axial filters beyond the largest axial index.
                        const uint64_t Size=uint64_t(Contents.rbegin()->first+65)*8;
                        uintptr_t A=0,Z=0;std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(Base,Size,A));
                        std::unique_ptr<int8_t[]> Y(CoDAssets::GameInstance->Read(Base,Size,Z));
                        if(X && Y && A==Size && Z==Size && !std::memcmp(X.get(),Y.get(),Size)) {
                            const std::string File="global_filter_candidate.bin";
                            IOOkay=Save(X.get(),uint32_t(Size),File)&&IOOkay;
                            Report["global_filter_candidate"]={{"pointer",Hex(Base)},{"file",File},{"bytes",Size},
                                {"anchor_index",Entry.first},{"pattern",Pattern},{"readback_unchanged",true}};
                        }
                        break;
                    }
                    if(Tried==3)break;
                }
            }
    Report["named_flag_candidates"]=Named;
    Report["named_flags_version"]=3;
    Report["module_base"]=Hex(Module);
    if(FlagsOnly)Report["scope"]="Stable BO4 named declarations only; no map-pool capture";
    Report["write_success"] = IOOkay;
    std::ofstream Stream(FileSystems::CombinePath(ExportPath, FlagsOnly ? "surface_flags_probe.json" : "world_pools_probe.json"),
                         std::ios::binary | std::ios::trunc);
    if (!Stream) return false;
    Stream << Report.dump(2);
    Stream.close();
    return IOOkay && !Stream.fail();
}
