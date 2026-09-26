#pragma once

#include <cstdint>

// -- Contains structures for various game file formats

#include "games/black_ops_2/reader/GameBlackOps2FileLayouts.h"
#include "games/black_ops_3/reader/GameBlackOps3FileLayouts.h"
#include "games/world_war_2/reader/GameWorldWar2FileLayouts.h"

#pragma region SABStructures

#pragma pack(push, 1)
struct SABFileHeader
{
    uint32_t Magic;
    uint32_t Version;

    uint32_t SizeOfAudioEntry;
    uint32_t SizeOfHashEntry;
    uint32_t SizeOfNameEntry;

    uint32_t EntriesCount;

    uint8_t UnknownData[8];

    uint64_t FileSize;

    uint64_t EntryTableOffset;
    uint64_t HashTableOffset;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct SABv4Entry
{
    uint32_t Key;
    uint32_t Size;
    uint32_t SeekTableLength;
    uint32_t FrameCount;

    uint32_t Unknown1;

    uint64_t Offset;
    
    uint32_t FrameRate;
    uint8_t ChannelCount;

    uint8_t Looping;
    uint8_t Format;

    uint8_t Padding[9];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct SABv14Entry
{
    uint32_t Key;
    uint32_t Size;
    uint32_t Offset;
    uint32_t FrameCount;
    uint8_t FrameRateIndex;
    uint8_t ChannelCount;
    uint8_t Looping;
    uint8_t Format;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct SABv15Entry
{
    uint32_t Key;
    uint32_t Size;
    uint32_t FrameCount;

    uint32_t Unknown1;

    uint64_t Offset;

    uint8_t FrameRateIndex;
    uint8_t ChannelCount;
    uint8_t Looping;
    uint8_t Format;

    uint8_t Padding[8];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct SABv17Entry
{
    uint64_t Key;
    uint64_t Unknown1;
    uint64_t Offset;
    uint32_t Size;
    uint32_t SeekTableLength;
    uint32_t FrameCount;
    uint32_t PrimedSize;
    uint32_t FrameRate;
    uint32_t Unknown3;
    uint8_t Unknown4;
    uint8_t ChannelCount;
    uint8_t Looping;
    uint8_t Format;
    uint8_t Padding[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct SABv21Entry
{
    uint64_t Key;
    uint64_t Unknown1;
    uint64_t Offset;

    uint32_t Size;
    uint32_t FrameCount;

    uint64_t Unknown2;    

    uint8_t FrameRateIndex;
    uint8_t ChannelCount;
    uint8_t Looping;
    uint8_t Format;

    uint8_t Padding[4];
};
#pragma pack(pop)

#pragma endregion