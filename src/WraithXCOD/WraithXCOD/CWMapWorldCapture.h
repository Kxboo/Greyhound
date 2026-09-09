#pragma once
#include <cmath>
#include <algorithm>
#include <set>
#include <map>
#include <limits>
#include "TerrainResearchCapture.h"
#include "GameBlackOpsCW.h"
#include "CWDistrictPayload.h"

// Cold War gfx_map (pool 0x1B) static model instances.
//
// The 64-byte placement record below was measured on a live zm_platinum and
// checked against an independent C2M export of the same loaded map: position,
// uniform scale and rotation agreed for every sampled record. The stride and
// the array itself are still located by validation at runtime rather than by a
// fixed header offset, so a build that moves the field is reported as unlocated
// instead of silently decoded from the wrong address.
//
// DEAD END, do not restore: a 72-byte record (quat +0, position +16, scale +28,
// XModel* +40, index +48) also decodes and agrees with C2M, but it is an island
// of ~34 records rather than the placement array. This capture targeted it until
// now, which is why it never produced a usable placement set.
//
// The 64-byte record carries NO model reference. Instance -> model identity
// lives in a parallel u32 array with one entry per instance; locating it and
// mapping id -> name is unresolved, so this capture emits measured candidates
// for offline work and does not name instances on a guess.
namespace CWMapWorldCapture
{
    using TerrainResearch::json;
    using TerrainResearch::Hex;
    using TerrainResearch::Pointer;

    inline uint64_t RU64(const uint8_t* P) { uint64_t V; memcpy(&V, P, 8); return V; }
    inline uint32_t RU32(const uint8_t* P) { uint32_t V; memcpy(&V, P, 4); return V; }
    inline float    RF32(const uint8_t* P) { float V; memcpy(&V, P, 4); return V; }

    constexpr uint32_t RecordStride = 64;
    constexpr uint32_t OffBoundsA = 0x00;  // float[4] extent, unconfirmed
    constexpr uint32_t OffQuat = 0x10;     // float[4] x,y,z,w, unit
    constexpr uint32_t OffPosition = 0x20; // float[3] world inches
    constexpr uint32_t OffScale = 0x2C;    // float, uniform
    constexpr uint32_t OffBoundsB = 0x30;  // float[4] extent, unconfirmed

    struct Instance
    {
        float Quat[4]; float Position[3]; float Scale;
        float BoundsA[4]; float BoundsB[4];
    };

    inline Instance ReadRecord(const uint8_t* B)
    {
        Instance I{};
        for (int K = 0; K < 4; ++K) I.Quat[K] = RF32(B + OffQuat + 4 * K);
        for (int K = 0; K < 3; ++K) I.Position[K] = RF32(B + OffPosition + 4 * K);
        I.Scale = RF32(B + OffScale);
        for (int K = 0; K < 4; ++K) I.BoundsA[K] = RF32(B + OffBoundsA + 4 * K);
        for (int K = 0; K < 4; ++K) I.BoundsB[K] = RF32(B + OffBoundsB + 4 * K);
        return I;
    }

    // The 72-byte reading leaned on a valid XModel pointer to reject noise. This
    // record has no pointer, so the discrimination has to come from the data: a
    // unit quaternion is the load-bearing test (four floats whose squares sum to
    // 1), backed by finite position, sane scale and finite extents.
    inline bool Plausible(const Instance& I)
    {
        const double L = std::sqrt(double(I.Quat[0]) * I.Quat[0] + double(I.Quat[1]) * I.Quat[1] +
            double(I.Quat[2]) * I.Quat[2] + double(I.Quat[3]) * I.Quat[3]);
        if (!(L > 0.999 && L < 1.001)) return false;
        for (float P : I.Position) if (!std::isfinite(P) || std::fabs(P) > 1.0e7f) return false;
        if (!(I.Scale > 0.0f && I.Scale < 1000.0f)) return false;
        for (float V : I.BoundsA) if (!std::isfinite(V)) return false;
        for (float V : I.BoundsB) if (!std::isfinite(V)) return false;
        return true;
    }

    // ZYX intrinsic. Reproduced C2M's RotationDegrees on every sampled record,
    // so exports from either tool can be diffed without a convention guess.
    inline void EulerDegrees(const float Q[4], double Out[3])
    {
        const double X = Q[0], Y = Q[1], Z = Q[2], W = Q[3];
        const double SinR = 2.0 * (W * X + Y * Z), CosR = 1.0 - 2.0 * (X * X + Y * Y);
        double SinP = 2.0 * (W * Y - Z * X);
        SinP = std::max(-1.0, std::min(1.0, SinP));
        const double SinYw = 2.0 * (W * Z + X * Y), CosYw = 1.0 - 2.0 * (Y * Y + Z * Z);
        constexpr double Deg = 57.295779513082320876798154814105;
        Out[0] = std::atan2(SinR, CosR) * Deg;
        Out[1] = std::asin(SinP) * Deg;
        Out[2] = std::atan2(SinYw, CosYw) * Deg;
    }

