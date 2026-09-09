#pragma once
#include <cmath>
#include <string>
#include <vector>
#include "TerrainResearchCapture.h"
#include "CWMapEntityExport.h"

// The collision-family walk turns up blocks of 96-byte records that carry a
// name hash, a local bounding box and pointers to per-model geometry. This
// renders the ones that hold together as a flat list, so a model's collision
// bounds can be read without re-walking the capture by hand.
//
// A record is only emitted when the shape test passes on the whole block: the
// box must be ordered and finite in every record. That keeps a block of
// unrelated 96-byte data from being printed as if it were a model list.
namespace CWClipModelExport
{
    using TerrainResearch::json;
    using TerrainResearch::Hex;
    using TerrainResearch::Pointer;

    constexpr uint64_t Stride = 96;
    constexpr uint64_t OffHash = 0x00, OffGeometryA = 0x08, OffGeometryB = 0x10;
    constexpr uint64_t OffExtra = 0x18, OffCount = 0x20, OffMins = 0x40;
    constexpr uint64_t OffMaxs = 0x4C, OffFlags = 0x58;

    inline float F32(const uint8_t* P) { float V; memcpy(&V, P, 4); return V; }
    inline uint32_t U32(const uint8_t* P) { uint32_t V; memcpy(&V, P, 4); return V; }
    inline uint64_t U64(const uint8_t* P) { uint64_t V; memcpy(&V, P, 8); return V; }

    inline bool Ordered(const uint8_t* R)
    {
        for (int A = 0; A < 3; ++A)
        {
            const float Lo = F32(R + OffMins + A * 4), Hi = F32(R + OffMaxs + A * 4);
            if (!std::isfinite(Lo) || !std::isfinite(Hi)) return false;
            if (!(Lo <= Hi) || std::fabs(Lo) > 1e6f || std::fabs(Hi) > 1e6f) return false;
        }
        return true;
    }

    // Records reached through the pointer table, in table order. The block is a
    // covering span, so a pointer that falls outside it has no record here.
    // One map's models arrive across several blocks, so records accumulate
    // into Models and Write puts out a single list at the end of the walk.
    // Each model reaches one payload allocation through its second geometry
    // pointer: a 56-byte descriptor whose +0x20 aims at a block that begins
    // with its own byte length. That length is the only thing that bounds the
    // read, so the payload is captured here rather than by spanning a guessed
    // range around it, and it is written per model so the two stay tied.
    constexpr uint64_t OffDescriptorPayload = 0x20, DescriptorBytes = 56;
    // Gold has a verified 10,957,800-byte brush allocation; retain a bounded
    // power-of-two ceiling and the existing total budget for all maps.
    constexpr uint64_t PayloadMax = 16ull * 1024 * 1024, PayloadTotal = 96ull * 1024 * 1024;
    // The payload's data region is not one array: entropy over a sliding window
    // breaks it into sections with different encodings, and the boundary moves
    // per model. Decoding it needs the section table, so the two descriptors are
    // emitted word by word here rather than read for one field. The first
    // geometry pointer reaches 88 bytes that have never been read at all.
    constexpr uint64_t GeometryABytes = 88;
    // A handful of models also get their descriptor pointers followed, enough to
    // tell a table of offsets from a pointer to one.
    constexpr uint64_t ProbeModels = 24, ProbeBytes = 256;

    inline json Words(const std::vector<uint8_t>& B)
    {
        json W = json::array();
        for (uint64_t O = 0; O + 8 <= B.size(); O += 8) W.push_back(Hex(U64(B.data() + O)));
        return W;
    }

