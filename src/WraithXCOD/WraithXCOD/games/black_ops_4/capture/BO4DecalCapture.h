#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <map>
#include <vector>
#include <stdexcept>

namespace BO4DecalCapture
{
    constexpr uint32_t WorldBytes = 6832;
    constexpr uint32_t MaxWorldSlots = 16;

    inline std::map<uint64_t, uint32_t> MaterialUses(const std::vector<uint8_t>& Records)
    {
        if (Records.size() % 216 || Records.size() / 216 > 65536)
            throw std::runtime_error("Invalid BO4 volume decal record size");
        std::map<uint64_t, uint32_t> Uses;
        for (size_t Offset = 0; Offset < Records.size(); Offset += 216)
        {
            uint64_t Material = 0;
            std::memcpy(&Material, Records.data() + Offset + 0xB8, sizeof Material);
            if (Material) ++Uses[Material];
        }
        return Uses;
    }

    // Inspect a bounded snapshot, never follow unvalidated free-list pointers.
    inline std::string SelectWorld(uint64_t Base, uint32_t Stride, uint32_t Capacity,
        uint32_t Loaded, uint64_t FreeHead, const uint8_t* Bytes, size_t Size,
        uint64_t& World)
    {
        World = 0;
        if (!Base || Stride != WorldBytes || !Capacity || Capacity > MaxWorldSlots ||
            Loaded != 1)
            return "unsupported gfxworld pool layout or occupancy";
        const uint64_t Span = uint64_t(Stride) * Capacity;
        if (Base > (std::numeric_limits<uint64_t>::max)() - Span || !Bytes || Size != Span)
            return "invalid or incomplete gfxworld pool snapshot";
        bool Free[MaxWorldSlots] = {};
        uint32_t FreeCount = 0;
        for (uint64_t Next = FreeHead; Next != 0;)
        {
            if (Next < Base || Next - Base >= Span || (Next - Base) % Stride)
                return "gfxworld free-list pointer outside aligned pool slots";
            const auto Slot = static_cast<uint32_t>((Next - Base) / Stride);
            if (Free[Slot]) return "gfxworld free-list cycle";
            Free[Slot] = true;
            ++FreeCount;
            std::memcpy(&Next, Bytes + size_t(Slot) * Stride, sizeof Next);
        }
        if (FreeCount + Loaded != Capacity)
            return "gfxworld free-list occupancy disagrees with loaded count";
        for (uint32_t Slot = 0; Slot < Capacity; ++Slot)
            if (!Free[Slot]) World = Base + uint64_t(Slot) * Stride;
        return {};
    }
}