    inline std::vector<uint8_t> ReadBytes(uint64_t Address, uint64_t Size)
    {
        std::vector<uint8_t> B;
        if (!CoDAssets::GameInstance || !Pointer(Address) || !Size || Size > 0x4000000ull) return B;
        B.resize(size_t(Size));
        const auto Got = CoDAssets::GameInstance->Read(B.data(), uintptr_t(Address), uintptr_t(Size));
        if (Got != Size) B.clear();
        return B;
    }

    inline bool ZeroRecord(const uint8_t* B)
    {
        for (uint32_t I = 0; I < RecordStride; ++I) if (B[I]) return false;
        return true;
    }

    // The header's counted pointers do not all start a record boundary, and the
    // instance array begins with a run of cleared slots, so neither the count
    // nor the first record can be trusted on its own. Sample across the whole
    // span at every 8-byte alignment and keep the reading that actually decodes.
    struct Fit { uint32_t Alignment = 0, Good = 0, Bad = 0, Empty = 0; };

    inline Fit FitArray(uint64_t Address, uint64_t SpanBytes)
    {
        Fit Best; bool Have = false;
        if (SpanBytes < RecordStride) return Best;
        for (uint32_t Align = 0; Align < RecordStride && Align + RecordStride <= SpanBytes; Align += 8)
        {
            const uint64_t Usable = SpanBytes - Align;
            const uint64_t Slots = Usable / RecordStride;
            if (!Slots) continue;
            const uint32_t Samples = uint32_t(std::min<uint64_t>(Slots, 96));
            Fit Current; Current.Alignment = Align;
            for (uint32_t S = 0; S < Samples; ++S)
            {
                const uint64_t Slot = Samples == 1 ? 0 : uint64_t(S) * (Slots - 1) / (Samples - 1);
                const auto B = ReadBytes(Address + Align + Slot * RecordStride, RecordStride);
                if (B.size() != RecordStride) { ++Current.Bad; continue; }
                if (ZeroRecord(B.data())) ++Current.Empty;
                else if (Plausible(ReadRecord(B.data()))) ++Current.Good;
                else ++Current.Bad;
            }
            if (!Have || Current.Good > Best.Good) { Best = Current; Have = true; }
        }
        return Best;
    }

    inline uint32_t FitPercent(const Fit& F)
    {
        const uint32_t Decided = F.Good + F.Bad;
        return Decided ? F.Good * 100 / Decided : 0;
    }

    // Address of some record that decodes, used to anchor the run walk.
    inline uint64_t FindAnchor(uint64_t Address, uint64_t SpanBytes, uint32_t Align)
    {
        if (SpanBytes <= Align) return 0;
        const uint64_t Slots = (SpanBytes - Align) / RecordStride;
        const uint32_t Samples = uint32_t(std::min<uint64_t>(Slots, 96));
        for (uint32_t S = 0; S < Samples; ++S)
        {
            const uint64_t Slot = Samples == 1 ? 0 : uint64_t(S) * (Slots - 1) / (Samples - 1);
            const uint64_t At = Address + Align + Slot * RecordStride;
            const auto B = ReadBytes(At, RecordStride);
            if (B.size() == RecordStride && !ZeroRecord(B.data()) && Plausible(ReadRecord(B.data())))
                return At;
        }
        return 0;
    }

    struct Run { uint64_t Base = 0; uint64_t Slots = 0; };

    // The counted pointers in the header do not bound this array: the accepted
    // ones cover a few dozen records while the run continues for thousands.
    // Grow outward from a decoding record instead and let the data end itself.
    inline Run ExpandRun(uint64_t Anchor, uint64_t MaxBytes)
    {
        constexpr uint32_t Chunk = 512;
        // The array interleaves cleared slots and records this decoder cannot
        // read yet, so a single undecodable slot must not end the walk. Only a
        // long unbroken stretch of them is treated as the end of the array, and
        // the run is trimmed back to the last slot that actually decoded.
        constexpr uint32_t GapLimit = 64;
        const uint64_t Want = uint64_t(Chunk) * RecordStride;

        uint64_t End = Anchor, LastGood = Anchor + RecordStride;
        uint32_t Gap = 0;
        while (End - Anchor < MaxBytes)
        {
            const auto B = ReadBytes(End, Want);
            if (B.size() != Want) break;
            uint32_t Taken = 0;
            bool Stop = false;
            for (; Taken < Chunk && !Stop; ++Taken)
            {
                const auto* At = B.data() + size_t(Taken) * RecordStride;
                if (!ZeroRecord(At) && Plausible(ReadRecord(At)))
                {
                    Gap = 0;
                    LastGood = End + uint64_t(Taken + 1) * RecordStride;
                }
                else if (++Gap > GapLimit) Stop = true;
            }
            End += uint64_t(Taken) * RecordStride;
            if (Stop) break;
        }

        uint64_t Base = Anchor, FirstGood = Anchor;
        Gap = 0;
        while (Anchor - Base < MaxBytes && Base >= Want)
        {
            const auto B = ReadBytes(Base - Want, Want);
            if (B.size() != Want) break;
            uint32_t Taken = 0;
            bool Stop = false;
            for (; Taken < Chunk && !Stop; ++Taken)
            {
                const auto* At = B.data() + size_t(Chunk - 1 - Taken) * RecordStride;
                if (!ZeroRecord(At) && Plausible(ReadRecord(At)))
                {
                    Gap = 0;
                    FirstGood = Base - uint64_t(Taken + 1) * RecordStride;
                }
                else if (++Gap > GapLimit) Stop = true;
            }
            Base -= uint64_t(Taken) * RecordStride;
            if (Stop) break;
        }

        Run R; R.Base = FirstGood;
        R.Slots = LastGood > FirstGood ? (LastGood - FirstGood) / RecordStride : 0;
        return R;
    }

