#pragma once
#include <algorithm>
#include <map>
#include <set>
#include <vector>
#include "TerrainResearchCapture.h"
#include "CWClipModelExport.h"
#include "CWCollisionWorldCapture.h"

// Collision-family pools store their arrays back-to-back in one allocation, so
// the distance between two consecutive header pointers is the byte length of
// the earlier array. That lets every array be captured whole without first
// identifying which header word is its count -- the counts in clip_map do not
// sit adjacent to their pointers the way the trigger pool's do.
//
// Past the header the data is a chain of fixed-stride record blocks that
// reference each other, so the same two steps repeat: measure a block record
// stride, then follow each offset within that stride where most records hold a
// pointer. Nothing here claims a field meaning; it records where each block is,
// how long it is, and how that length was bounded.
namespace CWClipMapCapture
{
    using TerrainResearch::json;
    using TerrainResearch::Hex;
    using TerrainResearch::Pointer;

    constexpr uint64_t ArrayLimit = 48ull * 1024 * 1024;
    constexpr uint64_t PoolLimit = 1024ull * 1024 * 1024;
    constexpr uint64_t FollowBytes = 12ull * 1024 * 1024;   // keep for a further hop
    constexpr uint32_t MaxDepth = 2;
    // Targets further apart than this are treated as separate allocations.
    constexpr uint64_t ClusterGap = 256ull * 1024;
    constexpr size_t ClusterLimit = 48;
    // Self-sized allocations: a per-block ceiling and a total for the pass.
    constexpr uint64_t SizedLimit = 8ull * 1024 * 1024;
    constexpr uint64_t SizedTotal = 768ull * 1024 * 1024;

    inline bool Named(uint32_t Pool, std::string& Out)
    {
        switch (Pool)
        {
        case 0x07: Out = "xcollision"; return true;
        case 0x17: Out = "col_map";    return true;
        case 0x18: Out = "clip_map";   return true;
        case 0x19: Out = "com_map";    return true;
        case 0x1A: Out = "game_map";   return true;
        default: return false;
        }
    }

    inline uint64_t RegionRemaining(uint64_t Address)
    {
        MEMORY_BASIC_INFORMATION M{};
        if (!Pointer(Address)) return 0;
        if (!VirtualQueryEx(CoDAssets::GameInstance->GetCurrentProcess(),
            reinterpret_cast<const void*>(Address), &M, sizeof(M))) return 0;
        if (M.State != MEM_COMMIT) return 0;
        const auto Base = reinterpret_cast<uint64_t>(M.BaseAddress);
        if (Base > Address || M.RegionSize > UINT64_MAX - Base) return 0;
        const auto End = Base + M.RegionSize;
        return End > Address ? End - Address : 0;
    }

    inline uint64_t Word(const std::vector<uint8_t>& B, size_t O)
    {
        uint64_t V; memcpy(&V, B.data() + O, 8); return V;
    }

    // A block of fixed-stride records repeats distinctive words at a constant
    // spacing: a shared tag, a constant mask, a null field. The most common
    // spacing between equal 8-byte words is that stride. Words that occur too
    // often are mostly padding and carry no spacing information, so they are
    // left out of the vote.
    inline uint64_t DetectStride(const std::vector<uint8_t>& B)
    {
        if (B.size() < 256) return 0;
        // A pointer table has no repeated words at all -- every entry is a
        // distinct address -- so the spacing vote below finds nothing. Recognise
        // it directly: stride 8, one field at offset 0.
        if (B.size() % 8 == 0)
        {
            std::set<uint64_t> Distinct;
            bool Table = true;
            for (size_t O = 0; O + 8 <= B.size() && Table; O += 8)
            {
                const auto V = Word(B, O);
                if (!Pointer(V) || !Distinct.insert(V).second) Table = false;
            }
            if (Table && Distinct.size() >= 8) return 8;
        }
        std::map<uint64_t, std::vector<size_t>> Where;
        const size_t Scan = std::min<size_t>(B.size(), 1u << 20);
        for (size_t O = 0; O + 8 <= Scan; O += 8)
        {
            const auto V = Word(B, O);
            if (V == 0) continue;
            Where[V].push_back(O);
        }
        std::map<uint64_t, uint64_t> Votes;
        for (const auto& Entry : Where)
        {
            const auto& L = Entry.second;
            if (L.size() < 4) continue;
            for (size_t I = 0; I + 1 < L.size(); ++I)
            {
                const uint64_t D = L[I + 1] - L[I];
                if (D >= 16 && D <= 4096 && D % 8 == 0) ++Votes[D];
            }
        }
        uint64_t Best = 0, BestVotes = 0;
        for (const auto& V : Votes) if (V.second > BestVotes) { BestVotes = V.second; Best = V.first; }
        // A stride only means something if the constant-spaced words it explains
        // cover a real share of the part of the block that was actually scanned.
        return BestVotes >= 8 && BestVotes * Best >= Scan / 4 ? Best : 0;
    }

