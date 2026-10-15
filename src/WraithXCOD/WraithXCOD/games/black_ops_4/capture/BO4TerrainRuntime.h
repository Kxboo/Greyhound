#pragma once
#include <array>
#include <cstdint>
#include <cstring>

namespace BO4TerrainRuntime
{
    // +32 names a slice of the shared texture array, not a sector-local slot.
    inline bool Matches(const uint8_t* record, const std::array<uint32_t, 8>& uv,
                        uint32_t expectedWeightSlice)
    {
        uint32_t actual = 0;
        std::memcpy(&actual, record + 32, sizeof(actual));
        return actual == expectedWeightSlice &&
            std::memcmp(record, uv.data(), sizeof(uint32_t) * 8) == 0;
    }
}