    inline void Collect(TerrainResearch::Capture& C, const std::string& Pool,
        json& Models, json& Blocks, uint64_t BlockAddress,
        const std::vector<uint8_t>& Block, const std::vector<uint64_t>& Table)
    {
        if (Block.size() < Stride) return;

        uint64_t Total = 0, Good = 0;
        for (size_t O = 0; O + Stride <= Block.size(); O += Stride)
        {
            ++Total;
            if (Ordered(Block.data() + O) && U64(Block.data() + O + OffHash)) ++Good;
        }
        // Every record of a real model block passes; a coincidental block does not.
        if (!Total || Good * 20 < Total * 19) return;

        uint64_t Named = 0, Reached = 0, Missing = 0, Brushes = 0;
        uint64_t Payloads = 0, PayloadBytes = 0, NoPayload = 0;
        for (const uint64_t P : Table)
        {
            if (P < BlockAddress || P - BlockAddress + Stride > Block.size()) { ++Missing; continue; }
            const uint8_t* R = Block.data() + (P - BlockAddress);
            if (!Ordered(R)) { ++Missing; continue; }
            ++Reached;
            const auto Hash = U64(R + OffHash);
            const auto Name = CWMapEntityExport::ResolveHash(Hash);
            const bool Resolved = !Name.empty() && Name.find_first_not_of("0123456789ABCDEF") != std::string::npos;
            if (Resolved) ++Named;
            const auto Count = U32(R + OffCount);
            Brushes += Count;
            // Follow this model to its own payload, exactly sized.
            json Payload = {{"status", "absent"}};
            json DescB = {{"status", "absent"}}, DescA = {{"status", "absent"}};
            const bool Probe = Models.size() < ProbeModels;
            const auto Descriptor = U64(R + OffGeometryB);
            if (Pointer(Descriptor))
            {
                const auto D = C.Span(Descriptor, DescriptorBytes,
                    "typed/" + Pool + "/descriptors/" + Hex(Descriptor) + "_b.bin",
                    "payload descriptor; raw field meanings provisional", false, "resident_scene");
                DescB = {{"address", Hex(Descriptor)}, {"captured_bytes", D.size()},
                    {"status", D.size() == DescriptorBytes ? "captured" : "short_read"}};
                if (D.size() == DescriptorBytes)
                {
                    DescB["words"] = Words(D);
                    const auto At = U64(D.data() + OffDescriptorPayload);
                    Payload = {{"address", Hex(At)}, {"status", "unreadable"}};
                    if (Pointer(At))
                    {
                        const auto H = C.Span(At, 8,
                            "typed/" + Pool + "/descriptors/" + Hex(At) + "_prefix.bin",
                            "payload leading size field", false, "resident_scene");
                        uint32_t Leading = 0;
                        if (H.size() == 8) memcpy(&Leading, H.data(), 4);
                        // The descriptor's last word carries the allocation size in
                        // its low half, and it is the block's own leading u32 plus
                        // 256 in every one of this map's 1888 models. Reading only
                        // the leading value covers the 256-byte zero header and
                        // stops 256 bytes short of the end of the data, so the size
                        // is taken from the descriptor and the leading value is kept
                        // alongside it to show the two still agree.
                        const uint32_t Allocated = static_cast<uint32_t>(U64(D.data() + 0x30) & 0xFFFFFFFF);
                        const uint32_t Length = Allocated;
                        Payload["declared_bytes"] = Leading;
                        Payload["allocated_bytes"] = Allocated;
                        Payload["header_bytes"] = Allocated >= Leading ? Allocated - Leading : 0;
                        if (H.size() == 8 && Length >= 256 && Length <= PayloadMax &&
                            uint64_t(Leading) + 256 == Length &&
                            C.Report.value("collision_payload_bytes_charged", 0ull) + Length <= PayloadTotal)
                        {
                            C.Report["collision_payload_bytes_charged"] = C.Report.value("collision_payload_bytes_charged", 0ull) + Length;
                            const auto File = "typed/" + Pool + "/payload/" + Hex(Hash) + ".bin";
                            const auto B = C.Span(At, Length, File,
                                "candidate collision allocation; descriptor +0x30 low32 size agrees with leading u32 +256",
                                false, "resident_scene");
                            Payload["file"] = File;
                            Payload["captured_bytes"] = B.size();
                            Payload["status"] = B.size() == Length ? "captured" : "short_read";
                            if (B.size() == Length)
                            {
                                ++Payloads; PayloadBytes += B.size();
                                Payload["readback_unchanged"] = C.VerifySpan(At, B, File);
                            }
                        }
                        else Payload["status"] = "implausible_length";
                    }
                }
            }
            if (Payload.value("status", "") != "captured") ++NoPayload;

            // geometry_a: 88 bytes, never read before this pass.
            const auto Alt = U64(R + OffGeometryA);
            if (Pointer(Alt))
            {
                const auto A = C.Span(Alt, GeometryABytes,
                    "typed/" + Pool + "/descriptors/" + Hex(Alt) + "_a.bin",
                    "geometry_a descriptor; raw field meanings provisional", false, "resident_scene");
                DescA = {{"address", Hex(Alt)}, {"captured_bytes", A.size()},
                    {"status", A.size() == GeometryABytes ? "captured" : "short_read"}};
                if (A.size() == GeometryABytes)
                {
                    DescA["words"] = Words(A);
                    // Only a few models: follow each pointer word one hop, so a
                    // word that is an offset can be told from one that is not.
                    if (Probe)
                    {
                        json Hops = json::array();
                        for (uint64_t O = 0; O + 8 <= GeometryABytes; O += 8)
                        {
                            const auto Q = U64(A.data() + O);
                            if (!Pointer(Q)) continue;
                            const auto File = "typed/" + Pool + "/geometry_a/" + Hex(Hash) + "_" + Hex(O) + ".bin";
                            const auto B = C.Span(Q, ProbeBytes, File, "bytes at a geometry_a pointer word",
                                false, "speculative");
                            Hops.push_back({{"word", O}, {"address", Hex(Q)},
                                {"file", File}, {"captured_bytes", B.size()}});
                        }
                        DescA["pointer_hops"] = Hops;
                    }
                }
            }

            Models.push_back({
                {"name", Name}, {"name_hash", Hex(Hash)}, {"name_resolved", Resolved},
                {"record_address", Hex(P)},
                {"mins", {F32(R + OffMins), F32(R + OffMins + 4), F32(R + OffMins + 8)}},
                {"maxs", {F32(R + OffMaxs), F32(R + OffMaxs + 4), F32(R + OffMaxs + 8)}},
                {"count_0x20", Count}, {"flags_0x58", U32(R + OffFlags)},
                {"geometry_a", Hex(U64(R + OffGeometryA))},
                {"geometry_b", Hex(U64(R + OffGeometryB))},
                {"geometry_extra", Hex(U64(R + OffExtra))},
                {"descriptor_a", DescA}, {"descriptor_b", DescB},
                {"payload", Payload}});
        }
        Blocks.push_back({{"block_address", Hex(BlockAddress)},
            {"records_in_block", Total}, {"records_passing_shape_test", Good},
            {"table_entries", Table.size()}, {"records_reached", Reached},
            {"table_entries_outside_block", Missing},
            {"names_resolved", Named}, {"count_0x20_total", Brushes},
            {"payloads_captured", Payloads}, {"payload_bytes", PayloadBytes},
            {"models_without_payload", NoPayload}});
    }

