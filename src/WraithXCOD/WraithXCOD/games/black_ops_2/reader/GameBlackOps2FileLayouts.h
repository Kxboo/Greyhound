#pragma once

#include <cstdint>

#pragma region Black Ops 2

#pragma pack(push, 1)
struct BO2IPakHeader
{
    uint32_t Magic;
    uint32_t Version;
    uint32_t Size;
    uint32_t SegmentCount;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2IPakSegment
{
    uint32_t Type;
    uint32_t Offset;
    uint32_t Size;
    uint32_t EntryCount;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2IPakDataHeader
{
    // Count and offset are packed into a single integer
    uint32_t Offset : 24;
    uint32_t Count : 8;

    // The commands tell what each block of data does
    uint32_t Commands[31];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2IPakEntry
{
    uint64_t Key;
    uint32_t Offset;
    uint32_t Size;
};
#pragma pack(pop)

#pragma endregion
