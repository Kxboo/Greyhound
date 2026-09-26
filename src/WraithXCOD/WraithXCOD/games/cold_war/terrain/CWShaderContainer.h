#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

// Read the declared DXIL program kind. Technique-table slots are not stages:
// Cold War slot 2 contains vertex shaders, not the previously assumed domain.
namespace CWShaderContainer
{
    struct Program
    {
        uint32_t ContainerBytes = 0;
        uint32_t Kind = 0;
        bool Valid = false;
        const char* Stage() const
        {
            if (!Valid) return "unknown";
            switch (Kind)
            {
            case 0: return "pixel";
            case 1: return "vertex";
            case 2: return "geometry";
            case 3: return "hull";
            case 4: return "domain";
            case 5: return "compute";
            case 6: return "library";
            case 13: return "mesh";
            case 14: return "amplification";
            default: return "unknown";
            }
        }
    };

    inline Program Read(const void* Data, size_t Size)
    {
        Program Result;
        if (!Data || Size < 32) return Result;
        const auto* Bytes = static_cast<const uint8_t*>(Data);
        auto Word = [Bytes](size_t Offset) {
            uint32_t Value;
            std::memcpy(&Value, Bytes + Offset, sizeof(Value));
            return Value;
        };
        if (std::memcmp(Bytes, "DXBC", 4) != 0) return Result;
        const uint32_t Length = Word(24), Count = Word(28);
        if (Length < 32 || Length > Size || Count == 0 || Count > (Length - 32) / 4)
            return Result;
        bool Found = false;
        for (uint32_t Index = 0; Index < Count; ++Index)
        {
            const uint32_t Offset = Word(32 + static_cast<size_t>(Index) * 4);
            if (Offset < 32 + static_cast<uint64_t>(Count) * 4 || Offset > Length - 8)
                return Program{};
            const uint32_t PartSize = Word(Offset + 4);
            if (PartSize > Length - Offset - 8) return Program{};
            if (std::memcmp(Bytes + Offset, "DXIL", 4) != 0) continue;
            if (Found || PartSize < 24 || std::memcmp(Bytes + Offset + 16, "DXIL", 4) != 0)
                return Program{};
            const uint32_t ProgramWords = Word(Offset + 12);
            const uint32_t BitcodeOffset = Word(Offset + 24), BitcodeSize = Word(Offset + 28);
            if (ProgramWords < 6 || static_cast<uint64_t>(ProgramWords) * 4 > PartSize ||
                BitcodeOffset < 16 || BitcodeSize < 4 || static_cast<uint64_t>(8) + BitcodeOffset + BitcodeSize >
                    static_cast<uint64_t>(ProgramWords) * 4)
                return Program{};
            if (Word(static_cast<size_t>(Offset) + 16 + BitcodeOffset) != 0xDEC04342u)
                return Program{};
            Result.Kind = Word(Offset + 8) >> 16;
            Found = true;
        }
        Result.ContainerBytes = Length;
        Result.Valid = Found;
        return Result;
    }
}