    inline std::string MapName(const std::vector<uint8_t>& Header)
    {
        if (Header.size() < 16) return std::string();
        const auto P = RU64(Header.data() + 8);
        if (!Pointer(P)) return std::string();
        const auto B = ReadBytes(P, 128);
        std::string Name;
        for (uint8_t Ch : B)
        {
            if (!Ch) break;
            if (Ch < 32 || Ch >= 127) return std::string();
            Name.push_back(char(Ch));
        }
        return Name;
    }

    inline std::string ModelHashName(uint64_t Hash)
    {
        Hash &= 0xFFFFFFFFFFFFFFFull;
        if (!Hash) return {};
        const auto& DB = GameBlackOpsCW::AssetNameCache.NameDatabase;
        const auto Hit = DB.find(Hash);
        return Hit != DB.end() ? Hit->second : Strings::Format("xmodel_%llx", Hash);
    }

    inline std::string ModelName(uint64_t XModelPtr, std::map<uint64_t, std::string>& Cache)
    {
        const auto Found = Cache.find(XModelPtr);
        if (Found != Cache.end()) return Found->second;
        std::string Name;
        const auto B = ReadBytes(XModelPtr, 8);
        if (B.size() == 8)
        {
            // BOCWXModel::NamePtr is a 60-bit hash in the same encoding the
            // xmodel pool uses, so Greyhound's existing index resolves it.
            const auto Hash = RU64(B.data()) & 0xFFFFFFFFFFFFFFFull;
            Name = ModelHashName(Hash);
        }
        Cache[XModelPtr] = Name;
        return Name;
    }

    // The placement data is partitioned by the DISTRICTS asset on maps where
    // gfx_map contains only the district descriptors. The live structure is:
    // districts +0x48 -> counted records of 0x88 bytes; record +0x68 -> a 56-byte
    // district payload descriptor; descriptor +0x20 -> payload and +0x30 low
    // 32 bits -> allocation bytes. The payload header stores the global start,
    // count, reference table and 64-byte transform table at +0x108..+0x118.
    constexpr uint32_t DistrictRecordStride = 0x88;
    constexpr uint32_t DistrictCountOffset = 0x40;
    constexpr uint32_t DistrictCountLimit = 4096;
    constexpr uint32_t DistrictTableOffset = 0x48;
    constexpr uint32_t DistrictPayloadDescriptorOffset = 0x68;
    constexpr uint32_t DistrictPayloadAddressOffset = 0x20;
    constexpr uint32_t DistrictPayloadBytesOffset = 0x30;
    constexpr uint32_t DistrictHeaderStartOffset = 0x108;
    constexpr uint32_t DistrictHeaderCountOffset = 0x10C;
    constexpr uint32_t DistrictHeaderReferencesOffset = 0x110;
    constexpr uint32_t DistrictHeaderTransformsOffset = 0x118;
    constexpr uint32_t DistrictReferenceStride = 64;

    // District transform records are distinct from the gfx_map records above.
    // Validated against all 46,281 platinum C2M position/scale pairs.
    inline Instance ReadDistrictRecord(const uint8_t* B)
    {
        Instance I{};
        for (int K = 0; K < 4; ++K) I.Quat[K] = RF32(B + 4 * K);
        for (int K = 0; K < 3; ++K) I.Position[K] = RF32(B + 16 + 4 * K);
        I.Scale = RF32(B + 28);
        return I;
    }