    // The CLIP_MAP model table is now counted and verified. Do not walk
    // arbitrary words in geometry allocations to rediscover this known edge.
    inline void CaptureCountedClipMap(TerrainResearch::Capture& C, const std::vector<uint8_t>& Header)
    {
        json Result = {{"schema", "cw-collision-counted-table-v1"}, {"source_pool", 0x18},
            {"status", "incomplete"}, {"method", "CLIP_MAP +0x40 pointer table, +0x1a8 count; exact 96-byte asset records"}};
        json Models=json::array(), Blocks=json::array();
        bool Stable=true;
        try
        {
            if(Header.size()!=472) throw std::runtime_error("Unsupported CLIP_MAP header size");
            const auto Count=CWClipModelExport::U32(Header.data()+0x1a8);
            const auto At=Word(Header,0x40);
            if(!Count || Count>65536 || !Pointer(At)) throw std::runtime_error("Invalid collision asset table");
            const auto Table=C.Span(At,Count*8ull,"typed/clip_map/model_pointers.bin","counted collision asset table",false,"structure");
            if(Table.size()!=Count*8ull) throw std::runtime_error("Incomplete collision asset table");
            std::set<uint64_t> Seen;
            for(uint32_t I=0;I<Count;++I)
            {
                const auto P=Word(Table,I*8ull);
                if(!Pointer(P) || !Seen.insert(P).second) throw std::runtime_error("Invalid/duplicate collision asset pointer");
                const auto File="typed/clip_map/records/"+std::to_string(I)+".bin";
                const auto R=C.Span(P,96,File,"directly owned collision asset record",false,"structure");
                if(R.size()!=96 || !CWClipModelExport::Ordered(R.data())) throw std::runtime_error("Invalid collision asset record");
                CWClipModelExport::Collect(C,"clip_map",Models,Blocks,P,R,std::vector<uint64_t>{P});
                if(!C.VerifySpan(P,R,File)) Stable=false;
            }
            if(!C.VerifySpan(At,Table,"typed/clip_map/model_pointers.bin")) Stable=false;
            if(Models.size()!=Count) throw std::runtime_error("Incomplete collision asset inventory");
            CWClipModelExport::Write(C,"clip_map",Models,Blocks);
            CWCollisionWorldCapture::Capture(C,Header,Models);
            Result["status"]=Stable?"captured":"changed";
            Result["model_count"]=Count;
        }
        catch(const std::exception& E) {Stable=false;Result["status"]="failed";Result["error"]=E.what();}
        Result["readback_unchanged"]=Stable;
        const auto Text=Result.dump(2);
        const bool Saved=C.Write("clip_map_arrays.json",reinterpret_cast<const uint8_t*>(Text.data()),Text.size());
        C.Report["collision_arrays"]={{"file","clip_map_arrays.json"},{"saved",Saved},{"readback_unchanged",Stable},
            {"method","counted collision asset table"},{"status",Result["status"]}};
    }

