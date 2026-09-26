#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

// Validate a complete indexed object before following any of its commands.
// Some indexed objects are not command streams. Never interpret their bytes
// as offsets into the rest of the package.
namespace XSUBObjectLayout
{
    struct Block { size_t Offset; uint32_t Size; uint8_t Codec; };
    inline uint32_t U32(const uint8_t* P) { uint32_t V; std::memcpy(&V, P, 4); return V; }
    inline bool Parse(const uint8_t* Data, size_t Size, uint64_t FileOffset, std::vector<Block>& Blocks)
    {
        Blocks.clear();
        if (!Data || !Size) return false;
        std::vector<Block> Parsed;
        size_t Position = 0;
        while (Position < Size)
        {
            if (Size - Position < 8) return false;
            const auto Count = U32(Data + Position);
            if (!Count || Count > 256) return false;
            const size_t HeaderSize = Count <= 30 ? 128 : 8 + 4 * Count;
            if (HeaderSize > Size - Position) return false;
            const auto Commands = Data + Position + 8;
            Position += HeaderSize;
            for (uint32_t I = 0; I < Count; ++I)
            {
                const auto Command = U32(Commands + 4 * I);
                const auto Length = Command & 0xffffff;
                const auto Codec = uint8_t(Command >> 24);
                if (Length > Size - Position) return false;
                if ((Codec == 8 || Codec == 9) && Length < 4) return false;
                Parsed.push_back({Position, Length, Codec});
                Position += Length;
            }
            // Headers begin at absolute package 128-byte boundaries. A final
            // object may end at its last data byte without trailing padding.
            if (Position == Size) break;
            const auto Padding = (128 - ((FileOffset % 128 + Position % 128) % 128)) % 128;
            if (Padding > Size - Position) return false;
            Position += size_t(Padding);
        }
        Blocks = std::move(Parsed);
        return !Blocks.empty();
    }
}