    inline void Write(TerrainResearch::Capture& C, const std::string& Pool,
        const json& Models, const json& Blocks)
    {
        if (Models.empty()) return;
        uint64_t Named = 0, Parts = 0;
        bool PayloadsVerified = true;
        for (const auto& M : Models)
        {
            if (M.value("name_resolved", false)) ++Named;
            Parts += M.value("count_0x20", 0u);
            const auto& Payload = M.at("payload");
            if (Payload.value("status", "") != "captured" || !Payload.value("readback_unchanged", false)) PayloadsVerified = false;
        }
        json Document = {{"schema", "cw-clip-models-v1"}, {"source_pool", Pool},
            {"record_stride", Stride}, {"model_count", Models.size()},
            {"names_resolved", Named}, {"count_0x20_total", Parts},
            {"source_blocks", Blocks},
            {"bounds_status", "model-local; these records carry no world placement"},
            {"geometry_status", "geometry_a/geometry_b/geometry_extra are the per-model references the walk followed"},
            {"payload_status", "candidate allocation reached through descriptor_b +0x20; size from descriptor_b +0x30 low32, requiring leading u32 +256 agreement; per-payload readback recorded; contents not decoded"},
            {"descriptor_status", "descriptor_b is the 56 bytes behind geometry_b, descriptor_a the 88 behind geometry_a; both are emitted word by word because the payload's data region is several sections and the section table has not been located. Words are raw, no field meaning is claimed"},
            {"field_evidence", {
                {"+0x00", "name hash; FNV-1a 64 masked to 63 bits, matched against independently named assets"},
                {"+0x20", "a small per-model count, 1..973, summing to 43266 for this map. Tested against an independent export and it is NOT the surface, triangle or vertex count, and NOT the length of the 56-byte descriptor chain at +0x10. Meaning unresolved."},
                {"+0x40", "float3 mins, ordered against maxs in every record of the block"},
                {"+0x4C", "float3 maxs"},
                {"+0x58", "small enumerated value, mostly 0/1/16/17; meaning unresolved"}}},
            {"models", Models}};

        const auto Text = Document.dump(2);
        const auto File = Pool + "_models.json";
        const bool Saved = C.Write(File, reinterpret_cast<const uint8_t*>(Text.data()), Text.size());
        C.Report["clip_models"] = {{"file", File}, {"saved", Saved},
            {"models", Models.size()}, {"names_resolved", Named}, {"all_payloads_verified", PayloadsVerified},
            {"count_0x20_total", Parts}};
    }
}