    inline std::vector<uint8_t> LocalDistrictPackage(TerrainResearch::Capture& C,
        uint64_t Key, uint64_t ExpectedBytes, json& Evidence)
    {
        Evidence = {{"key", Hex(Key)}, {"expected_bytes", ExpectedBytes}};
        std::vector<uint8_t> Decoded;
        auto Fail = [&](const std::string& Reason) { Evidence["status"] = Reason; return std::vector<uint8_t>(); };
        if (!Key || !CoDAssets::GamePackageCache) return Fail("local_package_unavailable");
        if (ExpectedBytes < CWDistrictPayload::HeaderBytes || ExpectedBytes > CWDistrictPayload::MaxBytes)
            return Fail("allocation_size_rejected");
        CoDAssets::GamePackageCache->WaitForPackageCacheLoad();
        PackageCacheObject Info{}; std::string Path;
        if (!CoDAssets::GamePackageCache->DescribePackageObject(Key, Info, Path))
            return Fail("key_not_in_local_package_cache");
        Evidence["package_path"] = Path; Evidence["package_offset"] = Info.Offset;
        Evidence["compressed_bytes"] = Info.CompressedSize;
        if (!Info.CompressedSize || Info.CompressedSize > CWDistrictPayload::MaxBytes ||
            !C.ReserveScenePackageBytes(Info.CompressedSize)) return Fail("package_budget_rejected");
        try
        {
            uint32_t Size = 0;
            auto Raw = CoDAssets::GamePackageCache->ExtractPackageObjectRaw(Key, Size);
            if (!Raw || Size != Info.CompressedSize) return Fail("raw_extract_failed");
            const auto Plan = TerrainResearch::PlanPackage(Raw.get(), Size, Info.Offset, ExpectedBytes);
            Evidence["decode_plan"] = Plan.Reason;
            if (!Plan.Valid || Plan.OutputBytes != ExpectedBytes) return Fail("decoded_allocation_size_mismatch");
            if (!C.ReserveScenePackageBytes(ExpectedBytes)) return Fail("decoded_budget_rejected");
            Decoded.resize(size_t(ExpectedBytes));
            size_t Out = 0;
            for (const auto& B : Plan.Blocks)
            {
                if (!B.OutputBytes) continue;
                uint64_t Actual = 0;
                if (B.Codec == 0)
                { memcpy(Decoded.data() + Out, Raw.get() + B.Offset, B.InputBytes); Actual = B.InputBytes; }
                else if (B.Codec == 3)
                    Actual = Compression::DecompressLZ4Block(reinterpret_cast<const int8_t*>(Raw.get() + B.Offset),
                        reinterpret_cast<int8_t*>(Decoded.data() + Out), int32_t(B.InputBytes), int32_t(B.OutputBytes));
                else
                    Actual = Siren::Decompress(Raw.get() + B.Offset + 4, uint32_t(B.InputBytes - 4),
                        Decoded.data() + Out, uint32_t(B.OutputBytes));
                if (Actual != B.OutputBytes) return Fail("package_decompression_failed");
                Out += B.OutputBytes;
            }
            const auto File = "packages/district_" + Hex(Key) + ".bin";
            Evidence["file"] = File;
            if (!C.Write(File, Decoded.data(), Decoded.size())) return Fail("package_evidence_write_failed");
            Evidence["status"] = "decoded_local_package";
        }
        catch (const std::exception& E) { Evidence["error"] = E.what(); return Fail("package_exception"); }
        return Decoded;
    }

