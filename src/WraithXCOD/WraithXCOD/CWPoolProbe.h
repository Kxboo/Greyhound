#pragma once
#include <cstdint>
#include <cstring>
#include <vector>
#include <set>
#include <algorithm>

// Independent of game layouts and process access, for synthetic tests.
namespace CWPoolProbe
{
    // Pure planner: preserve every incoming edge even when payload reads deduplicate.
    struct Edge { uint64_t Parent, Address; uint32_t Offset, Depth; };
    struct Graph
    {
        static constexpr size_t NodeLimit = 512, EdgeLimit = 16384;
        static constexpr uint32_t DepthLimit = 2, PrefixBytes = 65536;
        std::vector<Edge> Edges;
        std::vector<std::pair<uint64_t, uint32_t>> Queue;
        std::set<uint64_t> Seen;
        bool NodeLimitReached = false, EdgeLimitReached = false;
        void Scan(const std::vector<uint8_t>& Bytes, uint64_t Parent, uint32_t Depth, uint32_t Start = 0)
        {
            if (Depth > DepthLimit) return;
            for (size_t O = Start; O + 8 <= Bytes.size(); O += 8)
            {
                uint64_t P = 0; memcpy(&P, Bytes.data() + O, 8);
                if (P < 0x10000 || P >= 0x800000000000ull) continue;
                if (Edges.size() == EdgeLimit) { EdgeLimitReached = true; return; }
                Edges.push_back({Parent, P, static_cast<uint32_t>(O), Depth});
                if (Seen.count(P)) continue;
                if (Queue.size() == NodeLimit) { NodeLimitReached = true; continue; }
                Seen.insert(P); Queue.emplace_back(P, Depth);
            }
        }
    };

    struct Occupancy { bool Valid = false; std::set<uint32_t> Free; };
    inline Occupancy FreeSlots(const std::vector<uint8_t>& Headers, uint32_t Stride,
        uint64_t Base, uint64_t Head, uint32_t Loaded)
    {
        Occupancy R;
        if (Stride < 8 || Headers.size() % Stride || Loaded > Headers.size() / Stride) return R;
        while (Head)
        {
            if (Head < Base || Head - Base >= Headers.size() || (Head - Base) % Stride) return R;
            const auto S = static_cast<uint32_t>((Head - Base) / Stride);
            if (!R.Free.insert(S).second) return R;
            memcpy(&Head, Headers.data() + size_t(S) * Stride, 8);
        }
        R.Valid = R.Free.size() == Headers.size() / Stride - Loaded;
        return R;
    }
    struct Candidate { uint32_t Slot, Offset; uint64_t Address; };
    struct Result { uint32_t Slots = 0; bool LimitReached = false; std::vector<Candidate> Candidates; };
    inline Result Plan(const std::vector<uint8_t>& Headers, uint32_t Stride)
    {
        Result R;
        if (Stride < 8 || Stride > 65536 || Headers.size() % Stride) return R;
        const auto Slots = std::min<size_t>(256, Headers.size() / Stride);
        std::set<uint64_t> Seen;
        for (uint32_t S = 0; S < Slots; ++S)
        {
            R.Slots = S + 1;
            // Skip the name hash / free-list link, not a payload field.
            for (uint32_t O = 8; O + 8 <= Stride; O += 8)
            {
                uint64_t P = 0; memcpy(&P, Headers.data() + size_t(S) * Stride + O, 8);
                if (P < 0x10000 || P >= 0x800000000000ull || !Seen.insert(P).second) continue;
                if (R.Candidates.size() == 256) { R.LimitReached = true; return R; }
                R.Candidates.push_back({S, O, P});
            }
        }
        return R;
    }
}
