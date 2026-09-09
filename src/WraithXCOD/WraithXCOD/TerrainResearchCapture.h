#pragma once

// Read-only evidence collection. Bounds on unknown objects are not their layouts.
#include "json.hpp"
#include "ProcessReader.h"
#include "TerrainResearchPolicy.h"
#include "Compression.h"
#include "Siren.h"
#include <map>
#include <set>
#include <fstream>
#include <functional>

namespace TerrainResearch
{
    using json = nlohmann::json;
    inline std::string Hex(uint64_t V) { return Strings::Format("0x%llX", V); }
    inline std::string Utc()
    {
        SYSTEMTIME T{}; GetSystemTime(&T);
        return Strings::Format("%04u-%02u-%02uT%02u:%02u:%02u.%03uZ",
            T.wYear, T.wMonth, T.wDay, T.wHour, T.wMinute, T.wSecond, T.wMilliseconds);
    }
    inline uint64_t U64(const std::vector<uint8_t>& B, size_t O)
    {
        uint64_t V = 0;
        if (O <= B.size() && 8 <= B.size() - O) memcpy(&V, B.data() + O, 8);
        return V;
    }
    inline uint32_t U32(const std::vector<uint8_t>& B, size_t O)
    {
        uint32_t V = 0;
        if (O <= B.size() && 4 <= B.size() - O) memcpy(&V, B.data() + O, 4);
        return V;
    }
    inline bool Pointer(uint64_t P) { return P >= 0x10000 && P < 0x0000800000000000ull; }