    inline void CaptureDistricts(TerrainResearch::Capture& C, uint32_t Pool,
        const std::vector<uint8_t>& Asset)
    {
        const uint32_t DistrictCount = Asset.size() >= DistrictCountOffset + 4
            ? RU32(Asset.data() + DistrictCountOffset) : 0;
        if (DistrictCount == 0 || DistrictCount > DistrictCountLimit)
        {
            C.Report["district_static_models"] = {{"located", false},
                {"status", "invalid_district_count"}, {"count", DistrictCount}};
            return;
        }
        json Result = { {"schema", "cw-district-static-models-v1"}, {"source_pool", Pool},
            {"district_count_offset", DistrictCountOffset},
            {"district_record_stride", DistrictRecordStride}, {"district_count", DistrictCount},
            {"district_payload_descriptor_offset", DistrictPayloadDescriptorOffset},
            {"placement_record_stride", RecordStride},
            {"field_offsets", {{"quaternion_xyzw", 0}, {"position", 16},
                {"uniform_scale", 28}, {"bounds_min", 32}, {"bounds_max", 44}}},
            {"euler_convention", "ZYX intrinsic, degrees; X=roll, Y=pitch, Z=yaw"},
            {"model_identity", "resolved through each placement reference record and Greyhound's xmodel name database"} };

        if (Asset.size() < DistrictTableOffset + 8)
        {
            Result["status"] = "asset_slot_too_small";
            const auto Text = Result.dump(2);
            C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Text.data()), Text.size());
            C.Report["district_static_models"] = {{"located", false}};
            return;
        }
        const uint64_t TableAddress = RU64(Asset.data() + DistrictTableOffset);
        if (!Pointer(TableAddress))
        {
            Result["status"] = "district_table_pointer_unresolved";
            const auto Text = Result.dump(2);
            C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Text.data()), Text.size());
            C.Report["district_static_models"] = {{"located", false}};
            return;
        }

        const uint64_t TableBytes = uint64_t(DistrictRecordStride) * DistrictCount;
        const auto Table = C.Span(TableAddress, TableBytes, "typed/district_table.bin",
            "district records containing placement partition descriptors", false, "structure");
        const bool TableStable = Table.size() == TableBytes &&
            C.VerifySpan(TableAddress, Table, "typed/district_table.bin");
        Result["district_table"] = {{"address", Hex(TableAddress)}, {"bytes", Table.size()},
            {"readback_unchanged", TableStable}};
        if (Table.size() != TableBytes)
        {
            Result["status"] = "district_table_unreadable";
            const auto Text = Result.dump(2);
            C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Text.data()), Text.size());
            C.Report["district_static_models"] = {{"located", false}, {"readback_unchanged", TableStable}};
            return;
        }

        std::map<uint64_t, std::string> NameCache;
        std::map<std::string, uint32_t> Uses;
        json Models = json::array();
        json Districts = json::array();
        uint32_t Decoded = 0, Unresolved = 0, Recovered = 0, Missing = 0;
        bool Complete = TableStable;
        std::vector<std::pair<uint32_t, uint32_t>> Ranges;

        for (uint32_t District = 0; District < DistrictCount; ++District)
        {
            C.Progress("Reading live and local-package placement districts", uint32_t(95ull*District/DistrictCount), District, DistrictCount);
            const auto* D = Table.data() + size_t(District) * DistrictRecordStride;
            const uint64_t DescriptorAddress = RU64(D + DistrictPayloadDescriptorOffset);
            if (!DescriptorAddress) continue; // Render-only district, no placement payload.
            json DR = {{"district", District}, {"descriptor_address", Hex(DescriptorAddress)}};
            const auto DescriptorName = Strings::Format("typed/district_%02u_descriptor.bin", District);
            const auto Descriptor = C.Span(DescriptorAddress, 56, DescriptorName,
                "district placement payload descriptor", false, "structure");
            if (Descriptor.size() != 56)
            { DR["status"] = "descriptor_unreadable"; ++Missing; Complete = false; Districts.push_back(DR); continue; }
            const uint64_t Address = RU64(Descriptor.data() + DistrictPayloadAddressOffset);
            const uint64_t Bytes = RU32(Descriptor.data() + DistrictPayloadBytesOffset);
            const uint64_t Key = RU64(Descriptor.data() + 8);
            DR["payload_address"] = Hex(Address); DR["payload_bytes"] = Bytes;
            CWDistrictPayload::Layout L;
            std::vector<uint8_t> Refs, Transforms;
            std::vector<std::string> Names;
            bool Packaged = false;
            std::string Error;
            auto ResolveNames = [&]() -> bool
            {
                Names.clear(); Names.reserve(L.Count);
                for (uint32_t I = 0; I < L.Count; ++I)
                {
                    const auto Identity = RU64(Refs.data() + size_t(I) * RecordStride + 16);
                    auto Name = Packaged ? ModelHashName(Identity) : ModelName(Identity, NameCache);
                    if (Name.empty()) { Error = "model_identity_unreadable"; return false; }
                    Names.push_back(std::move(Name));
                }
                return true;
            };
            // Accept a live district only as a whole: stable header, arrays and descriptor.
            auto Live = [&]() -> bool
            {
                if (!Pointer(Address) || Bytes < 288 || Bytes > CWDistrictPayload::MaxBytes)
                { Error = "invalid_live_payload_address_or_size"; return false; }
                const auto HeaderName = Strings::Format("typed/district_%02u_payload.bin", District);
                const auto H = C.Span(Address, 288, HeaderName, "district placement header", false, "resident_scene");
                if (H.size() != 288) { Error = "payload_unreadable"; return false; }
                L.Start = RU32(H.data() + 264); L.Count = RU32(H.data() + 268);
                L.References = RU64(H.data() + 272); L.Transforms = RU64(H.data() + 280);
                const uint64_t ArrayBytes = uint64_t(L.Count) * RecordStride;
                auto Local = [&](uint64_t At) { return At >= Address && At - Address <= Bytes && ArrayBytes <= Bytes - (At - Address); };
                if (!L.Count || uint64_t(L.Start) + L.Count > UINT32_MAX || !Local(L.References) || !Local(L.Transforms) ||
                    L.References - Address < 288 || L.Transforms - Address < 288 ||
                    !(L.References + ArrayBytes <= L.Transforms || L.Transforms + ArrayBytes <= L.References))
                { Error = "payload_layout_unresolved"; return false; }
                const auto RN = Strings::Format("typed/district_%02u_references.bin", District);
                const auto TN = Strings::Format("typed/district_%02u_transforms.bin", District);
                Refs = C.Span(L.References, ArrayBytes, RN, "placement references", false, "resident_scene");
                Transforms = C.Span(L.Transforms, ArrayBytes, TN, "placement transforms", false, "resident_scene");
                if (!CWDistrictPayload::ValidateArrays(Refs, Transforms, L.Count, false, Error) || !ResolveNames()) return false;
                if (!C.VerifySpan(L.References, Refs, RN) || !C.VerifySpan(L.Transforms, Transforms, TN) ||
                    !C.VerifySpan(Address, H, HeaderName) || !C.VerifySpan(DescriptorAddress, Descriptor, DescriptorName))
                { Error = "live_placement_readback_changed_or_unavailable"; return false; }
                return true;
            };
            bool Valid = Live();
            DR["live_status"] = Valid ? "validated" : Error;
            DR["live_readback_unchanged"] = Valid;
            if (!Valid)
            {
                Packaged = true;
                auto Payload = LocalDistrictPackage(C, Key, Bytes, DR["package"]);
                Error.clear();
                Valid = CWDistrictPayload::PackageLayout(Payload, Bytes, L, Error);
                if (Valid)
                {
                    const auto N = size_t(L.Count) * RecordStride;
                    Refs.assign(Payload.begin() + size_t(L.References), Payload.begin() + size_t(L.References) + N);
                    Transforms.assign(Payload.begin() + size_t(L.Transforms), Payload.begin() + size_t(L.Transforms) + N);
                    Valid = CWDistrictPayload::ValidateArrays(Refs, Transforms, L.Count, true, Error) && ResolveNames();
                    if (Valid && !C.VerifySpan(DescriptorAddress, Descriptor, DescriptorName))
                    { Valid = false; Error = "descriptor_changed_during_package_recovery"; }
                }
                DR["package_validation"] = Valid ? "validated" : Error;
            }
            if (!Valid)
            { DR["status"] = "unresolved"; ++Missing; Complete = false; Districts.push_back(DR); continue; }
            if (Packaged) ++Recovered;
            DR["status"] = "decoded"; DR["source"] = Packaged ? "local_package" : "live";
            DR["global_start"] = L.Start; DR["instances"] = L.Count;
            Ranges.emplace_back(L.Start, L.Count);
            for (uint32_t I = 0; I < L.Count; ++I)
            {
                const auto* T = Transforms.data() + size_t(I) * RecordStride;
                const auto Word = RU32(T + 56), Index = Word & 0x7FFFFFFF;
                const auto* R = Refs.data() + size_t(Index) * DistrictReferenceStride;
                const auto& Model = Names[Index];
                const bool Resolved = Model.rfind("xmodel_", 0) != 0;
                if (!Resolved) ++Unresolved;
                const auto Rec = ReadDistrictRecord(T);
                ++Uses[Model]; ++Decoded;
                double E[3]; EulerDegrees(Rec.Quat, E);
                json Row = {{"Name", Model}, {"NameResolved", Resolved},
                    {"Position", {{"X", Rec.Position[0]}, {"Y", Rec.Position[1]}, {"Z", Rec.Position[2]}}},
                    {"RotationDegrees", {{"X", E[0]}, {"Y", E[1]}, {"Z", E[2]}}},
                    {"RotationQuaternion", {{"X", Rec.Quat[0]}, {"Y", Rec.Quat[1]}, {"Z", Rec.Quat[2]}, {"W", Rec.Quat[3]}}},
                    {"ModelScale", {{"X", Rec.Scale}, {"Y", Rec.Scale}, {"Z", Rec.Scale}}},
                    {"BoundsMin", {{"X", RF32(T+32)}, {"Y", RF32(T+36)}, {"Z", RF32(T+40)}}},
                    {"BoundsMax", {{"X", RF32(T+44)}, {"Y", RF32(T+48)}, {"Z", RF32(T+52)}}},
                    {"RecordSlot", Packaged ? json(nullptr) : json(uint64_t(L.Start) + I)},
                    {"PlacementSource", Packaged ? "local_package" : "live"}, {"District", District},
                    {"ReferenceIndex", Index}, {"ReferenceFlagsRaw", Word & 0x80000000u},
                    {"SplineInstanceIndex", RU32(R+40)==0xFFFFFFFF ? json(nullptr) : json(RU32(R+40))},
                    {"RequiresSplineDeformation", RU32(R+40)!=0xFFFFFFFF}};
                if (Packaged) Row["PackageRecordSlot"] = uint64_t(L.Start) + I;
                Models.push_back(std::move(Row));
            }
            Districts.push_back(DR);
        }
        const bool RangesValid = CWDistrictPayload::Contiguous(Ranges);
        const bool FinalTableStable = C.VerifySpan(TableAddress, Table, "typed/district_table.bin");
        Complete = Complete && RangesValid && FinalTableStable;
        Result["global_ranges_contiguous"] = RangesValid;
        Result["district_table_final_readback_unchanged"] = FinalTableStable;
        Result["recovered_package_districts"] = Recovered; Result["unresolved_districts"] = Missing;
        Result["limitations"] = {
            "Placements include source proxy models; runtime visibility and proxy replacement rules are not decoded.",
            "Package and live reference flags may differ; preserve PlacementSource when interpreting flags.",
            "Spline indices are retained; spline control data is not included in this placement export."};

        json Unique = json::array();
        for (const auto& U : Uses)
            Unique.push_back({{"Name", U.first}, {"InstanceCount", U.second},
                {"NameResolved", U.first.rfind("xmodel_", 0) != 0}});
        Result["status"] = "decoded_district_partitions";
        Result["districts"] = Districts; Result["StaticModels"] = Models;
        Result["UniqueModels"] = Unique; Result["decoded_instances"] = Decoded;
        Result["unique_models"] = Unique.size(); Result["unresolved_model_names"] = Unresolved;
        Result["complete"] = Complete; Result["readback_unchanged"] = Recovered ? json(nullptr) : json(Complete);
        const auto Text = Result.dump(2);
        const bool Saved = C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Text.data()), Text.size());
        C.Report["district_static_models"] = {{"located", Decoded > 0}, {"file", "static_models.json"},
            {"saved", Saved}, {"instances", Decoded}, {"unique_models", Unique.size()},
            {"unresolved_model_names", Unresolved}, {"complete", Complete}, {"districts", Districts.size()},
            {"recovered_package_districts", Recovered}, {"unresolved_districts", Missing}};
    }

    // Shape test for the parallel instance -> model id array: exactly one u32
    // per instance, and far fewer distinct values than entries (a map holds
    // thousands of instances of a couple of thousand models). This measures
    // candidates; it does not decide which one is the id array.
    struct IdFit { uint32_t Entries = 0, Distinct = 0, Max = 0, Zeros = 0; bool Shaped = false; };

    inline IdFit MeasureIdArray(uint64_t Address, uint64_t Entries)
    {
        IdFit F; F.Entries = uint32_t(Entries);
        if (!Entries || Entries > 4000000ull) return F;
        const auto B = ReadBytes(Address, Entries * 4);
        if (B.size() != Entries * 4) return F;
        std::set<uint32_t> Seen;
        for (uint64_t I = 0; I < Entries; ++I)
        {
            const auto V = RU32(B.data() + size_t(I) * 4);
            if (!V) ++F.Zeros;
            if (V > F.Max) F.Max = V;
            if (Seen.size() < 200000) Seen.insert(V);
        }
        F.Distinct = uint32_t(Seen.size());
        F.Shaped = F.Distinct > 1 && F.Distinct * 4 < uint32_t(Entries);
        return F;
    }

    inline void Capture(TerrainResearch::Capture& C, uint32_t Pool,
        const std::vector<uint8_t>& Header)
    {
        if (Pool == 0xAB) { CaptureDistricts(C, Pool, Header); return; }
        if (Pool != 0x1B || Header.size() < 64) return;

        json Result = {{"schema", "cw-gfxmap-static-models-v1"}, {"source_pool", Pool},
            {"source_name_hash", Hex(RU64(Header.data()))},
            {"record_stride", RecordStride},
            {"layout_status", "64-byte placement record; offsets checked against an independent C2M export of the same live map"},
            {"field_offsets", {{"bounds_a", OffBoundsA}, {"quaternion_xyzw", OffQuat},
                {"position", OffPosition}, {"uniform_scale", OffScale}, {"bounds_b", OffBoundsB}}},
            {"model_identity", "unresolved; this record holds no model reference and the parallel id array is not yet identified"},
            {"euler_convention", "ZYX intrinsic, degrees; X=roll, Y=pitch, Z=yaw"}};

        const auto Name = MapName(Header);
        if (!Name.empty()) Result["map_name"] = Name;

        // Locate the instance array by scanning adjacent (count, pointer) words
        // and keeping the widest array whose records actually decode.
        uint64_t BestAddress = 0, BestSpan = 0;
        uint32_t BestGood = 0, BestOffset = 0; Fit BestFit;
        json Candidates = json::array();
        for (size_t Off = 0; Off + 16 <= Header.size(); Off += 8)
        {
            const auto Count64 = RU64(Header.data() + Off);
            const auto Address = RU64(Header.data() + Off + 8);
            if (Count64 == 0 || Count64 > 2000000ull || !Pointer(Address)) continue;
            const uint64_t Span = Count64 * RecordStride;
            if (Span > TerrainResearch::Capture::SpanLimit) continue;
            const auto F = FitArray(Address, Span);
            const bool Accepted = F.Good >= 16 && FitPercent(F) >= 90;
            // Every counted pointer considered is recorded, accepted or not, so
            // a build that moves the array leaves a diagnosable trail.
            Candidates.push_back({{"header_offset", Off}, {"header_count", Count64},
                {"address", Hex(Address)}, {"record_alignment", F.Alignment},
                {"sampled_valid", F.Good}, {"sampled_invalid", F.Bad},
                {"sampled_cleared", F.Empty}, {"sample_valid_percent", FitPercent(F)},
                {"accepted", Accepted}});
            if (!Accepted) continue;
            if (F.Good > BestGood)
            {
                BestGood = F.Good; BestAddress = Address; BestSpan = Span;
                BestOffset = uint32_t(Off); BestFit = F;
            }
        }
        Result["array_candidates"] = Candidates;

        if (!BestGood)
        {
            Result["located"] = false;
            Result["complete"] = false;
            Result["unresolved"] = "no counted array in the gfx_map header decoded as placements";
            const auto Miss = Result.dump(2);
            C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Miss.data()), Miss.size());
            C.Report["gfx_map_static_models"] = {{"located", false}};
            return;
        }

        const auto Anchor = FindAnchor(BestAddress, BestSpan, BestFit.Alignment);
        if (!Anchor)
        {
            Result["located"] = false;
            Result["complete"] = false;
            Result["unresolved"] = "no decoding record found inside the best-fitting span";
            const auto Miss = Result.dump(2);
            C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Miss.data()), Miss.size());
            C.Report["gfx_map_static_models"] = {{"located", false}};
            return;
        }
        // A short run means the record walk does not yet model how this array is
        // laid out. Retain a bounded window around the anchor so the layout can
        // be worked out offline instead of guessed at from a failed export.
        const auto Diagnostic = [&](const char* Why)
        {
            constexpr uint64_t Before = 6ull * 1024 * 1024, After = 2ull * 1024 * 1024;
            const uint64_t From = Anchor > Before ? Anchor - Before : 0;
            if (!Pointer(From)) return;
            C.Span(From, Before + After, "typed/world_window.bin",
                "diagnostic window around a decoding placement record; layout unresolved",
                false, "resident_scene");
            Result["diagnostic_window"] = {{"file", "typed/world_window.bin"},
                {"address", Hex(From)}, {"bytes", Before + After}, {"reason", Why}};
        };

        const auto Walked = ExpandRun(Anchor, 8ull * 1024 * 1024);
        if (Walked.Slots < 4096) Diagnostic("walked run shorter than the placement count the map is expected to hold");
        const uint64_t ArrayAddress = Walked.Base;
        const uint64_t Slots = Walked.Slots;
        Result["located"] = true;
        Result["header_offset"] = BestOffset;
        Result["header_pointer"] = Hex(BestAddress);
        Result["header_count"] = BestSpan / RecordStride;
        Result["record_alignment"] = BestFit.Alignment;
        Result["anchor_address"] = Hex(Anchor);
        Result["array_address"] = Hex(ArrayAddress);
        Result["record_slots"] = Slots;
        Result["extent_source"] = "walked outward from a decoding record; the header's counted pointers do not bound this array";
        Result["sample_valid_percent"] = FitPercent(BestFit);
        Result["sampled_cleared"] = BestFit.Empty;

        const auto Bytes = Slots * RecordStride;
        if (!Slots || Bytes > TerrainResearch::Capture::SpanLimit)
        {
            Result["located"] = false;
            Result["complete"] = false;
            Result["unresolved"] = "walked run was empty or larger than the span limit";
            const auto Miss = Result.dump(2);
            C.Write("static_models.json", reinterpret_cast<const uint8_t*>(Miss.data()), Miss.size());
            C.Report["gfx_map_static_models"] = {{"located", false}};
            return;
        }
        const auto Raw = C.Span(ArrayAddress, Bytes, "typed/static_model_instances.bin",
            "counted placement array; raw bytes authoritative, decoded fields recorded alongside",
            false, "resident_scene");
        bool Complete = Raw.size() == Bytes;

        std::map<uint64_t, std::string> NameCache;
        std::map<std::string, uint32_t> Uses;
        json Models = json::array();
        uint32_t Implausible = 0, Cleared = 0;
        const auto Records = uint32_t(Raw.size() / RecordStride);
        for (uint32_t I = 0; I < Records; ++I)
        {
            const auto* At = Raw.data() + size_t(I) * RecordStride;
            // Cleared slots are ordinary spare capacity, not a decode failure.
            if (ZeroRecord(At)) { ++Cleared; continue; }
            const auto Rec = ReadRecord(At);
            if (!Plausible(Rec)) { ++Implausible; continue; }
            const std::string ModelNameText = "xmodel_unresolved";
            Uses[ModelNameText]++;
            double E[3]; EulerDegrees(Rec.Quat, E);
            Models.push_back({
                {"Name", ModelNameText},
                {"Position", {{"X", Rec.Position[0]}, {"Y", Rec.Position[1]}, {"Z", Rec.Position[2]}}},
                {"RotationDegrees", {{"X", E[0]}, {"Y", E[1]}, {"Z", E[2]}}},
                {"RotationQuaternion", {{"X", Rec.Quat[0]}, {"Y", Rec.Quat[1]},
                    {"Z", Rec.Quat[2]}, {"W", Rec.Quat[3]}}},
                {"ModelScale", {{"X", Rec.Scale}, {"Y", Rec.Scale}, {"Z", Rec.Scale}}},
                {"RecordSlot", I}, {"NameResolved", false}});
        }
        if (Implausible) Complete = false;

        json Unique = json::array();
        uint32_t Unresolved = 0;
        for (const auto& U : Uses)
        {
            const bool Resolved = U.first.rfind("xmodel_", 0) != 0;
            if (!Resolved) ++Unresolved;
            Unique.push_back({{"Name", U.first}, {"InstanceCount", U.second}, {"NameResolved", Resolved}});
        }

        const auto Stable = C.VerifySpan(ArrayAddress, Raw, "typed/static_model_instances.bin");
        Result["decoded_instances"] = Models.size();
        Result["cleared_slots"] = Cleared;
        Result["implausible_records"] = Implausible;
        Result["unique_models"] = Unique.size();
        Result["unresolved_model_names"] = Unresolved;
        Result["readback_unchanged"] = Stable;
        Result["transform_read_complete"] = Complete && Stable;
        Result["complete"] = false;
        Result["model_identity_status"] = "unresolved";
        Result["array_extent_status"] = "heuristic_candidate_run";
        Result["completeness_scope"] = "counted array read, per-record plausibility and second-read equality; not proof of engine semantics";

        json Placements = Result;
        Placements["StaticModels"] = Models;
        const auto PlacementText = Placements.dump(2);
        const bool SavedPlacements = C.Write("static_models.json",
            reinterpret_cast<const uint8_t*>(PlacementText.data()), PlacementText.size());

        json UniqueDoc = {{"schema", "cw-gfxmap-unique-models-v1"}, {"source_pool", Pool},
            {"instance_count", Models.size()}, {"unique_models", Unique.size()},
            {"unresolved_model_names", Unresolved}, {"UniqueModels", Unique}};
        if (!Name.empty()) UniqueDoc["map_name"] = Name;
        const auto UniqueText = UniqueDoc.dump(2);
        const bool SavedUnique = C.Write("unique_models.json",
            reinterpret_cast<const uint8_t*>(UniqueText.data()), UniqueText.size());

        C.Report["gfx_map_static_models"] = {{"located", true}, {"file", "static_models.json"},
            {"unique_models_file", "unique_models.json"},
            {"saved", SavedPlacements && SavedUnique}, {"instances", Models.size()},
            {"unique_models", Unique.size()}, {"unresolved_model_names", Unresolved},
            {"complete", false}, {"transform_read_complete", Complete && Stable}, {"readback_unchanged", Stable}};
    }
}