    inline void Capture(TerrainResearch::Capture& C, uint32_t Pool,
        const std::vector<uint8_t>& Header)
    {
        if(Pool==0x18) {CaptureCountedClipMap(C,Header);return;}
        std::string Name;
        if (!Named(Pool, Name) || Header.size() < 16) return;

        json Result = {{"schema", "cw-collision-arrays-v2"}, {"source_pool", Pool},
            {"pool_name_candidate", Name},
            {"source_name_hash", Hex(TerrainResearch::U64(Header, 0))},
            {"header_bytes", Header.size()},
            {"sizing_method", "header arrays: distance to the next higher header pointer; deeper blocks: the span covering every target of one pointer field, clamped to the committed region and a fixed ceiling"},
            {"arrays", json::array()}, {"blocks", json::array()}};

        uint64_t Spent = 0;
        std::set<uint64_t> Seen;
        struct Block { uint64_t Address; std::vector<uint8_t> Bytes; uint32_t Depth; };
        std::vector<Block> Queue;
        std::vector<std::pair<uint64_t, std::vector<uint8_t>>> Verify;
        // Which addresses actually aimed into each captured run. A covering
        // span reaches past the records the table names, so anything derived
        // from a block must use these rather than every slot in the span.
        std::vector<std::pair<uint64_t, std::vector<uint64_t>>> Aimed;
        json ClipModels = json::array(), ClipBlocks = json::array();

        const auto Take = [&](uint64_t Address, uint64_t Size, const std::string& File,
            const std::string& Meaning, uint32_t Depth, json& Into) -> bool
        {
            // Past this depth a covering span is a guess over scattered
            // allocations rather than one buffer, and the read budget is better
            // spent on the self-sized blocks that can be bounded exactly.
            if (Depth > MaxDepth)
            { Into["status"] = "skipped_beyond_span_depth"; return false; }
            if (!Size || Size > ArrayLimit || Spent + Size > PoolLimit)
            { Into["status"] = "skipped_out_of_budget"; return false; }
            if (RegionRemaining(Address) < Size)
            { Into["status"] = "skipped_outside_region"; return false; }
            const auto B = C.Span(Address, Size, File, Meaning, false, "resident_scene");
            Into["file"] = File;
            Into["captured_bytes"] = B.size();
            Into["status"] = B.size() == Size ? "captured" : "short_read";
            Spent += B.size();
            if (B.empty()) return false;
            if (B.size() <= 8ull * 1024 * 1024) Verify.emplace_back(Address, B);
            // Walk a block at the span-depth limit too: its own covering spans
            // are refused above, but its self-sized fields still need reading.
            if (Depth <= MaxDepth && B.size() <= FollowBytes) Queue.push_back({Address, B, Depth});
            return true;
        };

        // Header arrays, sized by the spacing of the header own pointers.
        std::vector<std::pair<size_t, uint64_t>> Slots;
        for (size_t O = 0; O + 8 <= Header.size(); O += 8)
        {
            uint64_t V; memcpy(&V, Header.data() + O, 8);
            if (!Pointer(V) || RegionRemaining(V) == 0) continue;
            if (!Seen.insert(V).second) continue;
            Slots.push_back({O, V});
        }
        std::vector<uint64_t> Sorted;
        for (const auto& S : Slots) Sorted.push_back(S.second);
        std::sort(Sorted.begin(), Sorted.end());
        for (const auto& S : Slots)
        {
            const auto Room = RegionRemaining(S.second);
            const auto Next = std::upper_bound(Sorted.begin(), Sorted.end(), S.second);
            const uint64_t Gap = Next == Sorted.end() ? UINT64_MAX : *Next - S.second;
            // A gap-bounded length is exact. Anything bounded by the region end
            // is an over-read whose tail belongs to something else, so keep it
            // small rather than spending the walk budget on a guess.
            const uint64_t Ceiling = Gap <= Room ? ArrayLimit : 4ull * 1024 * 1024;
            const uint64_t Size = std::min<uint64_t>({Gap, Room, Ceiling});
            json A = {{"header_offset", S.first}, {"address", Hex(S.second)},
                {"region_remaining", Room},
                {"gap_to_next_pointer", Gap == UINT64_MAX ? 0 : Gap},
                {"captured_bytes", 0}, {"exactly_sized", Size == Gap},
                {"size_bounded_by", Size == Gap ? "next_pointer"
                    : (Size == Room ? "region_end" : "over_read_ceiling")}};
            Take(S.second, Size, "typed/" + Name + "/array_" + Hex(S.second) + ".bin",
                "contiguous array from a collision-family header; length derived from pointer spacing, stride and meaning unresolved",
                0, A);
            Result["arrays"].push_back(A);
        }

        // Some pointer fields do not aim into one shared buffer at all: each
        // target is its own allocation that begins with its own byte size. That
        // is recognisable -- the starts are aligned and the leading word is a
        // plausible length -- and it is the only way to bound these reads, since
        // nothing about their spacing says where one ends.
        json SizedBlocks = json::array();
        uint64_t SizedBytes = 0;
        const auto Sized = [&](uint64_t Field, const std::vector<uint64_t>& T, json& Into) -> bool
        {
            if (T.size() < 8) return false;
            // Qualify on a sample before issuing one read per target.
            uint64_t Looks = 0, Looked = 0;
            const size_t Step = std::max<size_t>(1, T.size() / 64);
            for (size_t I = 0; I < T.size(); I += Step)
            {
                const auto H = C.Span(T[I], 8, "", "size probe", false, "resident_scene");
                ++Looked;
                if (H.size() < 8) continue;
                uint32_t Length; memcpy(&Length, H.data(), 4);
                if (Length >= 16 && Length <= SizedLimit && T[I] % 256 == 0) ++Looks;
            }
            // The sample only rules out fields that are clearly not this shape.
            // A field mixes self-sized allocations with unrelated pointers -- a
            // covering span over it reaches thousands of records the owning
            // table never names -- so the qualifying share can be small and each
            // target is still checked on its own below.
            if (!Looked || Looks * 20 < Looked) return false;

            uint64_t Took = 0, Bytes = 0;
            for (const uint64_t P : T)
            {
                if (SizedBytes + Bytes > SizedTotal) break;
                const auto H = C.Span(P, 8, "", "size header", false, "resident_scene");
                if (H.size() < 8) continue;
                uint32_t Length; memcpy(&Length, H.data(), 4);
                if (Length < 16 || Length > SizedLimit) continue;
                if (RegionRemaining(P) < Length) continue;
                const auto B = C.Span(P, Length, "typed/" + Name + "/sized/" + Hex(P) + ".bin",
                    "one self-sized allocation; its own leading u32 is the byte length, so this is exact rather than a covering span",
                    false, "resident_scene");
                if (B.size() != Length) continue;
                ++Took; Bytes += B.size();
                SizedBlocks.push_back({{"address", Hex(P)}, {"bytes", B.size()}});
            }
            SizedBytes += Bytes;
            Spent += Bytes;
            Into["self_sized_targets"] = Took;
            Into["self_sized_bytes"] = Bytes;
            Into["field_offset_of_sized"] = Field;
            return Took > 0;
        };

        // Breadth-first over the record blocks those arrays reference.
        for (size_t Q = 0; Q < Queue.size(); ++Q)
        {
            const auto Address = Queue[Q].Address;
            const auto Depth = Queue[Q].Depth;
            const auto Bytes = Queue[Q].Bytes;          // copy: Queue may grow
            const uint64_t Stride = DetectStride(Bytes);
            if (Stride == 96)
            {
                std::vector<uint64_t> Order;
                for (const auto& A : Aimed) if (A.first == Address) Order = A.second;
                CWClipModelExport::Collect(C, Name, ClipModels, ClipBlocks, Address, Bytes, Order);
            }
            json Info = {{"address", Hex(Address)}, {"bytes", Bytes.size()},
                {"depth", Depth}, {"detected_stride", Stride}, {"fields", json::array()}};
            if (!Stride)
            {
                Info["status"] = "no_repeating_stride";
                Result["blocks"].push_back(Info);
                continue;
            }
            Info["status"] = "walked";

            // Every pointer field of one record tends to aim into the same
            // allocation -- a section table, where the gaps between the pointers
            // are the section sizes. Capturing per field would read that
            // allocation once per field, so collect the targets of all fields
            // first and cover their union instead.
            std::vector<uint64_t> All;
            for (uint64_t Field = 0; Field + 8 <= Stride; Field += 8)
            {
                std::vector<uint64_t> T;
                uint64_t Records = 0;
                for (size_t O = size_t(Field); O + 8 <= Bytes.size(); O += size_t(Stride))
                {
                    ++Records;
                    const auto V = Word(Bytes, O);
                    if (Pointer(V) && RegionRemaining(V)) T.push_back(V);
                }
                // A real field is in nearly every record. A weaker hit rate is
                // stale words inside a block whose stride was guessed wrong, and
                // following those spends the budget on unrelated memory.
                if (Records < 4 || T.size() * 4 < Records * 3) continue;
                Info["fields"].push_back({{"field_offset", Field},
                    {"records", Records}, {"pointer_records", T.size()}});
                std::sort(T.begin(), T.end());
                T.erase(std::unique(T.begin(), T.end()), T.end());
                All.insert(All.end(), T.begin(), T.end());
            }
            std::sort(All.begin(), All.end());
            All.erase(std::unique(All.begin(), All.end()), All.end());

            json Runs = json::array();
            uint64_t Taken = 0;
            const uint64_t Tail = std::max<uint64_t>(Stride, 256);
            size_t Start = 0;
            for (size_t I = 0; I <= All.size() && Start < All.size(); ++I)
            {
                const bool End = I == All.size();
                if (!End && (I == Start || All[I] - All[I - 1] <= ClusterGap)) continue;
                const uint64_t Low = All[Start], High = All[I - 1];
                const size_t Members = I - Start, Start0 = Start;
                Start = I;
                if (Runs.size() >= ClusterLimit) break;
                if (Seen.insert(Low).second)
                {
                    json R = {{"target_low", Hex(Low)}, {"target_high", Hex(High)},
                        {"targets", Members}, {"covering_bytes", High - Low + Tail},
                        {"captured_bytes", 0}};
                    if (Take(Low, High - Low + Tail,
                        "typed/" + Name + "/block_" + Hex(Low) + ".bin",
                        "span covering one contiguous run of the addresses a record block points at",
                        Depth + 1, R))
                    {
                        Taken += R["captured_bytes"].get<uint64_t>();
                        Aimed.emplace_back(Low, std::vector<uint64_t>(
                            All.begin() + Start0, All.begin() + I));
                    }
                    Runs.push_back(R);
                }
                if (End) break;
            }
            Info["target_runs"] = Runs;
            Info["target_bytes"] = Taken;
            Result["blocks"].push_back(Info);
        }

        CWClipModelExport::Write(C, Name, ClipModels, ClipBlocks);
        if (Pool == 0x18) CWCollisionWorldCapture::Capture(C, Header, ClipModels);

        bool Stable = true;
        for (const auto& V : Verify)
            if (!C.VerifySpan(V.first, V.second, "typed/" + Name)) Stable = false;
        Result["readback_unchanged"] = Stable;
        Result["captured_bytes_total"] = Spent;
        Result["blocks_walked"] = Queue.size();
        Result["self_sized_blocks"] = SizedBlocks;
        Result["self_sized_bytes"] = SizedBytes;

        const auto Text = Result.dump(2);
        const bool Saved = C.Write(Name + "_arrays.json",
            reinterpret_cast<const uint8_t*>(Text.data()), Text.size());
        C.Report["collision_arrays"] = {{"file", Name + "_arrays.json"}, {"saved", Saved},
            {"pool_name_candidate", Name}, {"header_arrays", Slots.size()},
            {"blocks_walked", Queue.size()}, {"captured_bytes", Spent},
            {"self_sized_blocks", SizedBlocks.size()},
            {"self_sized_bytes", SizedBytes},
            {"readback_unchanged", Stable}};
    }
}
