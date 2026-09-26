#pragma once

#include <cstdint>

#pragma region Black Ops 3

#pragma pack(push, 1)
struct BO3XPakHeader
{
    uint32_t Magic;
    uint16_t Unknown1;
    uint16_t Version;
    uint64_t Unknown2;
    uint64_t Size;
    uint64_t FileCount;
    uint64_t DataOffset;
    uint64_t DataSize;
    uint64_t HashCount;
    uint64_t HashOffset;
    uint64_t HashSize;
    uint64_t Unknown3;
    uint64_t UnknownOffset;
    uint64_t Unknown4;
    uint64_t IndexCount;
    uint64_t IndexOffset;
    uint64_t IndexSize;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XPakHashEntry
{
    uint64_t Key;
    uint64_t Offset;
    uint64_t Size;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XPakDataHeader
{
    // Count and offset
    uint32_t Count;
    uint32_t Offset;

    // The commands tell what each block of data does
    uint32_t Commands[30];
};
#pragma pack(pop)

#pragma endregion