    class Capture
    {
        std::string Root;
        Budgets Budget;
        uint64_t Queries = 0;
        HANDLE Pack = INVALID_HANDLE_VALUE;
        uint64_t PackOffset = 0;
        std::function<void(uint32_t)> ProgressCallback;
        uint64_t LastProgress = 0;
        std::string ProgressStage;
        std::map<uint64_t, int> ImagePriority;
        std::map<uint64_t, std::vector<uint64_t>> MaterialImages, PackageOwners;
        std::map<std::pair<uint64_t, uint64_t>, std::string> Saved;
        std::set<uint64_t> Images, Materials, Techsets, Shaders, Packages;
    public:
        static constexpr uint64_t SpanLimit = 256ull * 1024 * 1024;
        static constexpr uint64_t TotalLimit = 7297ull * 1024 * 1024;
        json Report;
        json PendingPayloads = json::array();
        json PendingPackages = json::array();
        // Typed local-package readers share the existing bounded scene lane.
        bool ReserveScenePackageBytes(uint64_t Bytes)
        { return Bytes <= SpanLimit && Budget.Charge("packages_scene", Bytes); }
        explicit Capture(const std::string& Directory,
            const std::function<void(uint32_t)>& Callback) : Root(Directory), ProgressCallback(Callback)
        {
            FileSystems::CreateDirectory(Root);
            Report = {{"schema", "superterrain-source-evidence-v2"},
                {"started_utc", Utc()}, {"read_only", true}, {"atomic_snapshot", false},
                {"limits", {{"span_bytes", SpanLimit}, {"raw_evidence_bytes", TotalLimit},
                    {"unknown_array_prefix_bytes", 65536}, {"unknown_array_total_bytes", 512ull * 1024 * 1024},
                    {"pool_max_index", 0xDC}, {"scope", "additional research evidence; legacy terrain capture has separate limits"}}},
                {"reads", json::array()}, {"images", json::array()}, {"materials", json::array()},
                {"storage", json::object()},
                {"packages", json::array()}, {"pools", json::array()}, {"array_candidates", json::array()},
                {"unresolved", {"authored spline control-point layout", "renderer-owned VT composition pass",
                    "exact packed control-map semantics", "nonresident stream payloads absent from local cache",
                    "unknown pointer graphs beyond explicitly recorded prefixes"}}};
            Report["limits"]["budget_lanes_bytes"] = Budget.Limits;
            Report["limits"]["memory_query_limit"] = 250000;
            Report["limits"]["charging"] = "preflight rejects cost zero bytes; attempted reads charged only to their lane; raw/decoded packages have independent reserved lanes";
            if (CoDAssets::GameInstance)
                Report["process"] = {{"pid", GetProcessId(CoDAssets::GameInstance->GetCurrentProcess())},
                    {"path", CoDAssets::GameInstance->GetProcessPath()},
                    {"module_base", Hex(CoDAssets::GameInstance->GetMainModuleAddress())},
                    {"module_size", CoDAssets::GameInstance->GetMainModuleMemorySize()}};
        }
        ~Capture() { if (Pack != INVALID_HANDLE_VALUE) CloseHandle(Pack); }
        void Progress(const std::string& Stage, uint32_t Percent, size_t Done, size_t Total)
        {
            const auto Now = GetTickCount64();
            if (Stage == ProgressStage && Now - LastProgress < 1000 && Done != Total) return;
            ProgressStage = Stage; LastProgress = Now;
            if (ProgressCallback) ProgressCallback(Percent);
            const auto Logs = FileSystems::CombinePath(
                FileSystems::GetDirectoryName(FileSystems::GetDirectoryName(Root)), "logs");
            FileSystems::CreateDirectory(Logs);
            // Session-local progress is outside immutable captured evidence.
            std::ofstream F(FileSystems::CombinePath(Logs, "source_capture_native.json"), std::ios::binary);
            F << json({{"stage", Stage}, {"done", Done}, {"total", Total},
                {"percent", Percent}, {"utc", Utc()}}).dump();
        }
        // Accidental reuse must fail, never truncate.
        bool Write(const std::string& Name, const uint8_t* Data, size_t Size)
        {
            // Small records dominate file count, not data volume. Keep their
            // logical filenames and exact byte ranges in the evidence index.
            if (Size <= 4096 && Name.find('/') != std::string::npos)
            {
                if (Pack == INVALID_HANDLE_VALUE)
                    Pack = CreateFileA(FileSystems::CombinePath(Root, "small_records.bin").c_str(),
                        GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
                if (Pack == INVALID_HANDLE_VALUE) return false;
                DWORD Written = 0;
                const auto Offset = PackOffset;
                const bool Ok = WriteFile(Pack, Data, static_cast<DWORD>(Size), &Written, nullptr) && Written == Size;
                PackOffset += Written;
                if (Ok) Report["storage"][Name] = {{"file", "small_records.bin"}, {"offset", Offset}, {"bytes", Size}};
                return Ok;
            }
            auto Path = FileSystems::CombinePath(Root, Name);
            FileSystems::CreateDirectory(FileSystems::GetDirectoryName(Path));
            HANDLE F = CreateFileA(Path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (F == INVALID_HANDLE_VALUE) return false;
            DWORD Written = 0;
            const bool Ok = Size <= MAXDWORD && WriteFile(F, Data, static_cast<DWORD>(Size), &Written, nullptr)
                && Written == Size;
            CloseHandle(F);
            return Ok;
        }
        // Bounded live read for a short consistency window. The caller saves the
        // returned bytes and read record after completing all dependent reads.
        std::vector<uint8_t> DeferredSmallRead(uint64_t Address, uint64_t Size, const std::string& Name, json& R)
        {
            R={{"address",Hex(Address)},{"requested_bytes",Size},{"read_bytes",0},{"file",Name},
                {"budget_lane","structure"},{"started_utc",Utc()},
                {"interpretation","live consistency read; evidence persistence deferred"}};
            std::vector<uint8_t> Bytes;std::string Reason;
            if(!Pointer(Address) || !Size || Size>4096 || Size>0x0000800000000000ull-Address)
                R["status"]="invalid_address_or_size";
            else if(!Budget.Fits("structure",Size) || ++Queries>250000) R["status"]="budget_rejected";
            else if(!ReadableRange(CoDAssets::GameInstance->GetCurrentProcess(),Address,Size,Reason))
                R["status"]="unreadable_range";
            else
            {
                uintptr_t Got=0;auto Data=CoDAssets::GameInstance->Read(Address,static_cast<uintptr_t>(Size),Got);
                Budget.Charge("structure",Size);R["read_bytes"]=Got;
                if(Data && Got==Size) Bytes.assign(Data,Data+Size);
                delete[] Data;R["status"]=Bytes.size()==Size?"pending_write":"read_failed_or_partial";
            }
            R["range_check"]=Reason;R["finished_utc"]=Utc();return Bytes;
        }
        std::vector<uint8_t> Span(uint64_t Address, uint64_t Size, const std::string& Name,
            const std::string& Meaning, bool Fresh = false, std::string Lane = "structure", bool Independent = false)
        {
            json R = {{"address", Hex(Address)}, {"requested_bytes", Size}, {"file", Name},
                {"interpretation", Meaning}, {"read_bytes", 0}, {"started_utc", Utc()}};
            std::vector<uint8_t> Result;
            if (Fresh) Lane = "completion";
            else if (Name.compare(0, 7, "arrays/") == 0) Lane = "speculative";
            R["budget_lane"] = Lane;
            const auto Key = std::make_pair(Address, Size);
            const auto Existing = Saved.find(Key);
            // Independent bypasses saved evidence while retaining the caller's bounded lane.
            if (Existing != Saved.end() && !Fresh && !Independent)
            {
                // Traverse exactly the bytes already preserved, not a second
                // potentially changed version from the running process.
                const auto Location = Report["storage"].find(Existing->second);
                const auto StoredFile = Location == Report["storage"].end()
                    ? Existing->second : (*Location)["file"].get<std::string>();
                std::ifstream Input(FileSystems::CombinePath(Root, StoredFile), std::ios::binary);
                if (Location != Report["storage"].end()) Input.seekg((*Location)["offset"].get<uint64_t>());
                Result.resize(static_cast<size_t>(Size));
                Input.read(reinterpret_cast<char*>(Result.data()), Result.size());
                R["file"] = Existing->second;
                R["status"] = Input ? "reused_file" : "saved_file_read_failed";
                R["finished_utc"] = Utc();
                Report["reads"].push_back(R);
                if (!Input) Result.clear();
                return Result;
            }
            if (!Size) R["status"] = "empty";
            else if (!Pointer(Address) || Size > 0x0000800000000000ull - Address)
                R["status"] = "invalid_address";
            else if (Size > SpanLimit || !Budget.Fits(Lane, Size))
                R["status"] = "budget_rejected";
            else if (++Queries > 250000 && !Fresh)
                R["status"] = "query_limit_rejected";
            else
            {
                std::string Reason;
                if (!ReadableRange(CoDAssets::GameInstance->GetCurrentProcess(), Address, Size, Reason))
                {
                    R["status"] = "unreadable_range";
                    R["range_check"] = Reason;
                    R["finished_utc"] = Utc();
                    Report["reads"].push_back(R);
                    return Result;
                }
                R["range_check"] = Reason;
                uintptr_t Read = 0;
                auto Data = CoDAssets::GameInstance->Read(Address, static_cast<uintptr_t>(Size), Read);
                Budget.Charge(Lane, Size); // A race after preflight can still fail, but cannot starve another lane.
                R["read_bytes"] = Read;
                if (Data && Read) Result.assign(Data, Data + std::min<uint64_t>(Read, Size));
                delete[] Data;
                if (Result.empty()) R["status"] = "read_failed";
                else if (!Write(Name, Result.data(), Result.size())) R["status"] = "write_failed";
                else
                {
                    R["status"] = Read == Size ? "captured" : "partial_read";
                    if (Read == Size && Existing == Saved.end()) Saved[Key] = Name;
                }
            }
            R["finished_utc"] = Utc();
            Report["reads"].push_back(R);
            // Never parse partial data as a complete array.
            if (Result.size() != Size) Result.clear();
            return Result;
        }
        // A second live read, never a Saved-cache reuse. Save differing bytes only.
        // Shares the bounded resident_scene lane; no extra unbounded memory dump.
        bool VerifySpan(uint64_t Address, const std::vector<uint8_t>& Expected, const std::string& Name)
        {
            const auto Size=Expected.size();
            json R={{"address",Hex(Address)},{"bytes",Size},{"source",Name},
                {"started_utc",Utc()},{"status","not_checked"},{"budget_lane","resident_scene"}};
            bool Same=false;
            std::string Reason;
            if(!Size) {Same=true; R["status"]="empty";}
            else if(Size>SpanLimit || !Budget.Fits("resident_scene",Size)) R["status"]="budget_rejected";
            else if(++Queries>250000) R["status"]="query_limit_rejected";
            else if(!ReadableRange(CoDAssets::GameInstance->GetCurrentProcess(),Address,Size,Reason))
            {R["status"]="unreadable_range";R["range_check"]=Reason;}
            else
            {
                uintptr_t Read=0;
                auto Data=CoDAssets::GameInstance->Read(Address,static_cast<uintptr_t>(Size),Read);
                Budget.Charge("resident_scene",Size); R["read_bytes"]=Read;
                if(!Data || Read!=Size) R["status"]="read_failed_or_partial";
                else
                {
                    Same=memcmp(Data,Expected.data(),Size)==0;
                    R["status"]=Same?"unchanged":"changed";
                    if(!Same)
                    {
                        const auto File="verification_changes/"+std::to_string(Report["verifications"].size())+".bin";
                        R["changed_bytes_file"]=File;
                        R["changed_bytes_saved"]=Write(File,reinterpret_cast<const uint8_t*>(Data),Size);
                    }
                }
                delete[] Data;
            }
            R["finished_utc"]=Utc(); Report["verifications"].push_back(R); return Same;
        }
        void Image(uint64_t P, int Priority = 0)
        {
            auto Prior = ImagePriority.find(P);
            if (Prior == ImagePriority.end()) ImagePriority[P] = Priority;
            else Prior->second = std::min(Prior->second, Priority);
            if (!Images.insert(P).second) return;
            const auto Stem = "images/" + Hex(P);
            const auto B = Span(P, sizeof(BOCWGfxImage), Stem + ".header.bin", "BOCWGfxImage header");
            if (B.empty()) return;
            BOCWGfxImage I{}; memcpy(&I, B.data(), sizeof(I));
            json J = {{"address", Hex(P)}, {"name_hash", Hex(I.NamePtr & 0x0FFFFFFFFFFFFFFFull)},
                {"image_format", I.ImageFormat}, {"nominal_dimensions", {I.LoadedMipWidth, I.LoadedMipHeight}},
                {"loaded_levels", I.LoadedMipLevels}, {"stream_mip_count", I.GfxMipMaps},
                {"loaded_pointer", Hex(I.LoadedMipPtr)}, {"loaded_bytes", I.LoadedMipSize}};
            const auto Name = GameBlackOpsCW::AssetNameCache.NameDatabase.find(I.NamePtr & 0x0FFFFFFFFFFFFFFFull);
            if (Name != GameBlackOpsCW::AssetNameCache.NameDatabase.end()) J["resolved_name"] = Name->second;
            Report["images"].push_back(J);
            PendingPayloads.push_back({{"owner_image", P}, {"address", I.LoadedMipPtr}, {"size", I.LoadedMipSize},
                {"file", Stem + ".loaded.bin"}});
            Span(I.UnknownPtr1, I.UnknownPtr1 ? 256 : 0, Stem + ".stream_prefix.bin", "unknown stream descriptor: 256-byte prefix, extent unverified");
            auto Mips = Span(I.GfxMipsPtr, uint64_t(I.GfxMipMaps) * sizeof(BOCWGfxMip),
                Stem + ".mips.bin", "BOCWGfxMip array including all stream keys");
            for (size_t O = 0; O + sizeof(BOCWGfxMip) <= Mips.size(); O += sizeof(BOCWGfxMip))
            {
                BOCWGfxMip M{}; memcpy(&M, Mips.data() + O, sizeof(M));
                if (!M.HashID) continue;
                PackageOwners[M.HashID].push_back(P);
                if (!Packages.insert(M.HashID).second) continue;
                json K = {{"key", Hex(M.HashID)}, {"owner_image", Hex(P)}, {"mip_index", O / sizeof(M)},
                    {"descriptor_size_field", M.Size}, {"descriptor_dimensions", {M.Width, M.Height}}};
                PendingPackages.push_back(K);
            }
        }
        void Material(uint64_t P, int Priority = 0)
        {
            if (!Materials.insert(P).second)
            {
                for (const auto I : MaterialImages[P]) Image(I, Priority);
                return;
            }
            const auto Stem = "materials/" + Hex(P);
            const auto B = Span(P, 0x158, Stem + ".header.bin", "BOCWXMaterialEx header");
            if (B.empty()) return;
            const auto Table = Span(U64(B, 0x30), uint64_t(B[0x148]) * 0x18,
                Stem + ".images.bin", "material image bindings, 0x18-byte records");
            json J = {{"address", Hex(P)}, {"name_hash", Hex(U64(B, 0) & 0x0FFFFFFFFFFFFFFFull)},
                {"techset", Hex(U64(B, 0x28))}, {"images", json::array()}};
            const auto Name = GameBlackOpsCW::AssetNameCache.NameDatabase.find(U64(B, 0) & 0x0FFFFFFFFFFFFFFFull);
            if (Name != GameBlackOpsCW::AssetNameCache.NameDatabase.end()) J["resolved_name"] = Name->second;
            for (size_t O = 0; O + 0x18 <= Table.size(); O += 0x18)
            {
                const auto ImagePtr = U64(Table, O);
                J["images"].push_back({{"record_offset", O}, {"pointer", Hex(ImagePtr)}});
                MaterialImages[P].push_back(ImagePtr);
                Image(ImagePtr, Priority);
            }
            const auto InstancePointer = U64(B, 0x40);
            const auto Instance = Span(InstancePointer, InstancePointer ? 220 : 0,
                Stem + ".instance_prefix.bin",
                "material instance prefix; first 24 bytes declare parameter and image-reference extents");
            json InstanceInfo = {{"address", Hex(InstancePointer)}, {"status", "absent"}};
            if (Instance.size() >= 24)
            {
                const auto DataPointer = U64(Instance, 0);
                const auto ReferencesPointer = U64(Instance, 8);
                const auto WordCount = U32(Instance, 16);
                const auto ReferenceCount = U32(Instance, 20);
                InstanceInfo = {{"address", Hex(InstancePointer)},
                    {"data_pointer", Hex(DataPointer)}, {"word_count", WordCount},
                    {"data_bytes", uint64_t(WordCount) * 4},
                    {"references_pointer", Hex(ReferencesPointer)},
                    {"reference_count", ReferenceCount},
                    {"reference_bytes", uint64_t(ReferenceCount) * 16}};
                const bool DataValid = Pointer(DataPointer) && WordCount > 0 && WordCount <= 4096;
                const bool ReferencesValid = ReferenceCount == 0 ||
                    (Pointer(ReferencesPointer) && ReferenceCount <= 1024);
                InstanceInfo["declared_extents_valid"] = DataValid && ReferencesValid;
                if (DataValid)
                {
                    const auto Data = Span(DataPointer, uint64_t(WordCount) * 4,
                        Stem + ".instance_parameters.bin",
                        "complete material-instance parameter payload declared by its header");
                    InstanceInfo["parameter_payload_captured"] = !Data.empty();
                }
                if (ReferencesValid && ReferenceCount)
                {
                    const auto References = Span(ReferencesPointer, uint64_t(ReferenceCount) * 16,
                        Stem + ".instance_references.bin",
                        "complete 16-byte material-instance image/word-offset reference records");
                    InstanceInfo["references_captured"] = !References.empty();
                }
                else if (ReferenceCount == 0)
                    InstanceInfo["references_captured"] = true;
            }
            J["material_instance"] = InstanceInfo;
            Report["materials"].push_back(J);
            Span(U64(B, 0x118), U64(B, 0x110), Stem + ".constants.bin", "CBuffersPtr/CBuffersSize from existing material reader");
            for (size_t I = 0; I < 13; ++I)
            {
                auto Pass = Span(U64(B, 0xA8 + I * 8), U64(B, 0xA8 + I * 8) ? 32 : 0,
                    Stem + ".pass_" + std::to_string(I) + ".bin", "per-pass buffer descriptor prefix; extent unverified");
                if (!Pass.empty()) Span(U64(Pass, 16), U64(Pass, 16) ? 4 : 0,
                    Stem + ".pass_" + std::to_string(I) + ".offset.bin", "first constant-buffer offset used by existing reader");
            }
            const auto Tech = U64(B, 0x28);
            if (!Techsets.insert(Tech).second) return;
            const auto T = Span(Tech, 168, "techsets/" + Hex(Tech) + ".bin", "techset header and 18 technique pointers");
            for (size_t I = 0; I < 18 && !T.empty(); ++I)
            {
                const auto Ptr = U64(T, 24 + I * 8);
                if (!Ptr) continue;
                const auto Technique = Span(Ptr, 0x30, "techniques/" + Hex(Ptr) + ".bin", "technique descriptor");
                const auto ShaderPtrs = Span(U64(Technique, 0x28), U64(Technique, 0x28) ? 32 : 0,
                    "techniques/" + Hex(Ptr) + ".stages.bin", "four shader descriptor pointers");
                for (size_t S = 0; S + 8 <= ShaderPtrs.size(); S += 8)
                {
                    const auto Shader = U64(ShaderPtrs, S);
                    if (!Shader || !Shaders.insert(Shader).second) continue;
                    const auto D = Span(Shader, 0x18, "shaders/" + Hex(Shader) + ".descriptor.bin", "shader descriptor: hash, bytecode pointer, byte count");
                    if (!D.empty()) Span(U64(D, 8), U64(D, 16), "shaders/" + Hex(Shader) + ".dxil.bin", "unmodified bytecode; not necessarily the VT composition pass");
                }
            }
        }
        // Preserve small structural evidence before bulk texture payloads can
        // consume the work budget. This also keeps image headers when a cache
        // contains more texture data than fits in one bounded session.
        void FlushPayloads()
        {
            std::stable_sort(PendingPayloads.begin(), PendingPayloads.end(), [&](const json& A, const json& B) {
                return ImagePriority[A["owner_image"].get<uint64_t>()] < ImagePriority[B["owner_image"].get<uint64_t>()];
            });
            size_t Done = 0;
            for (const auto& P : PendingPayloads)
            {
                Progress("resident_payloads", 24 + static_cast<uint32_t>(2 * Done / std::max<size_t>(1, PendingPayloads.size())), Done, PendingPayloads.size());
                Span(P["address"].get<uint64_t>(), P["size"].get<uint64_t>(),
                    P["file"].get<std::string>(), "unmodified resident image payload, no DDS header or channel patching",
                    false, ImagePriority[P["owner_image"].get<uint64_t>()] < 2 ? "resident_terrain" : "resident_scene");
                ++Done;
            }
            for (auto& K : PendingPackages)
            {
                int Priority = 2;
                const auto Key = std::stoull(K["key"].get<std::string>(), nullptr, 16);
                K["owner_images"] = json::array();
                for (const auto Owner : PackageOwners[Key])
                {
                    Priority = std::min(Priority, ImagePriority[Owner]);
                    K["owner_images"].push_back(Hex(Owner));
                }
                K["priority"] = Priority;
                K["size_field_interpretation"] = "raw packed field; not used as an allocation size";
            }
            std::stable_sort(PendingPackages.begin(), PendingPackages.end(), [](const json& A, const json& B) {
                if (A["priority"] != B["priority"]) return A["priority"] < B["priority"];
                return A["mip_index"] > B["mip_index"];
            });
            Done = 0;
            for (auto K : PendingPackages)
            {
                Progress("local_packages", 26 + static_cast<uint32_t>(8 * Done / std::max<size_t>(1, PendingPackages.size())), Done, PendingPackages.size());
                ++Done;
                const auto Key = std::stoull(K["key"].get<std::string>(), nullptr, 16);
                const std::string Lane = K["priority"].get<int>() < 2 ? "packages_terrain" : "packages_scene";
                K["budget_lane"] = Lane;
                PackageCacheObject Info{}; std::string Path;
                // Local package extraction only. Never fetch CDN content for a sweep.
                if (!CoDAssets::GamePackageCache || !CoDAssets::GamePackageCache->DescribePackageObject(Key, Info, Path))
                    K["status"] = "not_in_local_package_cache";
                else if (!Info.CompressedSize || Info.CompressedSize > SpanLimit || !Budget.Fits(Lane, Info.CompressedSize))
                    K["status"] = "budget_rejected";
                else try
                {
                    K["package_path"] = Path; K["package_offset"] = Info.Offset;
                    K["compressed_bytes"] = Info.CompressedSize;
                    Budget.Charge(Lane, Info.CompressedSize);
                    uint32_t Size = 0;
                    auto Data = CoDAssets::GamePackageCache->ExtractPackageObjectRaw(Key, Size);
                    K["raw_bytes"] = Size;
                    if (!Data || Size != Info.CompressedSize) K["status"] = "raw_extract_failed";
                    else
                    {
                        const auto Raw = "packages/" + Hex(Key) + ".xsub.bin";
                        K["raw_file"] = Raw;
                        const bool RawOk = Write(Raw, Data.get(), Size);
                        K["raw_status"] = RawOk ? "captured" : "write_failed";
                        const auto Plan = PlanPackage(Data.get(), Size, Info.Offset, SpanLimit);
                        K["decode_plan"] = Plan.Reason;
                        K["planned_decoded_bytes"] = Plan.OutputBytes;
                        if (!Plan.Valid) K["status"] = "raw_only_unsupported_decode";
                        else if (!Budget.Charge(Lane, Plan.OutputBytes)) K["status"] = "raw_only_decoded_budget_rejected";
                        else
                        {
                            std::vector<uint8_t> Decoded(static_cast<size_t>(Plan.OutputBytes));
                            size_t Out = 0; bool Ok = true;
                            for (const auto& B : Plan.Blocks)
                            {
                                if (!B.OutputBytes) continue;
                                uint64_t Actual = 0;
                                if (B.Codec == 0)
                                {
                                    memcpy(Decoded.data() + Out, Data.get() + B.Offset, B.InputBytes);
                                    Actual = B.InputBytes;
                                }
                                else if (B.Codec == 3)
                                    Actual = Compression::DecompressLZ4Block(reinterpret_cast<const int8_t*>(Data.get() + B.Offset),
                                        reinterpret_cast<int8_t*>(Decoded.data() + Out), static_cast<int32_t>(B.InputBytes), static_cast<int32_t>(B.OutputBytes));
                                else
                                    Actual = Siren::Decompress(Data.get() + B.Offset + 4, static_cast<uint32_t>(B.InputBytes - 4),
                                        Decoded.data() + Out, static_cast<uint32_t>(B.OutputBytes));
                                if (Actual != B.OutputBytes) { Ok = false; break; }
                                Out += B.OutputBytes;
                            }
                            if (!Ok) K["status"] = "raw_only_decode_failed";
                            else
                            {
                                const auto File = "packages/" + Hex(Key) + ".bin";
                                K["file"] = File; K["extracted_bytes"] = Decoded.size();
                                K["status"] = Write(File, Decoded.data(), Decoded.size()) ? "captured" : "write_failed";
                            }
                        }
                        if (!RawOk) K["status"] = "write_failed";
                    }
                }
                catch (const std::exception& E)
                {
                    K["status"] = K.value("raw_status", "") == "captured" ? "raw_only_exception" : "extraction_exception";
                    K["error"] = E.what();
                }
                Report["packages"].push_back(K);
            }
        }
        bool Finish()
        {
            if (Pack != INVALID_HANDLE_VALUE)
            {
                FlushFileBuffers(Pack);
                CloseHandle(Pack); Pack = INVALID_HANDLE_VALUE;
            }
            Report["small_record_pack_bytes"] = PackOffset;
            Report["finished_utc"] = Utc();
            Report["budget_charged_bytes"] = Budget.Total();
            Report["budget_charged_by_lane"] = Budget.Used;
            Report["complete_game_memory_dump"] = false;
            const auto S = Report.dump(2);
            return Write("evidence.json", reinterpret_cast<const uint8_t*>(S.data()), S.size());
        }
    };
}
