#pragma once

#include <cstdint>

#pragma region WWII

#pragma pack(push, 1)
struct WWIIXPTocHeader
{
    uint64_t Magic;
    uint32_t Version;
    uint32_t EntriesCount;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXPTocEntry
{
    char Hash[16];
    uint64_t Offset;
    uint32_t Size;
    uint16_t PackageIndex;
};
#pragma pack(pop)

#pragma endregion
