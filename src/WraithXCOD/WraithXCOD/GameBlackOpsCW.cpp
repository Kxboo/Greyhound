#include <algorithm>
#include <set>
#include <vector>
#include "stdafx.h"

// The class we are implementing
#include "GameBlackOpsCW.h"

// We need the CoDAssets class
#include "CoDAssets.h"
#include "CoDRawImageTranslator.h"
#include "CoDXPoolParser.h"

// We need the following WraithX classes
#include "Strings.h"
#include "FileSystems.h"
#include "MemoryReader.h"
#include "MemoryWriter.h"
#include "SettingsManager.h"
#include "HalfFloats.h"
#include "Sound.h"
#include "TerrainResearchCapture.h"
#include "CWMapCandidateCapture.h"
#include "CWMapWorldCapture.h"
#include "CWSplineCapture.h"
#include "CWClipMapCapture.h"
#include "CWRadiantExport.h"
#include "CWBrushTypeCapture.h"
#include "ModelExportNaming.h"

// We need Opus
#include "../../External/Opus/include/opus.h"

// We need DirectXShaderCompiler for reflection
#include <wrl/client.h>
#include <d3d12.h>
#include <d3d12shader.h>
#include "dxc/Support/dxcapi.use.h"
#include "dxc/DxilContainer/DxilContainer.h"

using Microsoft::WRL::ComPtr;


#pragma comment(lib, "dxguid.lib")

// -- Initialize Asset Name Cache

WraithNameIndex GameBlackOpsCW::AssetNameCache = WraithNameIndex();
WraithNameIndex GameBlackOpsCW::StringCache = WraithNameIndex();

// -- Initialize built-in game offsets databases

// Black Ops CW SP
std::array<DBGameInfo, 3> GameBlackOpsCW::SinglePlayerOffsets =
{{
    { 0x11AD99D0, 0x0, 0xE275BF0, 0x0 }, // Latest offset 2023/12/10 Steam
    { 0x11E50670, 0x0, 0xE5EC920, 0x0 }, // Latest offset 2023/12/10 Battle.net
    { 0x10CFDE80, 0x0, 0xC97EAB0, 0x0 }, // Old offset
}};

// -- Finished with databases

// -- Begin DXC

dxc::DxcDllSupport DXCDLLSupport;

// -- End DXC

// -- Begin XModelStream structures

struct GfxStreamVertex
{
    uint8_t Color[4];

    uint16_t UVUPosition;
    uint16_t UVVPosition;

    int32_t VertexNormal;
    int32_t VertexTangent;
};

struct GfxStreamWeight
{
    uint8_t WeightVal1;
    uint8_t WeightVal2;
    uint8_t WeightVal3;
    uint8_t WeightVal4;

    uint16_t WeightID1;
    uint16_t WeightID2;
    uint16_t WeightID3;
    uint16_t WeightID4;
};

struct GfxStreamFace
{
    uint16_t Index1;
    uint16_t Index2;
    uint16_t Index3;
};

// -- End XModelStream structures

// -- Black Ops CW Pool Data Structure

struct BOCWXAssetPoolData
{
    // The beginning of the pool
    uint64_t PoolPtr;
    // The size of the asset header
    uint32_t AssetSize;
    // The maximum pool size
    uint32_t PoolSize;
    // Padding
    uint32_t Padding;
    // The amount of assets in the pool
    uint32_t AssetsLoaded;
    // A pointer to the closest free header
    uint64_t PoolFreeHeadPtr;
};

uint32_t GetFrameRate(uint8_t Index)
{
    switch (Index)
    {
    case 0: return 8000;
    case 1: return 12000;
    case 2: return 16000;
    case 3: return 24000;
    case 4: return 32000;
    case 5: return 44100;
    case 6: return 48000;
    case 7: return 96000;
    case 8: return 192000;
    default: return 48000;
    }
}

#pragma pack(push, 1)
struct BOCWStreamInfo
{
    uint64_t NamePtr;
    uint64_t UnknownZero;
    uint64_t StreamKey;
};
#pragma pack(pop)


// Verify that our pool data is exactly 0x20
static_assert(sizeof(BOCWXAssetPoolData) == 0x20, "Invalid Pool Data Size (Expected 0x20)");

namespace
{
    constexpr uint32_t BOCWTerrainGfxPoolIndex = 0xB1;
    // Recorded when offsets resolve, so pool enumeration can reach the same
    // directory later.  LoadOffsets is the only place that knows it.
    uint64_t BOCWDBAssetPoolsOffset = 0;
    constexpr uint64_t MaximumTerrainPoolBytes = 512ull * 1024ull * 1024ull;

    uint64_t TerrainGfxPoolPtr = 0;
    uint32_t TerrainGfxPoolSize = 0;
    uint32_t TerrainGfxAssetSize = 0;
}

bool GameBlackOpsCW::LoadOffsets()
{
    // ----------------------------------------------------
    //    Black Ops CW pools and sizes, XAssetPoolData is an array of pool info for each asset pool in the game
    //    Index * sizeof(BOCWXAssetPoolData) = the offset of the asset info in this array of data, we can verify it using the xmodel pool and checking for the model hash (0x04647533e968c910)
    //    Notice: Black Ops CW doesn't store a freePoolHandle at the beginning, so we just read on.
    //    On Black Ops CW, (0x04647533e968c910) will be the first xmodel
    //    Black Ops CW stringtable, check entries, results may vary
    // ----------------------------------------------------

    TerrainGfxPoolPtr = 0;
    TerrainGfxPoolSize = 0;
    TerrainGfxAssetSize = 0;

    // Attempt to load the game offsets
    if (CoDAssets::GameInstance == nullptr)
        return false;
        
    // We need the base address of the BO4 Module for ASLR + Heuristics
    auto BaseAddress = CoDAssets::GameInstance->GetMainModuleAddress();

    // Check built-in offsets via game exe mode (SP)
    for (auto& GameOffsets : SinglePlayerOffsets)
    {
        // Read required offsets (XANIM, XMODEL, XIMAGE, RAWFILE RELATED...)
        auto AnimPoolData       = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(BaseAddress + GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 5));
        auto ModelPoolData      = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(BaseAddress + GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 6));
        auto ImagePoolData      = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(BaseAddress + GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 0x10));
        auto MaterialPoolData   = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(BaseAddress + GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 10));
        auto SoundAssetPoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(BaseAddress + GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 19));
        auto TerrainPoolData    = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(BaseAddress + GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * BOCWTerrainGfxPoolIndex));

        // Apply game offset info
        CoDAssets::GameOffsetInfos.emplace_back(AnimPoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(ModelPoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(ImagePoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(MaterialPoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(SoundAssetPoolData.PoolPtr);

        // Verify via first xmodel asset, right now, we're using a hash
        auto FirstXModelHash = CoDAssets::GameInstance->Read<uint64_t>(CoDAssets::GameOffsetInfos[1]);
        // Check
        if (FirstXModelHash == 0x04647533e968c910)
        {
            // Validate sizes
            if (AnimPoolData.AssetSize == sizeof(BOCWXAnim) &&
                ModelPoolData.AssetSize == sizeof(BOCWXModel) &&
                ImagePoolData.AssetSize == sizeof(BOCWGfxImage))
            {
                // Verify string table, otherwise we are all set
                CoDAssets::GameOffsetInfos.emplace_back(BaseAddress + GameOffsets.StringTable);
                // Read and apply sizes
                CoDAssets::GamePoolSizes.emplace_back(AnimPoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(ModelPoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(ImagePoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(MaterialPoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(SoundAssetPoolData.PoolSize);
                TerrainGfxPoolPtr = TerrainPoolData.PoolPtr;
                TerrainGfxPoolSize = TerrainPoolData.PoolSize;
                TerrainGfxAssetSize = TerrainPoolData.AssetSize;
                BOCWDBAssetPoolsOffset = BaseAddress + GameOffsets.DBAssetPools;
                // Return success
                return true;
            }
        }
        // Reset
        CoDAssets::GameOffsetInfos.clear();
    }

    // Attempt to locate via heuristic searching
    auto DBAssetsScan = CoDAssets::GameInstance->Scan("40 53 48 83 EC ?? 0F B6 ?? 48 8D 05 ?? ?? ?? ?? 48 C1 E2 05");
    auto StringTableScan = CoDAssets::GameInstance->Scan("48 8B 53 ?? 48 85 D2 74 ?? 48 8B 03 48 89 02");

    // Check that we had hits
    if (DBAssetsScan > 0 && StringTableScan > 0)
    {
        // Load info and verify
        auto GameOffsets = DBGameInfo(
            // Resolve pool info from LEA
            CoDAssets::GameInstance->Read<uint32_t>(DBAssetsScan + 0xC) + (DBAssetsScan + 0x10),
            // We don't use size offsets
            0,
            // Resolve strings from LEA
            CoDAssets::GameInstance->Read<uint32_t>(StringTableScan + 0x12) + (StringTableScan + 0x16),
            // We don't use package offsets
            0
        );

        // In debug, print the info for easy additions later!
#if _DEBUG
        // Format the output
        printf("Heuristic: { 0x%llX, 0x0, 0x%llX, 0x0 }\n", (GameOffsets.DBAssetPools - BaseAddress), (GameOffsets.StringTable - BaseAddress));
#endif


        // Read required offsets (XANIM, XMODEL, XIMAGE)
        auto AnimPoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 5));
        auto ModelPoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 6));
        auto ImagePoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 0x10));
        auto MaterialPoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 10));
        auto SoundAssetPoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * 19));
        auto TerrainPoolData = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(GameOffsets.DBAssetPools + (sizeof(BOCWXAssetPoolData) * BOCWTerrainGfxPoolIndex));

        // Apply game offset info
        CoDAssets::GameOffsetInfos.emplace_back(AnimPoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(ModelPoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(ImagePoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(MaterialPoolData.PoolPtr);
        CoDAssets::GameOffsetInfos.emplace_back(SoundAssetPoolData.PoolPtr);

        // Verify via first xmodel asset, right now, we're using a hash
        auto FirstXModelHash = CoDAssets::GameInstance->Read<uint64_t>(CoDAssets::GameOffsetInfos[1]);

        // Check
        if (FirstXModelHash == 0x04647533e968c910)
        {
            // Validate sizes
            if (
                AnimPoolData.AssetSize  == sizeof(BOCWXAnim) && 
                ModelPoolData.AssetSize == sizeof(BOCWXModel) && 
                ImagePoolData.AssetSize == sizeof(BOCWGfxImage))
            {
                // Verify string table, otherwise we are all set
                CoDAssets::GameOffsetInfos.emplace_back(GameOffsets.StringTable);

                // Read and apply sizes
                CoDAssets::GamePoolSizes.emplace_back(AnimPoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(ModelPoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(ImagePoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(MaterialPoolData.PoolSize);
                CoDAssets::GamePoolSizes.emplace_back(SoundAssetPoolData.PoolSize);
                TerrainGfxPoolPtr = TerrainPoolData.PoolPtr;
                TerrainGfxPoolSize = TerrainPoolData.PoolSize;
                TerrainGfxAssetSize = TerrainPoolData.AssetSize;
                // This branch's DBAssetPools is already absolute -- unlike the
                // one above, it is not rebased -- so record it as-is.
                BOCWDBAssetPoolsOffset = GameOffsets.DBAssetPools;

                // Return success
                return true;
            }
        }
    }


    // Failed
    return false;
}

uint64_t CWCalculateHash(const std::string& Name)
{
    const uint64_t FNVPrime = 0x100000001B3;
    const uint64_t FNVOffset = 0xCBF29CE484222325;

    uint64_t Result = FNVOffset;

    for (uint64_t i = 0; i < Name.size(); i++)
    {
        Result ^= Name[i];
        Result *= FNVPrime;
    }
    return Result & 0xFFFFFFFFFFFFFFF;
}

std::string GameBlackOpsCW::DescribeAssetPools(uint32_t MaximumPoolIndex)
{
    // Read-only walk of the pool directory, the same table and struct the
    // terrain loader already uses -- no new access technique, just every index
    // instead of one.  Reports the shape of each pool so an unknown asset type
    // can be identified by its entry count and header size, plus the first
    // name hash so it can be matched against the wni dictionaries offline.
    std::string Report = "index,pool_ptr,asset_size,pool_size,assets_loaded,first_name_hash\n";

    if (CoDAssets::GameInstance == nullptr)
        return Report;

    if (BOCWDBAssetPoolsOffset == 0)
        return Report;

    for (uint32_t Index = 0; Index <= MaximumPoolIndex; Index++)
    {
        const uint64_t Entry = BOCWDBAssetPoolsOffset +
            (sizeof(BOCWXAssetPoolData) * Index);
        auto Pool = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(Entry);

        if (Pool.PoolPtr == 0 || Pool.AssetsLoaded == 0 || Pool.AssetSize == 0)
            continue;
        if (Pool.AssetSize > 0x10000 || Pool.PoolSize == 0)
            continue;

        uint64_t FirstHash = 0;
        FirstHash = CoDAssets::GameInstance->Read<uint64_t>(Pool.PoolPtr);

        Report += Strings::Format("0x%X,0x%llX,%u,%u,%u,0x%llX\n",
            Index, Pool.PoolPtr, Pool.AssetSize, Pool.PoolSize,
            Pool.AssetsLoaded, FirstHash & 0xFFFFFFFFFFFFFFF);
    }

    return Report;
}

bool GameBlackOpsCW::DumpAssetPool(uint32_t PoolIndex,
    const std::string& OutputPath, uint32_t MaximumAssets)
{
    if (CoDAssets::GameInstance == nullptr || BOCWDBAssetPoolsOffset == 0)
        return false;

    auto Pool = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(
        BOCWDBAssetPoolsOffset + (sizeof(BOCWXAssetPoolData) * PoolIndex));

    if (Pool.PoolPtr == 0 || Pool.AssetSize == 0 || Pool.AssetsLoaded == 0)
        return false;
    if (Pool.AssetSize > 0x10000 || Pool.AssetsLoaded > Pool.PoolSize)
        return false;

    uint32_t Count = Pool.AssetsLoaded;
    if (MaximumAssets != 0 && Count > MaximumAssets)
        Count = MaximumAssets;

    const uint64_t Bytes = static_cast<uint64_t>(Pool.AssetSize) * Count;
    if (Bytes == 0 || Bytes > 256ull * 1024ull * 1024ull)
        return false;

    uintptr_t BytesRead = 0;
    auto Buffer = CoDAssets::GameInstance->Read(Pool.PoolPtr,
        static_cast<uintptr_t>(Bytes), BytesRead);
    if (Buffer == nullptr)
        return false;

    std::ofstream Output(OutputPath, std::ios::binary | std::ios::trunc);
    Output.write(reinterpret_cast<const char*>(Buffer), BytesRead);
    Output.close();
    delete[] Buffer;
    return BytesRead > 0;
}

std::string GameBlackOpsCW::DumpAssetArrays(uint32_t PoolIndex,
    const std::string& OutputDirectory)
{
    std::string Report;
    if (CoDAssets::GameInstance == nullptr || BOCWDBAssetPoolsOffset == 0)
        return Report;

    auto Pool = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(
        BOCWDBAssetPoolsOffset + (sizeof(BOCWXAssetPoolData) * PoolIndex));
    if (Pool.PoolPtr == 0 || Pool.AssetSize == 0 || Pool.AssetSize > 0x10000)
        return Report;

    // Walk many assets, not just the first.  Reading only asset[0] meant a pool
    // holding thousands of records was searched one record deep, which is why
    // earlier sweeps found nothing -- a negative result over one asset says
    // nothing about the pool.
    const uint32_t MaximumAssets = 48;
    uint32_t AssetCount = Pool.AssetsLoaded;
    if (AssetCount > MaximumAssets)
        AssetCount = MaximumAssets;

    std::set<uint64_t> SeenPointers;
    uint64_t TotalBytes = 0;
    const uint64_t PoolByteBudget = 48ull * 1024ull * 1024ull;

    for (uint32_t AssetIndex = 0; AssetIndex < AssetCount; AssetIndex++)
    {
        const uint64_t AssetAddress = Pool.PoolPtr +
            (static_cast<uint64_t>(AssetIndex) * Pool.AssetSize);

        uintptr_t HeaderRead = 0;
        auto Header = CoDAssets::GameInstance->Read(AssetAddress, Pool.AssetSize, HeaderRead);
        if (Header == nullptr)
            continue;

        std::vector<std::pair<uint64_t, uint64_t>> Entries;
        for (uint32_t Offset = 0; Offset + 16 <= HeaderRead; Offset += 8)
        {
            uint64_t Count = 0, Pointer = 0;
            std::memcpy(&Count, Header + Offset, sizeof(Count));
            std::memcpy(&Pointer, Header + Offset + 8, sizeof(Pointer));
            if (Count > 1000000)
                Count &= 0xFFFFFFFF;
            if (Count > 1000000)
                Count >>= 16;
            if (Count == 0 || Count > 1000000)
                continue;
            if (Pointer < 0x10000 || Pointer > 0x7FF000000000)
                continue;
            Entries.emplace_back(Count, Pointer);
        }
        delete[] Header;

        for (size_t i = 0; i < Entries.size(); i++)
        {
            const uint64_t Count = Entries[i].first;
            const uint64_t Pointer = Entries[i].second;
            if (SeenPointers.count(Pointer) != 0)
                continue;
            SeenPointers.insert(Pointer);

            uint64_t Stride = 64;
            if (i + 1 < Entries.size() && Entries[i + 1].second > Pointer)
            {
                const uint64_t Span = Entries[i + 1].second - Pointer;
                if (Span / Count > 0 && Span / Count <= 4096)
                    Stride = Span / Count;
            }

            uint64_t Bytes = Count * Stride;
            if (Bytes > 1024ull * 1024ull)
                Bytes = 1024ull * 1024ull;
            if (TotalBytes + Bytes > PoolByteBudget)
                return Report;

            uintptr_t BytesRead = 0;
            auto Buffer = CoDAssets::GameInstance->Read(Pointer,
                static_cast<uintptr_t>(Bytes), BytesRead);
            if (Buffer == nullptr)
                continue;
            TotalBytes += BytesRead;

            const std::string Path = FileSystems::CombinePath(OutputDirectory,
                Strings::Format("pool_%03X_a%03u_i%02zu_n%llu_s%llu.bin",
                    PoolIndex, AssetIndex, i, Count, Stride));
            std::ofstream Output(Path, std::ios::binary | std::ios::trunc);
            Output.write(reinterpret_cast<const char*>(Buffer), BytesRead);
            Output.close();
            delete[] Buffer;

            Report += Strings::Format("  a%u array %zu: count=%llu stride=%llu ptr=0x%llX\n",
                AssetIndex, i, Count, Stride, Pointer);
        }
    }

    return Report;
}

std::string GameBlackOpsCW::DumpAllPools(uint32_t MaximumPoolIndex,
    const std::string& OutputDirectory)
{
    std::string Report;
    if (CoDAssets::GameInstance == nullptr || BOCWDBAssetPoolsOffset == 0)
        return Report;

    for (uint32_t Index = 0; Index <= MaximumPoolIndex; Index++)
    {
        auto Pool = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(
            BOCWDBAssetPoolsOffset + (sizeof(BOCWXAssetPoolData) * Index));
        if (Pool.PoolPtr == 0 || Pool.AssetSize == 0 || Pool.AssetsLoaded == 0)
            continue;
        if (Pool.AssetSize > 0x10000 || Pool.AssetsLoaded > Pool.PoolSize)
            continue;

        const std::string HeaderPath = FileSystems::CombinePath(OutputDirectory,
            Strings::Format("sweep_%03X_hdr_n%u_s%u.bin",
                Index, Pool.AssetsLoaded, Pool.AssetSize));
        DumpAssetPool(Index, HeaderPath, 512);

        Report += Strings::Format("pool 0x%X assets=%u size=%u\n",
            Index, Pool.AssetsLoaded, Pool.AssetSize);

        // Resolve what we can from the loaded name dictionaries; most asset
        // types are absent from them, so an unresolved hash is expected.
        for (uint32_t i = 0; i < Pool.AssetsLoaded && i < 60000; i++)
        {
            uint64_t Hash = CoDAssets::GameInstance->Read<uint64_t>(
                Pool.PoolPtr + (static_cast<uint64_t>(i) * Pool.AssetSize));
            Hash &= 0xFFFFFFFFFFFFFFF;
            auto Found = AssetNameCache.NameDatabase.find(Hash);
            if (Found != AssetNameCache.NameDatabase.end())
                Report += Strings::Format("    [%u] 0x%llX %s\n", i, Hash,
                    Found->second.c_str());
            else
                Report += Strings::Format("    [%u] 0x%llX\n", i, Hash);
        }

        Report += DumpAssetArrays(Index, OutputDirectory);
    }

    return Report;
}

bool GameBlackOpsCW::PeekMemory(uint64_t Address, uint32_t Bytes,
    const std::string& OutputPath)
{
    if (CoDAssets::GameInstance == nullptr)
        return false;
    if (Address < 0x10000 || Address >= 0x0000800000000000ull ||
        Bytes == 0 || Bytes > 16u * 1024u * 1024u || Bytes > 0x0000800000000000ull - Address)
        return false;

    uintptr_t BytesRead = 0;
    auto Buffer = CoDAssets::GameInstance->Read(Address, Bytes, BytesRead);
    if (Buffer == nullptr)
        return false;

    std::ofstream Output(OutputPath, std::ios::binary | std::ios::trunc);
    Output.write(reinterpret_cast<const char*>(Buffer), BytesRead);
    Output.close();
    delete[] Buffer;
    return BytesRead == Bytes && Output.good();
}

std::string GameBlackOpsCW::ResolveNameHash(uint64_t Address)
{
    if (CoDAssets::GameInstance == nullptr)
        return std::string();
    uint64_t Hash = CoDAssets::GameInstance->Read<uint64_t>(Address);
    Hash &= 0xFFFFFFFFFFFFFFF;
    auto Found = AssetNameCache.NameDatabase.find(Hash);
    if (Found == AssetNameCache.NameDatabase.end())
        return std::string();
    return Found->second;
}

std::string GameBlackOpsCW::ExportTerrainDecals(const std::string& ExportPath)
{
    std::string Manifest;
    if (CoDAssets::GameInstance == nullptr || BOCWDBAssetPoolsOffset == 0)
        return Manifest;

    // Material pool bounds are the discriminator: a decal record carries a raw
    // pointer to its material, so an array of 48-byte records whose +0x20 qword
    // lands inside this range is the decal list.  Nothing else in the scene
    // matches that shape, so no pool or array index needs to be remembered.
    auto MaterialPool = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(
        BOCWDBAssetPoolsOffset + (sizeof(BOCWXAssetPoolData) * 0x0A));
    if (MaterialPool.PoolPtr == 0 || MaterialPool.AssetSize == 0)
        return Manifest;
    const uint64_t MaterialLow = MaterialPool.PoolPtr;
    const uint64_t MaterialHigh = MaterialPool.PoolPtr +
        (static_cast<uint64_t>(MaterialPool.AssetSize) * MaterialPool.PoolSize);

    const uint32_t RecordSize = 48;
    std::vector<uint8_t> Records;
    uint64_t FoundCount = 0;
    uint32_t FoundPool = 0;
    uint64_t FoundPointer = 0, FoundHeader = 0;
    uint32_t FoundOffset = 0;

    for (uint32_t Index = 0; Index <= 0xDC && Records.empty(); Index++)
    {
        auto Pool = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(
            BOCWDBAssetPoolsOffset + (sizeof(BOCWXAssetPoolData) * Index));
        if (Pool.PoolPtr == 0 || Pool.AssetSize == 0 || Pool.AssetsLoaded == 0)
            continue;
        if (Pool.AssetSize > 0x10000 || Pool.AssetsLoaded > Pool.PoolSize)
            continue;

        uintptr_t HeaderRead = 0;
        auto Header = CoDAssets::GameInstance->Read(Pool.PoolPtr, Pool.AssetSize, HeaderRead);
        if (Header == nullptr)
            continue;

        for (uint32_t Offset = 0; Offset + 16 <= HeaderRead && Records.empty(); Offset += 8)
        {
            uint64_t Count = 0, Pointer = 0;
            std::memcpy(&Count, Header + Offset, sizeof(Count));
            std::memcpy(&Pointer, Header + Offset + 8, sizeof(Pointer));
            if (Count < 16 || Count > 1000000)
                continue;
            if (Pointer < 0x10000 || Pointer > 0x7FF000000000)
                continue;

            // Probe a handful of records; every one must reference a material.
            bool Matches = true;
            for (uint32_t Probe = 0; Probe < 8 && Matches; Probe++)
            {
                const uint64_t Material = CoDAssets::GameInstance->Read<uint64_t>(
                    Pointer + (static_cast<uint64_t>(Probe) * RecordSize) + 0x20);
                if (Material < MaterialLow || Material >= MaterialHigh)
                    Matches = false;
                else if ((Material - MaterialLow) % MaterialPool.AssetSize != 0)
                    Matches = false;
            }
            if (!Matches)
                continue;

            const uint64_t Bytes = Count * RecordSize;
            if (Bytes > 64ull * 1024ull * 1024ull)
                continue;
            uintptr_t BytesRead = 0;
            auto Buffer = CoDAssets::GameInstance->Read(Pointer,
                static_cast<uintptr_t>(Bytes), BytesRead);
            if (Buffer == nullptr || BytesRead != Bytes)
            {
                delete[] Buffer;
                continue;
            }
            Records.assign(Buffer, Buffer + BytesRead);
            delete[] Buffer;
            FoundCount = Count;
            FoundPool = Index;
            FoundPointer = Pointer;
            FoundHeader = Pool.PoolPtr;
            FoundOffset = Offset;
        }
        delete[] Header;
    }

    if (Records.empty())
        return Manifest;

    const std::string DecalPath = FileSystems::CombinePath(ExportPath, "decals");
    FileSystems::CreateDirectory(DecalPath);
    const std::string BinaryPath = FileSystems::CombinePath(DecalPath, "decal_records.bin");
    std::ofstream Binary(BinaryPath, std::ios::binary | std::ios::trunc);
    Binary.write(reinterpret_cast<const char*>(Records.data()), Records.size());
    Binary.close();

    std::set<uint64_t> Materials;
    for (uint64_t i = 0; i < FoundCount; i++)
    {
        uint64_t Pointer = 0;
        std::memcpy(&Pointer, Records.data() + (i * RecordSize) + 0x20, sizeof(Pointer));
        Materials.insert(Pointer);
    }

    Manifest += "{\n";
    Manifest += "  \"schema\": \"superterrain-decals-v2\",\n";
    Manifest += Strings::Format("  \"sourcePool\": \"0x%X\",\n", FoundPool);
    Manifest += Strings::Format("  \"sourcePointer\": \"0x%llX\",\n", FoundPointer);
    Manifest += Strings::Format("  \"sourceHeader\": \"0x%llX\",\n", FoundHeader);
    Manifest += Strings::Format("  \"countOffset\": %u,\n", FoundOffset);
    Manifest += Strings::Format("  \"records\": %llu,\n", FoundCount);
    Manifest += "  \"recordSize\": 48,\n";
    Manifest += "  \"recordFile\": \"decal_records.bin\",\n";
    Manifest += "  \"materials\": [\n";

    bool First = true;
    for (const uint64_t Pointer : Materials)
    {
        auto Material = ReadXMaterial(Pointer);
        uint64_t Used = 0;
        for (uint64_t i = 0; i < FoundCount; i++)
        {
            uint64_t Each = 0;
            std::memcpy(&Each, Records.data() + (i * RecordSize) + 0x20, sizeof(Each));
            if (Each == Pointer)
                Used++;
        }

        // Preserve the same semantic and parameter sidecars as a normal
        // XMaterial export. The raw decal manifest already records semantic
        // hashes, but these files retain Greyhound's canonical labels and the
        // readable settings needed to cross-reference road paint/asphalt.
        CoDAssets::ExportMaterialImageNames(Material, DecalPath);
        CoDAssets::ExportMaterialImages(Material, DecalPath, ".png",
            ImageFormat::Standard_PNG);

        if (!First)
            Manifest += ",\n";
        First = false;
        Manifest += "    {\n";
        Manifest += Strings::Format("      \"materialPointer\": \"0x%llX\",\n", Pointer);
        Manifest += Strings::Format("      \"materialNameHash\": \"0x%llX\",\n",
            CoDAssets::GameInstance->Read<uint64_t>(Pointer) & 0x0FFFFFFFFFFFFFFFull);
        Manifest += Strings::Format("      \"name\": \"%s\",\n",
            Material.MaterialName.c_str());
        Manifest += Strings::Format("      \"decals\": %llu,\n", Used);
        Manifest += "      \"images\": [";
        for (size_t i = 0; i < Material.Images.size(); i++)
        {
            if (i != 0)
                Manifest += ", ";
            Manifest += Strings::Format("{\"semantic\": %u, \"name\": \"%s\"}",
                Material.Images[i].SemanticHash,
                Material.Images[i].ImageName.c_str());
        }
        Manifest += "]\n    }";
    }
    Manifest += "\n  ]\n}\n";

    const std::string ManifestPath = FileSystems::CombinePath(DecalPath, "decals.json");
    std::ofstream Output(ManifestPath, std::ios::binary | std::ios::trunc);
    Output << Manifest;
    Output.close();
    return Manifest;
}

bool GameBlackOpsCW::ExportTerrainResearch(const CoDTerrain_t* Terrain,
    const std::string& ExportPath, const std::vector<uint64_t>& ProbeMaterials,
    const std::function<void(uint32_t)>& ReportProgress)
{
    using namespace TerrainResearch;
    if (!CoDAssets::GameInstance || !BOCWDBAssetPoolsOffset) return false;
    Capture C(FileSystems::CombinePath(ExportPath, "research"), ReportProgress);
    C.Progress("terrain_dependencies", 8, 0, 1);
    C.Report["terrain_address"] = Hex(Terrain->AssetPointer);
    C.Report["mode"] = "source_data_only";
    C.Report["array_selection"] = "all pool headers; follow count/pointer candidates in terrain hash siblings, named terrain/spline/decal assets, pool 0x1B, and the first occupied-looking header of each pool";
    auto H = C.Span(Terrain->AssetPointer, Terrain->AssetSize, "terrain_start.bin", "TerrainGfx header at start of additional evidence pass");
    const auto TerrainHash = U64(H, 0) & 0x0FFFFFFFFFFFFFFFull;
    const auto Bindings = C.Span(U64(H, 0x38), U64(H, 0x30) <= 65536 ? U64(H, 0x30) * 8 : Capture::SpanLimit + 1,
        "terrain_image_pointers.bin", "TerrainGfx image pointer table");
    for (size_t O = 0; O + 8 <= Bindings.size(); O += 8) C.Image(U64(Bindings, O));
    const auto Layers = C.Span(U64(H, 0x118), U64(H, 0x110) <= 1024 ? U64(H, 0x110) * 96 : Capture::SpanLimit + 1,
        "layer_image_pointers.bin", "12 image pointers per layer record from existing capture layout");
    for (size_t O = 0; O + 8 <= Layers.size(); O += 8) if (U64(Layers, O)) C.Image(U64(Layers, O));
    auto Root = C.Span(U64(H, 0x10), U64(H, 0x10) ? 0x170 : 0, "mapping_root_prefix.bin", "mapping root prefix covering known counted tables");
    const auto Slots = C.Span(U64(Root, 0x110), U64(Root, 0x108) <= 4096 ? U64(Root, 0x108) * 0x130 : Capture::SpanLimit + 1,
        "slot_materials.bin", "0x130-byte painted-slot records, including UV transforms and sort fields");
    for (size_t O = 0; O + 0x130 <= Slots.size(); O += 0x130) C.Material(U64(Slots, O));
    for (auto M : ProbeMaterials) C.Material(M, 1);
    C.Progress("terrain_dependencies", 18, 1, 1);

    const auto PoolBytes = C.Span(BOCWDBAssetPoolsOffset, 0xDD * sizeof(BOCWXAssetPoolData),
        "pool_descriptors_start.bin", "all 0xDD DBAssetPools descriptors, including free-list heads");
    BOCWXAssetPoolData MaterialPool{};
    if (PoolBytes.size() >= 0x0B * sizeof(MaterialPool))
        memcpy(&MaterialPool, PoolBytes.data() + 0x0A * sizeof(MaterialPool), sizeof(MaterialPool));
    const auto IsMaterial = [&](uint64_t P) {
        return MaterialPool.AssetSize == 0x158 && P >= MaterialPool.PoolPtr &&
            P - MaterialPool.PoolPtr < uint64_t(MaterialPool.PoolSize) * MaterialPool.AssetSize &&
            (P - MaterialPool.PoolPtr) % MaterialPool.AssetSize == 0;
    };
    uint64_t CandidateBytes = 0;
    std::set<uint64_t> Arrays;
    C.Report["decals"] = json::array();
    for (size_t Index = 0; (Index + 1) * sizeof(BOCWXAssetPoolData) <= PoolBytes.size(); ++Index)
    {
        C.Progress("pool_evidence", 18 + static_cast<uint32_t>(6 * Index / 0xDD), Index, 0xDD);
        BOCWXAssetPoolData P{}; memcpy(&P, PoolBytes.data() + Index * sizeof(P), sizeof(P));
        json Info = {{"index", Index}, {"pointer", Hex(P.PoolPtr)}, {"asset_size", P.AssetSize},
            {"capacity", P.PoolSize}, {"loaded", P.AssetsLoaded}, {"free_head", Hex(P.PoolFreeHeadPtr)}};
        if (!P.AssetsLoaded) { Info["status"] = "empty"; C.Report["pools"].push_back(Info); continue; }
        if (!Pointer(P.PoolPtr) || P.AssetSize < 8 || P.AssetSize > 65536 || P.AssetsLoaded > P.PoolSize)
        {
            Info["status"] = "invalid_descriptor"; C.Report["pools"].push_back(Info); continue;
        }
        const auto Stem = "pools/" + std::to_string(Index);
        // Capacity matters: occupied headers can lie beyond AssetsLoaded because
        // the pool has holes. Preserve the free list so occupancy can be audited.
        auto Headers = C.Span(P.PoolPtr, uint64_t(P.AssetSize) * P.PoolSize,
            Stem + ".headers.bin", "entire allocated header pool; includes free slots, not all entries are assets");
        Info["file"] = Stem + ".headers.bin";
        Info["status"] = Headers.empty() ? "not_fully_captured_see_reads" : "captured";
        C.Report["pools"].push_back(Info);
        bool First = true;
        for (size_t O = 0; O + P.AssetSize <= Headers.size(); O += P.AssetSize)
        {
            const auto RawName = U64(Headers, O);
            if (!RawName || (RawName >= P.PoolPtr && RawName - P.PoolPtr < Headers.size())) continue;
            const auto Hash = RawName & 0x0FFFFFFFFFFFFFFFull;
            const auto Name = AssetNameCache.NameDatabase.find(Hash);
            const std::string Resolved = Name == AssetNameCache.NameDatabase.end() ? "" : Name->second;
            const bool Named = Resolved.find("terrain") != std::string::npos ||
                Resolved.find("spline") != std::string::npos || Resolved.find("decal") != std::string::npos;
            const bool Follow = First || Index == 0x1B || (TerrainHash && Hash == TerrainHash) || Named;
            First = false;
            if (!Follow) continue;
            if (Index == 0x0A && Named) C.Material(P.PoolPtr + O, 2);
            if (Index == 0x10 && Named) C.Image(P.PoolPtr + O, 2);
            // Only one level of unknown arrays. Keep parent address + byte offset
            // so every inference can be revisited against the raw header.
            for (size_t A = 0; A + 16 <= P.AssetSize; A += 8)
            {
                const auto CountField = U64(Headers, O + A);
                const auto Count = CountField & 0xFFFFFFFFull;
                const auto Ptr = U64(Headers, O + A + 8);
                if (!Count || Count > 1000000 || !Pointer(Ptr)) continue;
                json Candidate = {{"pool", Index}, {"parent_address", Hex(P.PoolPtr + O)},
                    {"parent_hash", Hex(Hash)}, {"parent_name", Resolved}, {"count_offset", A},
                    {"count_field", Hex(CountField)}, {"candidate_count_low32", Count}, {"pointer", Hex(Ptr)}};
                if (!Arrays.insert(Ptr).second)
                {
                    Candidate["status"] = "duplicate_pointer";
                    C.Report["array_candidates"].push_back(Candidate); continue;
                }
                if (CandidateBytes + 65536 > 512ull * 1024 * 1024)
                {
                    Candidate["status"] = "candidate_budget_rejected";
                    C.Report["array_candidates"].push_back(Candidate); continue;
                }
                // Probe only the material-bearing record shape. Failure does not
                // establish absence of decals, nor identify authored spline data.
                const auto ProbeCount = std::min<uint64_t>(Count, 8);
                auto Probe = C.Span(Ptr, ProbeCount * 48, "arrays/" + Hex(Ptr) + ".probe.bin",
                    "candidate 48-byte record prefix; type unconfirmed");
                bool Decal = !Probe.empty();
                for (size_t R = 0; R < ProbeCount && Decal; ++R) Decal = IsMaterial(U64(Probe, R * 48 + 0x20));
                CandidateBytes += ProbeCount * 48;
                if (Decal)
                {
                    const auto File = "decals/" + Hex(Ptr) + ".records.bin";
                    auto Records = C.Span(Ptr, Count * 48, File, "candidate decal records: first up to eight records reference aligned material pool entries");
                    json D = Candidate;
                    D["record_size"] = 48; D["count"] = Count; D["file"] = File;
                    D["status"] = Records.empty() ? "not_fully_captured_see_reads" : "captured_candidate";
                    D["authored_spline_control_points"] = "not_identified";
                    C.Report["decals"].push_back(D);
                    for (size_t R = 0; R + 48 <= Records.size(); R += 48)
                        if (IsMaterial(U64(Records, R + 0x20))) C.Material(U64(Records, R + 0x20));
                    Candidate["status"] = "decal_shape_candidate";
                }
                else
                {
                    // Count gives no stride. Do not invent count*64 as a full array.
                    C.Span(Ptr, 65536, "arrays/" + Hex(Ptr) + ".prefix.bin",
                        "64-KiB research prefix, allocation boundary and stride unknown; may contain adjacent data");
                    CandidateBytes += 65536;
                    Candidate["status"] = "prefix_attempted_extent_unknown";
                }
                C.Report["array_candidates"].push_back(Candidate);
            }
        }
    }
    C.FlushPayloads();
    const auto End = C.Span(Terrain->AssetPointer, Terrain->AssetSize, "terrain_end.bin", "header reread; see stability check", true);
    C.Report["terrain_header_unchanged_during_evidence_pass"] =
        H.empty() || End.empty() ? json(nullptr) : json(H == End);
    const auto PoolsEnd = C.Span(BOCWDBAssetPoolsOffset, PoolBytes.size(), "pool_descriptors_end.bin",
        "pool descriptor reread; compares counts and pointers, not pointed-to payload contents", true);
    C.Report["pool_descriptors_unchanged_during_evidence_pass"] =
        PoolBytes.empty() || PoolsEnd.empty() ? json(nullptr) : json(PoolBytes == PoolsEnd);
    C.Report["stability_scope"] = "header equality only; pointed-to resources may change while capturing";
    C.Progress("research_complete", 35, 1, 1);
    return C.Finish();
}

#include "CWPoolProbe.h"

namespace
{
    struct CWResearchPool { uint32_t Index; const char* Name; const char* Setting; };
    // T9 Main.hpp enum: names are candidates, not verified member layouts.
    const CWResearchPool CWResearchPools[] = {
        {0x02, "physpreset", "showcwcollision"}, {0x03, "physconstraints", "showcwcollision"},
        {0x04, "destructibledef", "showcwentities"}, {0x43, "glasses", "showcwentities"},
        {0xD1, "dynmodel", "showcwentities"}, {0x8E, "entitylist", "showcwentities"},
        {0x4B, "keyvaluepairs", "showcwentities"}, {0x57, "scriptbundle", "showcwentities"},
        {0x80, "triggerlist", "showcwtriggers"}, {0xD7, "triggereffectdesc", "showcwtriggers"},
        {0xD8, "triggeractions", "showcwtriggers"},
        {0x3E, "animtree", "showcwai"}, {0x5C, "aimtable", "showcwai"},
        {0x62, "animstatemachine", "showcwai"}, {0x63, "behaviortree", "showcwai"},
        {0x64, "behaviorstatemachine", "showcwai"}, {0xC2, "navinput", "showcwnav"},
        {0x07, "xcollision", "showcwcollision"},
        {0x17, "col_map", "showcwcollision"}, {0x18, "clip_map", "showcwcollision"},
        {0x19, "com_map", "showcwworld"}, {0x1A, "game_map", "showcwworld"},
        {0x1B, "gfx_map", "showcwworld"}, {0xAB, "districts", "showcwworld"},
        {0x75, "navmesh", "showcwnav"}, {0x76, "navvolume", "showcwnav"},
        {0x33, "fx", "showcwfx"}, {0x7F, "staticlevelfxlist", "showcwfx"}
    };
}

bool GameBlackOpsCW::ExportResearchPool(const CoDRawFile_t* Asset, const std::string& ExportPath, bool Radiant, const std::function<void(uint32_t, const std::string&)>& Progress)
{
    using namespace TerrainResearch;
    if (!CoDAssets::GameInstance || !BOCWDBAssetPoolsOffset) return false;
    const CWResearchPool* Target = nullptr;
    for (const auto& P : CWResearchPools) if (P.Index == Asset->ResearchPoolIndex) Target = &P;
    if (!Target) return false;
    Radiant = Target->Index == 0x18 && (Radiant || SettingsManager::GetSetting("cwradiantbrushes", "false") == "true");
    if (Radiant && !CWRadiantExport::Available()) { if(Progress)Progress(0,"Missing brush_export runtime beside Greyhound.exe.");return false; }
    if(Radiant && Progress)Progress(0,"Capturing collision payloads and direct brush placements...");
    const auto Root = FileSystems::CombinePath(ExportPath, Radiant ? std::string("diagnostics") : Strings::Format("cw_pool_%03X_%llu",
        Target->Index, GetTickCount64()));
    // Reserve a new directory; never mix evidence from separate exports.
    if (!CreateDirectoryA(Root.c_str(), nullptr)) return false;
    Capture C(Root, {});
    C.Report["schema"] = "greyhound-cw-pool-evidence-v1";
    C.Report["pool_name_candidate"] = Target->Name;
    C.Report["pool_index"] = Target->Index;
    C.Report["enum_source"] = "https://github.com/ProjectDonetsk/T9/blob/048a1a0d7ca75ccb190a45a32c7882e4ac1e3ebb/hook_lib/Main.hpp";
    C.Report["layout_status"] = "opaque headers; enum/build compatibility unverified";
    C.Report["payloads_captured"] = false;
    C.Report["unresolved"] = {"nested payload layouts", "slot occupancy", "BO3 reconstruction"};
    const uint64_t Descriptor = BOCWDBAssetPoolsOffset + sizeof(BOCWXAssetPoolData) * Target->Index;
    const auto Start = C.Span(Descriptor, sizeof(BOCWXAssetPoolData), "descriptor_start.bin", "pool descriptor including free-list head");
    BOCWXAssetPoolData P{};
    if (Start.size() != sizeof(P)) { C.Finish(); return false; }
    memcpy(&P, Start.data(), sizeof(P));
    const uint64_t Bytes = uint64_t(P.AssetSize) * P.PoolSize;
    const bool Valid = Pointer(P.PoolPtr) && P.AssetSize >= 8 && P.AssetSize <= 65536 &&
        P.PoolSize && P.AssetsLoaded <= P.PoolSize && Bytes <= Capture::SpanLimit &&
        Bytes <= 0x0000800000000000ull - P.PoolPtr;
    C.Report["pool"] = {{"address", Hex(P.PoolPtr)}, {"asset_size", P.AssetSize},
        {"capacity", P.PoolSize}, {"loaded", P.AssetsLoaded}, {"requested_bytes", Bytes},
        {"free_head", Hex(P.PoolFreeHeadPtr)}, {"descriptor_valid", Valid}};
    std::vector<uint8_t> Headers;
    if (Valid) Headers = C.Span(P.PoolPtr, Bytes, "headers.bin",
        "full capacity including free slots; headers only, pointers are not portable payloads");
    const bool Probe = SettingsManager::GetSetting("cwprobepayloads", "false") == "true";
    const bool DeepProbe = Probe && SettingsManager::GetSetting("cwdeepProbe", "false") == "true";
    const bool MapData = Radiant || SettingsManager::GetSetting("cwmapdata", "false") == "true";
    const bool AutoTypes=Radiant && SettingsManager::GetSetting("cwradianttypes","true")=="true";
    CWBrushTypeCapture::Types TypeCapture;
    bool TypesComplete=!AutoTypes;
    C.Report["capture_sections"] = {{"entities_triggers", !Radiant && SettingsManager::GetSetting("cwcaptureentities", "true")=="true"},
        {"model_placements", !Radiant && SettingsManager::GetSetting("cwcaptureplacements", "true")=="true"},
        {"model_splines", !Radiant && SettingsManager::GetSetting("cwcapturesplines", "false")=="true"},
        {"collision_payloads", Radiant || SettingsManager::GetSetting("cwcapturecollision", "true")=="true"},
        {"typed_capture_enabled", MapData || DeepProbe}};
    C.Report["probe"] = {{"enabled", Probe}, {"recursive", false},
        {"slot_limit", 256}, {"unique_address_limit", 256}, {"prefix_byte_limit", 4096},
        {"occupancy", "unknown; sampled slots may be free"},
        {"interpretation", "aligned address-like words only; no pointer or count semantics verified"},
        {"candidates", json::array()}};
    if ((DeepProbe || MapData) && !Headers.empty())
    {
        const auto Occupancy = CWPoolProbe::FreeSlots(Headers, P.AssetSize, P.PoolPtr,
            P.PoolFreeHeadPtr, P.AssetsLoaded);
        if (Occupancy.Valid && P.AssetsLoaded == 1)
            for (uint32_t S = 0; S < P.PoolSize; ++S)
                if (!Occupancy.Free.count(S))
                {
                    const auto First = Headers.begin() + size_t(S) * P.AssetSize;
                    const std::vector<uint8_t> Slot(First, First + P.AssetSize);
                    if(AutoTypes)TypeCapture.Begin(C,BOCWDBAssetPoolsOffset,Slot);
                    if (!Radiant && SettingsManager::GetSetting("cwcaptureentities", "true")=="true")
                        CWMapCandidateCapture::Capture(C, Target->Index, Slot);
                    if (!Radiant && SettingsManager::GetSetting("cwcaptureplacements", "true")=="true")
                        CWMapWorldCapture::Capture(C, Target->Index, Slot);
                    if (!Radiant && SettingsManager::GetSetting("cwcapturesplines", "false")=="true")
                        CWSplineCapture::Capture(C, Target->Index, Slot);
                    if (Radiant || SettingsManager::GetSetting("cwcapturecollision", "true")=="true")
                        CWClipMapCapture::Capture(C, Target->Index, Slot);
                }
        C.Report["headers_readback_unchanged"]=C.VerifySpan(P.PoolPtr,Headers,"headers.bin");
        if(AutoTypes)TypesComplete=TypeCapture.Finish(C);
        if(MapData)
            C.Report["map_data_status"]=(C.Report.contains("typed_candidates")
                || C.Report.contains("gfx_map_static_models")
                || C.Report.contains("district_static_models")
                || C.Report.contains("collision_arrays") || C.Report.contains("model_splines"))
                ? "candidate_capture_attempted" : "unsupported_layout_or_occupancy";
    }
    if (DeepProbe && !MapData && !Headers.empty())
    {
        CWPoolProbe::Graph Graph;
        const auto Occupancy = CWPoolProbe::FreeSlots(Headers, P.AssetSize, P.PoolPtr,
            P.PoolFreeHeadPtr, P.AssetsLoaded);
        uint32_t Scanned = 0;
        for (uint32_t S = 0; S < P.PoolSize && Scanned < 256; ++S)
        {
            if (Occupancy.Valid && Occupancy.Free.count(S)) continue;
            const auto First = Headers.begin() + size_t(S) * P.AssetSize;
            Graph.Scan(std::vector<uint8_t>(First, First + P.AssetSize),
                P.PoolPtr + uint64_t(S) * P.AssetSize, 1, 8);
            ++Scanned;
        }
        C.Report["capture_sections"] = {{"entities_triggers", !Radiant && SettingsManager::GetSetting("cwcaptureentities", "true")=="true"},
        {"model_placements", !Radiant && SettingsManager::GetSetting("cwcaptureplacements", "true")=="true"},
        {"model_splines", !Radiant && SettingsManager::GetSetting("cwcapturesplines", "false")=="true"},
        {"collision_payloads", Radiant || SettingsManager::GetSetting("cwcapturecollision", "true")=="true"},
        {"typed_capture_enabled", MapData || DeepProbe}};
    C.Report["probe"] = {{"enabled", true}, {"recursive", true},
            {"mode", "bounded_pointer_graph"}, {"depth_limit", CWPoolProbe::Graph::DepthLimit},
            {"prefix_byte_limit", CWPoolProbe::Graph::PrefixBytes},
            {"unique_address_limit", CWPoolProbe::Graph::NodeLimit},
            {"edge_limit", CWPoolProbe::Graph::EdgeLimit}, {"slots_scanned", Scanned},
            {"slots_omitted", (Occupancy.Valid ? P.AssetsLoaded : P.PoolSize) - Scanned},
            {"occupancy", Occupancy.Valid ? "free-list shape and count validated; non-atomic" : "unknown; includes potentially free slots"},
            {"interpretation", "candidate pointer graph; array lengths, types and ownership unverified"},
            {"nodes", json::array()}, {"edges", json::array()}};
        for (size_t I = 0; I < Graph.Queue.size(); ++I)
        {
            // Copy: Scan may grow/reallocate Queue.
            const auto Address = Graph.Queue[I].first;
            const auto Depth = Graph.Queue[I].second;
            json N = {{"address", Hex(Address)}, {"depth", Depth}, {"status", "query_failed"}};
            MEMORY_BASIC_INFORMATION M{};
            if (VirtualQueryEx(CoDAssets::GameInstance->GetCurrentProcess(),
                reinterpret_cast<const void*>(Address), &M, sizeof(M)))
            {
                const auto Base = reinterpret_cast<uint64_t>(M.BaseAddress);
                N["region"] = {{"base", Hex(Base)}, {"bytes", M.RegionSize},
                    {"protection", M.Protect}, {"state", M.State}, {"type", M.Type}};
                // Never traverse code/image mappings as candidate asset payloads.
                const auto Access = M.Protect & 0xFF;
                if (M.Type == MEM_IMAGE || Access == PAGE_EXECUTE || Access == PAGE_EXECUTE_READ ||
                    Access == PAGE_EXECUTE_READWRITE || Access == PAGE_EXECUTE_WRITECOPY)
                    N["status"] = "image_or_executable_mapping_skipped";
                else if (Base <= Address && M.RegionSize <= UINT64_MAX - Base && Base + M.RegionSize > Address)
                {
                    const auto Size = std::min<uint64_t>(CWPoolProbe::Graph::PrefixBytes, Base + M.RegionSize - Address);
                    const auto File = "graph_" + Hex(Address) + ".bin";
                    const auto Data = C.Span(Address, Size, File,
                        "bounded speculative prefix; includes potentially unrelated adjacent bytes", false, "speculative");
                    N["status"] = C.Report["reads"].back()["status"];
                    N["file"] = C.Report["reads"].back()["file"];
                    N["requested_bytes"] = Size;
                    N["read_bytes"] = C.Report["reads"].back()["read_bytes"];
                    if (!Data.empty()) Graph.Scan(Data, Address, Depth + 1);
                }
                else N["status"] = "invalid_region";
            }
            C.Report["probe"]["nodes"].push_back(N);
        }
        for (const auto& E : Graph.Edges)
            C.Report["probe"]["edges"].push_back({{"parent_address", Hex(E.Parent)},
                {"field_offset", E.Offset}, {"address", Hex(E.Address)}, {"depth", E.Depth}});
        C.Report["probe"]["address_limit_reached"] = Graph.NodeLimitReached;
        C.Report["probe"]["edge_limit_reached"] = Graph.EdgeLimitReached;
    }
    else if (Probe && !MapData && !Headers.empty())
    {
        const auto Plan = CWPoolProbe::Plan(Headers, P.AssetSize);
        C.Report["probe"]["slots_scanned"] = Plan.Slots;
        C.Report["probe"]["slots_omitted"] = P.PoolSize - Plan.Slots;
        C.Report["probe"]["address_limit_reached"] = Plan.LimitReached;
        for (const auto& Candidate : Plan.Candidates)
        {
            json R = {{"slot", Candidate.Slot}, {"header_offset", Candidate.Offset},
                {"parent_address", Hex(P.PoolPtr + uint64_t(Candidate.Slot) * P.AssetSize)},
                {"address", Hex(Candidate.Address)}, {"status", "query_failed"}};
            MEMORY_BASIC_INFORMATION M{};
            if (VirtualQueryEx(CoDAssets::GameInstance->GetCurrentProcess(),
                reinterpret_cast<const void*>(Candidate.Address), &M, sizeof(M)))
            {
                const auto Base = reinterpret_cast<uint64_t>(M.BaseAddress);
                if (Base <= Candidate.Address && M.RegionSize <= UINT64_MAX - Base &&
                    Base + M.RegionSize > Candidate.Address)
                {
                    const auto Size = std::min<uint64_t>(4096, Base + M.RegionSize - Candidate.Address);
                    const auto File = "probe_" + Hex(Candidate.Address) + ".bin";
                    C.Span(Candidate.Address, Size, File,
                        "unverified one-hop prefix; may include unrelated adjacent bytes", false, "speculative");
                    R["status"] = C.Report["reads"].back()["status"];
                    R["file"] = File;
                    R["requested_bytes"] = Size;
                    R["read_bytes"] = C.Report["reads"].back()["read_bytes"];
                }
                else R["status"] = "invalid_region";
            }
            C.Report["probe"]["candidates"].push_back(R);
        }
    }
    const auto End = C.Span(Descriptor, sizeof(P), "descriptor_end.bin", "descriptor stability check", true);
    C.Report["descriptor_unchanged"] = End.size() == Start.size() && End == Start;
    C.Report["header_pool_complete"] = Valid && Headers.size() == Bytes;
    C.Report["coverage"] = MapData
        ? "headers and counted entity/trigger candidate arrays with readback; no speculative graph or complete asset claim"
        : DeepProbe
        ? "headers and bounded two-hop candidate graph; no complete payload or decoded asset claim"
        : Probe
        ? "headers and bounded speculative prefixes; no complete payload or decoded asset claim"
        : "headers only; no collision meshes, brushes, entities or navigation decoded";
    bool ReadsSaved = TypesComplete;
    if (C.Report.contains("typed_candidates") &&
        (!C.Report["typed_candidates"].value("saved", false) || !C.Report["typed_candidates"].value("complete", false))) ReadsSaved = false;
    if(C.Report.contains("headers_readback_unchanged") && !C.Report["headers_readback_unchanged"].get<bool>()) ReadsSaved=false;
    const bool CollisionOnly = Radiant || MapData && Target->Index == 0x18 &&
        SettingsManager::GetSetting("cwcapturecollision", "true") == "true" &&
        SettingsManager::GetSetting("cwcaptureentities", "true") == "false" &&
        SettingsManager::GetSetting("cwcaptureplacements", "true") == "false" &&
        SettingsManager::GetSetting("cwcapturesplines", "false") == "false";
    const bool DistrictPlacements = MapData && Target->Index == 0xAB &&
        C.Report.contains("district_static_models");
    if (CollisionOnly)
    {
        for (const auto* Section : {"clip_models", "collision_arrays", "collision_world_instances"})
            if (!C.Report.contains(Section) || !C.Report[Section].value("saved", false)) ReadsSaved = false;
        if (!C.Report.value("clip_models", json::object()).value("all_payloads_verified", false) ||
            !C.Report.value("collision_arrays", json::object()).value("readback_unchanged", false) ||
            C.Report.value("collision_world_instances", json::object()).value("status", "") != "captured") ReadsSaved = false;
        C.Report["coverage"] = "Verified collision payloads and direct collision-instance ownership; optional descriptor probes are not required; no decoded brush or BO3 compile claim";
    }
    else if (DistrictPlacements)
    {
        const auto& Districts = C.Report["district_static_models"];
        ReadsSaved = ReadsSaved && Districts.value("saved", false) && Districts.value("complete", false);
        C.Report["coverage"] = "Validated live/local-package district XModel placements; source proxies retained; no runtime visibility claim";
    }
    else if(MapData && !C.Report.contains("typed_candidates")) ReadsSaved=false;
    for (const auto& Read : C.Report["reads"])
        if (Read.value("status", "") == "write_failed" ||
            (!(DistrictPlacements && Read.value("file", "").rfind("typed/district_", 0) == 0) &&
                Read.value("budget_lane", "") != "speculative" && Read.value("status", "") != "captured" &&
                Read.value("status", "") != "reused_file")) ReadsSaved = false;
    C.Report["required_reads_saved"] = ReadsSaved;
    const bool Saved = C.Finish();
    const bool Complete = Saved && ReadsSaved && Valid && Headers.size() == Bytes && End == Start;
    if (DistrictPlacements) CoDAssets::LatestExportPath = Root;
    if(!Complete || !Radiant) return Complete;
    std::string MapPath;uint64_t MapHash=0;
    try { std::ifstream In(FileSystems::CombinePath(Root,"collision_world_instances.json"));json Owners;In>>Owners;
        MapHash=std::stoull(Owners.at("map_hash").get<std::string>(),nullptr,16);
        MapPath=CWMapEntityExport::ResolveHash(MapHash);
    } catch(const std::exception&) {return false;}
    std::string TriggerCapture;
    if(SettingsManager::GetSetting("cwradiantvolumes","true")=="true")
    {
        if(Progress)Progress(0,"Capturing this map's trigger and volume source data...");
        TriggerCapture=FileSystems::CombinePath(Root,"trigger_capture");
        if(!CWBrushTypeCapture::Volumes(TriggerCapture,BOCWDBAssetPoolsOffset,MapHash))return false;
    }
    const auto Output=ExportPath;
    CoDAssets::LatestExportPath=Root;
    const bool Converted=CWRadiantExport::Run(Root,Output,MapPath,Progress,AutoTypes,TriggerCapture);
    if(Converted)CoDAssets::LatestExportPath=Output;
    return Converted;
}

bool GameBlackOpsCW::LoadAssets()
{
    // Prepare to load game assets, into the AssetPool
    bool NeedsAnims     = (SettingsManager::GetSetting("showxanim",     "true")         == "true");
    bool NeedsModels    = (SettingsManager::GetSetting("showxmodel",    "true")         == "true");
    bool NeedsImages    = (SettingsManager::GetSetting("showximage",    "false")        == "true");
    bool NeedsRawFiles  = (SettingsManager::GetSetting("showxrawfiles", "false")        == "true");
    bool NeedsMaterials = (SettingsManager::GetSetting("showxmtl",      "false")        == "true");
    bool NeedsSounds    = (SettingsManager::GetSetting("showxsounds",   "false")        == "true");
    bool NeedsTerrains  = (SettingsManager::GetSetting("showxterrain",  "true")         == "true");
    bool NeedsExtInfo   = (SettingsManager::GetSetting("needsextinfo",  "true")         == "true");

    /*
        This was implemented as a fix for a specific user who requested it, as the search box is capped at 32767 by Windows
        and this is a workaround, if you're interested in using it, any hashes in this filters file will be ignored on load,
        essentially acting as an excluder, consider it a hidden feature with no support as it was made for a specific use
        case. If you cannot get it to work, do not ask me.
    */
    auto Filters = WraithNameIndex();
    Filters.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(), "package_index\\bocw_filters.wni"));

    // One row per populated research pool. Free slots are not advertised as assets.
    if (BOCWDBAssetPoolsOffset)
    for (const auto& Target : CWResearchPools)
    {
        if (SettingsManager::GetSetting(Target.Setting, "false") != "true") continue;
        auto P = CoDAssets::GameInstance->Read<BOCWXAssetPoolData>(
            BOCWDBAssetPoolsOffset + sizeof(BOCWXAssetPoolData) * Target.Index);
        if (!TerrainResearch::Pointer(P.PoolPtr) || !P.AssetsLoaded || P.AssetsLoaded > P.PoolSize ||
            P.AssetSize < 8 || P.AssetSize > 65536) continue;
        auto Row = new CoDRawFile_t();
        Row->ResearchPoolIndex = Target.Index;
        Row->AssetName = Strings::Format("cw_pool_%03X_%s_headers", Target.Index, Target.Name);
        Row->AssetPointer = P.PoolPtr;
        Row->AssetStatus = WraithAssetStatus::Loaded;
        CoDAssets::GameAssets->LoadedAssets.push_back(Row);
    }

    // Check if we need assets
    if (NeedsAnims)
    {
        // Parse the XAnim pool
        CoDXPoolParser<uint64_t, BOCWXAnim>((CoDAssets::GameOffsetInfos[0]), CoDAssets::GamePoolSizes[0], [Filters, NeedsExtInfo](BOCWXAnim& Asset, uint64_t& AssetOffset)
        {
            // Mask the name as hashes are 60Bit
            Asset.NamePtr &= 0xFFFFFFFFFFFFFFF;

            // Check for filters
            if (Filters.NameDatabase.size() > 0)
            {
                // Check for this asset in DB
                if (Filters.NameDatabase.find(Asset.NamePtr) != Filters.NameDatabase.end())
                {
                    // Skip this asset
                    return;
                }
            }

            // Validate and load if need be
            auto AnimName = Strings::Format("xanim_%llx", Asset.NamePtr);

            // Check for an override in the name DB
            if (AssetNameCache.NameDatabase.find(Asset.NamePtr) != AssetNameCache.NameDatabase.end())
            {
                auto& NewName = AssetNameCache.NameDatabase[Asset.NamePtr];

                if (CoDAssets::VerifiedHashes)
                {
                    if (CWCalculateHash(NewName) == Asset.NamePtr)
                    {
                        AnimName = NewName;
                    }
                }
                else
                {
                    AnimName = NewName;
                }
            }

            // Log it
            CoDAssets::LogXAsset("Anim", AnimName);

            // Make and add
            auto LoadedAnim = new CoDAnim_t();
            // Set
            LoadedAnim->AssetName    = AnimName;
            LoadedAnim->AssetPointer = AssetOffset;
            LoadedAnim->Framerate    = Asset.Framerate;
            LoadedAnim->FrameCount   = Asset.NumFrames;
            LoadedAnim->BoneCount    = Asset.TotalBoneCount;
            LoadedAnim->ShapeCount   = (uint32_t) * (uint16_t*)&Asset.Unknown[0];
            LoadedAnim->AssetStatus  = WraithAssetStatus::Loaded;

            // Parse bone names if requested
            if (NeedsExtInfo)
            {
                for (size_t i = 0; i < LoadedAnim->BoneCount; i++)
                {
                    auto BoneIndex = CoDAssets::GameInstance->Read<uint32_t>(Asset.BoneIDsPtr + i * 4);

                    LoadedAnim->BoneNames.emplace_back(CoDAssets::GameStringHandler(BoneIndex));
                }
            }

            // Add
            CoDAssets::GameAssets->LoadedAssets.push_back(LoadedAnim);
        });
    }

    if (NeedsModels)
    {
        // Parse the XModel pool
        CoDXPoolParser<uint64_t, BOCWXModel>((CoDAssets::GameOffsetInfos[1]), CoDAssets::GamePoolSizes[1], [Filters, NeedsExtInfo](BOCWXModel& Asset, uint64_t& AssetOffset)
        {
            // Mask the name as hashes are 60Bit
            Asset.NamePtr &= 0xFFFFFFFFFFFFFFF;

            // Check for filters
            if (Filters.NameDatabase.size() > 0)
            {
                // Check for this asset in DB
                if (Filters.NameDatabase.find(Asset.NamePtr) != Filters.NameDatabase.end())
                {
                    // Skip this asset
                    return;
                }
            }

            // XSkeleton for bone info
            auto XSkeleton = CoDAssets::GameInstance->Read<BOCWXSkeleton>(Asset.XSkeletonPtr);

            // Validate and load if need be
            auto& ModelName = Strings::Format("xmodel_%llx", Asset.NamePtr);

            // Check for an override in the name DB
            if (AssetNameCache.NameDatabase.find(Asset.NamePtr) != AssetNameCache.NameDatabase.end())
            {
                auto& NewName = AssetNameCache.NameDatabase[Asset.NamePtr];

                if (CoDAssets::VerifiedHashes)
                {
                    if (CWCalculateHash(NewName) == Asset.NamePtr)
                    {
                        ModelName = NewName;
                    }
                }
                else
                {
                    ModelName = NewName;
                }
            }

            // Log it
            CoDAssets::LogXAsset("Model", ModelName);

            // Make and add
            auto LoadedModel = new CoDModel_t();
            // Set
            LoadedModel->AssetName         = ModelName;
            LoadedModel->AssetPointer      = AssetOffset;
            LoadedModel->BoneCount         = XSkeleton.BoneCounts[0] + XSkeleton.BoneCounts[1];
            LoadedModel->LodCount          = Asset.NumLods;
            LoadedModel->AssetStatus       = WraithAssetStatus::Loaded;
            // Parse bone names if requested
            if (NeedsExtInfo)
            {
                for (size_t i = 0; i < LoadedModel->BoneCount; i++)
                {
                    auto BoneIndex = CoDAssets::GameInstance->Read<uint32_t>(XSkeleton.BoneIDsPtr + i * 4);

                    LoadedModel->BoneNames.emplace_back(CoDAssets::GameStringHandler(BoneIndex));
                }
            }

            // Add
            CoDAssets::GameAssets->LoadedAssets.push_back(LoadedModel);
        });
    }

    if (NeedsImages)
    {
        // Parse the XModel pool
        CoDXPoolParser<uint64_t, BOCWGfxImage>((CoDAssets::GameOffsetInfos[2]), CoDAssets::GamePoolSizes[2], [Filters](BOCWGfxImage& Asset, uint64_t& AssetOffset)
        {
            // Mask the name as hashes are 60Bit
            Asset.NamePtr &= 0xFFFFFFFFFFFFFFF;

            // Check for filters
            if (Filters.NameDatabase.size() > 0)
            {
                // Check for this asset in DB
                if (Filters.NameDatabase.find(Asset.NamePtr) != Filters.NameDatabase.end())
                {
                    // Skip this asset
                    return;
                }
            }

            // Validate and load if need be
            auto ImageName = Strings::Format("ximage_%llx", Asset.NamePtr);

            // Check for an override in the name DB
            if (AssetNameCache.NameDatabase.find(Asset.NamePtr) != AssetNameCache.NameDatabase.end())
            {
                auto& NewName = AssetNameCache.NameDatabase[Asset.NamePtr];

                if (CoDAssets::VerifiedHashes)
                {
                    if (CWCalculateHash(NewName) == Asset.NamePtr)
                    {
                        ImageName = NewName;
                    }
                }
                else
                {
                    ImageName = NewName;
                }
            }

            // Log it
            CoDAssets::LogXAsset("Image", ImageName);

            // Check for loaded images
            // if (Asset.GfxMipsPtr != 0)
            {
                // Make and add
                auto LoadedImage = new CoDImage_t();
                // Set
                LoadedImage->AssetName    = ImageName;
                LoadedImage->AssetPointer = AssetOffset;
                LoadedImage->Width        = (uint16_t)Asset.LoadedMipWidth;
                LoadedImage->Height       = (uint16_t)Asset.LoadedMipHeight;
                LoadedImage->Format       = (uint16_t)Asset.ImageFormat;
                LoadedImage->AssetStatus  = WraithAssetStatus::Loaded;
                LoadedImage->Streamed     = Asset.GfxMipsPtr != 0;
                // Add
                CoDAssets::GameAssets->LoadedAssets.push_back(LoadedImage);
            }
        });
    }

    if (NeedsMaterials)
    {
        // Parse the XModel pool
        CoDXPoolParser<uint64_t, BOCWXMaterial>((CoDAssets::GameOffsetInfos[3]), CoDAssets::GamePoolSizes[3], [Filters](BOCWXMaterial& Asset, uint64_t& AssetOffset)
        {
            // Mask the name as hashes are 60Bit
            Asset.NamePtr &= 0xFFFFFFFFFFFFFFF;

            // Check for filters
            if (Filters.NameDatabase.size() > 0)
            {
                // Check for this asset in DB
                if (Filters.NameDatabase.find(Asset.NamePtr) != Filters.NameDatabase.end())
                {
                    // Skip this asset
                    return;
                }
            }

            // Validate and load if need be
            auto MaterialName = Strings::Format("xmaterial_%llx", Asset.NamePtr);

            // Check for an override in the name DB
            if (AssetNameCache.NameDatabase.find(Asset.NamePtr) != AssetNameCache.NameDatabase.end())
            {
                auto& NewName = AssetNameCache.NameDatabase[Asset.NamePtr];

                if (CoDAssets::VerifiedHashes)
                {
                    if (CWCalculateHash(NewName) == Asset.NamePtr)
                    {
                        MaterialName = NewName;
                    }
                }
                else
                {
                    MaterialName = NewName;
                }
            }

            // Log it
            CoDAssets::LogXAsset("Material", MaterialName);

            // Make and add
            auto LoadedImage = new CoDMaterial_t();
            // Set
            LoadedImage->AssetName    = MaterialName;
            LoadedImage->AssetPointer = AssetOffset;
            LoadedImage->ImageCount   = Asset.ImageCount;
            LoadedImage->AssetStatus  = WraithAssetStatus::Loaded;
            // Add
            CoDAssets::GameAssets->LoadedAssets.push_back(LoadedImage);
        });
    }

    if (NeedsSounds)
    {
        // Parse the XModel pool
        CoDXPoolParser<uint64_t, BOCWSoundAsset>((CoDAssets::GameOffsetInfos[4]), CoDAssets::GamePoolSizes[4], [](BOCWSoundAsset& Asset, uint64_t& AssetOffset)
        {
            // Mask the name as hashes are 60Bit
            Asset.NamePtr &= 0xFFFFFFFFFFFFFFF;

            // Validate and load if need be
            auto SoundName = Strings::Format("xsound_%llx", Asset.NamePtr);

            // Check for an override in the name DB
            if (AssetNameCache.NameDatabase.find(Asset.NamePtr) != AssetNameCache.NameDatabase.end())
            {
                auto& NewName = AssetNameCache.NameDatabase[Asset.NamePtr];

                if (CoDAssets::VerifiedHashes)
                {
                    if (CWCalculateHash(NewName) == Asset.NamePtr)
                    {
                        SoundName = NewName;
                    }
                }
                else
                {
                    SoundName = NewName;
                }
            }

            // Log it
            CoDAssets::LogXAsset("Sound", SoundName);

            // Make and add
            auto LoadedSound = new CoDSound_t();
            // Set the name, but remove all extensions first
            LoadedSound->AssetName    = FileSystems::GetFileNamePurgeExtensions(SoundName);
            LoadedSound->FullPath     = FileSystems::GetDirectoryName(SoundName);
            LoadedSound->AssetPointer = AssetOffset;
            LoadedSound->AssetStatus  = WraithAssetStatus::Loaded;
            // Set various properties
            LoadedSound->FrameRate     = GetFrameRate(Asset.FrameRateIndex);
            LoadedSound->FrameCount    = Asset.FrameCount;
            LoadedSound->ChannelsCount = Asset.ChannelCount;
            LoadedSound->AssetSize     = -1;
            LoadedSound->AssetStatus   = WraithAssetStatus::Loaded;
            LoadedSound->IsFileEntry   = false;
            LoadedSound->Length        = (uint32_t)(1000.0f * (float)(LoadedSound->FrameCount / (float)(LoadedSound->FrameRate)));
            // Add
            CoDAssets::GameAssets->LoadedAssets.push_back(LoadedSound);
           
        });
    }

    if (NeedsTerrains && TerrainGfxPoolPtr != 0 &&
        TerrainGfxAssetSize >= sizeof(uint64_t) && TerrainGfxAssetSize <= 0x10000 &&
        TerrainGfxPoolSize > 0)
    {
        const uint64_t PoolBytes = static_cast<uint64_t>(TerrainGfxAssetSize) * TerrainGfxPoolSize;
        const uint64_t MaximumPoolOffset = TerrainGfxPoolPtr + PoolBytes;

        if (PoolBytes <= MaximumTerrainPoolBytes && MaximumPoolOffset > TerrainGfxPoolPtr)
        {
            uintptr_t BytesRead = 0;
            auto PoolBuffer = CoDAssets::GameInstance->Read(TerrainGfxPoolPtr, static_cast<uintptr_t>(PoolBytes), BytesRead);

            if (PoolBuffer != nullptr && BytesRead == PoolBytes)
            {
                for (uint32_t i = 0; i < TerrainGfxPoolSize; i++)
                {
                    const uint64_t AssetOffset = TerrainGfxPoolPtr + static_cast<uint64_t>(i) * TerrainGfxAssetSize;
                    uint64_t NameHash = 0;
                    std::memcpy(&NameHash, PoolBuffer + static_cast<size_t>(i) * TerrainGfxAssetSize, sizeof(NameHash));

                    // Free slots use the first qword as an in-pool linked-list pointer.
                    if (NameHash == 0 || (NameHash > TerrainGfxPoolPtr && NameHash < MaximumPoolOffset))
                        continue;

                    NameHash &= 0xFFFFFFFFFFFFFFF;
                    auto TerrainName = Strings::Format("terraingfx_%llx", NameHash);

                    if (AssetNameCache.NameDatabase.find(NameHash) != AssetNameCache.NameDatabase.end())
                    {
                        auto& NewName = AssetNameCache.NameDatabase[NameHash];
                        if (!CoDAssets::VerifiedHashes || CWCalculateHash(NewName) == NameHash)
                            TerrainName = NewName;
                    }

                    CoDAssets::LogXAsset("TerrainGfx", TerrainName);

                    auto LoadedTerrain = new CoDTerrain_t();
                    LoadedTerrain->AssetName = TerrainName;
                    LoadedTerrain->AssetPointer = AssetOffset;
                    LoadedTerrain->AssetSize = TerrainGfxAssetSize;
                    LoadedTerrain->AssetStatus = WraithAssetStatus::Loaded;
                    CoDAssets::GameAssets->LoadedAssets.push_back(LoadedTerrain);
                }
            }

            delete[] PoolBuffer;
        }
    }

    // Success, error only on specific load
    return true;
}

std::unique_ptr<XAnim_t> GameBlackOpsCW::ReadXAnim(const CoDAnim_t* Animation)
{
    // TODO: Look at streamed XAnims

    // Verify that the program is running
    if (CoDAssets::GameInstance->IsRunning())
    {
        // Prepare to read the xanim
        auto Anim = std::make_unique<XAnim_t>();
        // Read the XAnim structure
        auto AnimData = CoDAssets::GameInstance->Read<BOCWXAnim>(Animation->AssetPointer);
        // Copy over default properties
        Anim->AnimationName = Animation->AssetName;
        // Frames and Rate
        Anim->FrameCount = AnimData.NumFrames;
        Anim->FrameRate = AnimData.Framerate;

        //// Check for viewmodel animations
        //if ((_strnicmp(Animation->AssetName.c_str(), "viewmodel_", 10) == 0) || (_strnicmp(Animation->AssetName.c_str(), "vm_", 3) == 0))
        //{
        //    // This is a viewmodel animation
        //    Anim->ViewModelAnimation = true;
        //}
        ////// Check for additive animations
        ////if (AnimData.AssetType == 0x6)
        ////{
        ////    // This is a additive animation
        ////    Anim->AdditiveAnimation = true;
        ////}
        ////// Check for looping
        ////Anim->LoopingAnimation = (AnimData.LoopingFlag > 0);

        // Read the delta data
        auto AnimDeltaData = CoDAssets::GameInstance->Read<BO4XAnimDeltaParts>(AnimData.DeltaPartsPtr);

        // Copy over pointers
        Anim->BoneIDsPtr          = AnimData.BoneIDsPtr;
        Anim->DataBytesPtr        = AnimData.DataBytePtr;
        Anim->DataShortsPtr       = AnimData.DataShortPtr;
        Anim->DataIntsPtr         = AnimData.DataIntPtr;
        Anim->RandomDataBytesPtr  = AnimData.RandomDataBytePtr;
        Anim->RandomDataShortsPtr = AnimData.RandomDataShortPtr;
        Anim->NotificationsPtr    = AnimData.NotificationsPtr;

        // Bone ID index size
        Anim->BoneIndexSize = 4;

        // Copy over counts
        Anim->NoneRotatedBoneCount            = AnimData.NoneRotatedBoneCount;
        Anim->TwoDRotatedBoneCount            = AnimData.TwoDRotatedBoneCount;
        Anim->NormalRotatedBoneCount          = AnimData.NormalRotatedBoneCount;
        Anim->TwoDStaticRotatedBoneCount      = AnimData.TwoDStaticRotatedBoneCount;
        Anim->NormalStaticRotatedBoneCount    = AnimData.NormalStaticRotatedBoneCount;
        Anim->NormalTranslatedBoneCount       = AnimData.NormalTranslatedBoneCount;
        Anim->PreciseTranslatedBoneCount      = AnimData.PreciseTranslatedBoneCount;
        Anim->StaticTranslatedBoneCount       = AnimData.StaticTranslatedBoneCount;
        Anim->NoneTranslatedBoneCount         = AnimData.NoneTranslatedBoneCount;
        Anim->TotalBoneCount                  = AnimData.TotalBoneCount;
        Anim->NotificationCount               = AnimData.NotificationCount;
        Anim->BlendShapeNamesPtr              = AnimData.UnknownPtr;
        Anim->BlendShapeWeightsPtr            = AnimData.UnknownZero1;
        Anim->BlendShapeWeightCount           = (uint32_t)*(uint16_t*)&AnimData.Unknown[0];

        // Copy delta
        Anim->DeltaTranslationPtr = AnimDeltaData.DeltaTranslationsPtr;
        Anim->Delta2DRotationsPtr = AnimDeltaData.Delta2DRotationsPtr;
        Anim->Delta3DRotationsPtr = AnimDeltaData.Delta3DRotationsPtr;

        // Set types, we use quata for BO4
        Anim->RotationType = AnimationKeyTypes::QuatPackingA;
        Anim->TranslationType = AnimationKeyTypes::MinSizeTable;

        // Black Ops CW doesn't support inline indicies
        Anim->SupportsInlineIndicies = false;

        // Return it
        return Anim;
    }
    // Not running
    return nullptr;
}

std::unique_ptr<XModel_t> GameBlackOpsCW::ReadXModel(const CoDModel_t* Model)
{
    // Verify that the program is running
    if (CoDAssets::GameInstance->IsRunning())
    {
        // Read the XModel structure
        auto ModelData = CoDAssets::GameInstance->Read<BOCWXModel>(Model->AssetPointer);
        // XSkeleton for bone info
        auto XSkeleton = CoDAssets::GameInstance->Read<BOCWXSkeleton>(ModelData.XSkeletonPtr);

        // Prepare to read the xmodel (Reserving space for lods)
        auto ModelAsset = std::make_unique<XModel_t>(ModelData.NumLods);

        // Copy over default properties
        ModelAsset->ModelName = Model->AssetName;
        // Bone counts
        ModelAsset->BoneCount = XSkeleton.BoneCounts[1];
        ModelAsset->RootBoneCount = XSkeleton.BoneCounts[2];
        ModelAsset->CosmeticBoneCount = XSkeleton.BoneCounts[0];

        // Bone data type
        ModelAsset->BoneRotationData = BoneDataTypes::QuatPackingA;

        // We are streamed
        ModelAsset->IsModelStreamed = true;

        // Bone id info
        ModelAsset->BoneIDsPtr = XSkeleton.BoneIDsPtr;
        ModelAsset->BoneIndexSize = 4;

        // Bone parent info
        ModelAsset->BoneParentsPtr = XSkeleton.ParentListPtr;
        ModelAsset->BoneParentSize = 2;

        // Local bone pointers
        ModelAsset->RotationsPtr = XSkeleton.RotationsPtr;
        ModelAsset->TranslationsPtr = XSkeleton.TranslationsPtr;

        // Global matricies
        ModelAsset->BaseMatriciesPtr = XSkeleton.BaseMatriciesPtr;

        // Prepare to parse lods
        for (uint32_t i = 0; i < ModelData.NumLods; i++)
        {
            // Read the lod
            auto LODInfo = CoDAssets::GameInstance->Read<BOCWXModelLod>(ModelData.ModelLodPtrs[i]);
            // Create the lod and grab reference
            ModelAsset->ModelLods.emplace_back(LODInfo.NumSurfs);
            // Grab reference
            auto& LodReference = ModelAsset->ModelLods[i];

            // Set distance
            LodReference.LodDistance = LODInfo.LodDistance;

            // Set stream key and info ptr
            LodReference.LODStreamKey = LODInfo.LODStreamKey;
            LodReference.LODStreamInfoPtr = LODInfo.XModelMeshPtr;

            // Grab pointer from the lod itself
            auto XSurfacePtr = LODInfo.XSurfacePtr;

            // Skip 8 bytes in materials
            ModelData.MaterialHandlesPtr += 8;
            // Read material handles ptr
            auto MaterialHandlesPtr = CoDAssets::GameInstance->Read<uint64_t>(ModelData.MaterialHandlesPtr);
            // Advance 8 and skip 24 bytes
            ModelData.MaterialHandlesPtr += 0x18;

            // Load surfaces
            for (uint32_t s = 0; s < LODInfo.NumSurfs; s++)
            {
                // Create the surface and grab reference
                LodReference.Submeshes.emplace_back();
                // Grab reference
                auto& SubmeshReference = LodReference.Submeshes[s];

                // Read the surface data
                auto SurfaceInfo = CoDAssets::GameInstance->Read<BOCWXModelSurface>(XSurfacePtr);
                // Apply surface info
                SubmeshReference.VertexCount = SurfaceInfo.VertexCount;
                SubmeshReference.FaceCount = SurfaceInfo.FacesCount;
                SubmeshReference.VertexPtr = SurfaceInfo.VerticiesIndex;
                SubmeshReference.FacesPtr = SurfaceInfo.FacesIndex;

                // Assign weight info to the count slots, to save memory
                SubmeshReference.WeightCounts[0] = SurfaceInfo.Flag1;
                SubmeshReference.WeightCounts[1] = SurfaceInfo.Flag2;
                //SubmeshReference.WeightCounts[2] = SurfaceInfo.Flag3;
                //SubmeshReference.WeightCounts[3] = SurfaceInfo.Flag4;

                // Read this submesh's material handle
                auto MaterialHandle = CoDAssets::GameInstance->Read<uint64_t>(MaterialHandlesPtr);
                // Create the material and add it
                LodReference.Materials.emplace_back(ReadXMaterial(MaterialHandle));

                // Advance
                XSurfacePtr += sizeof(BOCWXModelSurface);
                MaterialHandlesPtr += sizeof(uint64_t);
            }
        }

        // Return it
        return ModelAsset;
    }
    // Not running
    return nullptr;
}

std::unique_ptr<XImageDDS> GameBlackOpsCW::ReadXImage(const CoDImage_t* Image)
{
    // Proxy off
    return LoadXImage(XImage_t(ImageUsageType::DiffuseMap, 0, Image->AssetPointer, Image->AssetName));
}

std::unique_ptr<XSound> GameBlackOpsCW::ReadXSound(const CoDSound_t * Sound)
{
    // Read the Sound Asset structure
    auto SoundData = CoDAssets::GameInstance->Read<BOCWSoundAsset>(Sound->AssetPointer);
    // Buffer
    std::unique_ptr<uint8_t[]> SoundBuffer = nullptr;

    // Offset to the data, depending on the buffer
    uint32_t OpusDataSize       = 0;
    uint32_t OpusDataOffset     = 0;
    uint32_t OpusConsumed       = 0;
    uint32_t PCMDataSize        = 0;

    // Check if we need raw data or standard xpak
    if (SoundData.StreamKey != 0)
    {
        // Load raw buffer, these aren't compressed
        uint32_t SoundMemoryResult = 0;
        SoundBuffer = CoDAssets::GamePackageCache->ExtractPackageObjectRaw(SoundData.StreamKey, SoundMemoryResult);

        if (SoundMemoryResult == 0)
            return nullptr;

        OpusDataSize = SoundMemoryResult;
    }
    else
    {
        // Extract buffer, these are compressed
        uint32_t SoundMemoryResult = 0;
        SoundBuffer = CoDAssets::GamePackageCache->ExtractPackageObject(CoDAssets::GameInstance->Read<uint64_t>(SoundData.StreamInfoPtr + 0x8), SoundMemoryResult);

        if (SoundMemoryResult == 0)
            return nullptr;

        OpusDataSize = *(uint32_t*)(SoundBuffer.get() + 280);
        OpusDataOffset = 288;
    }

    
    if(SoundBuffer == nullptr)
        return nullptr;

    // Initialize Opus
    int ErrorCode;
    auto Decoder = opus_decoder_create(GetFrameRate(SoundData.FrameRateIndex), SoundData.ChannelCount, &ErrorCode);

    if (ErrorCode != OPUS_OK)
        return nullptr;

    // Create new buffer for each 960 frame block
    auto PCMBuffer = std::make_unique<opus_int16[]>(960 * 2 * (size_t)SoundData.ChannelCount);

    // Output Writer (Note: Frame Count in Asset isn't 100% accurate, so we add on some padding
    //                      to account for 960 frame split so that we can avoid realloc)
    MemoryWriter TempWriter((SoundData.FrameCount + 4096) * 2 * SoundData.ChannelCount);

    // Consume Opus Data
    while (OpusConsumed < OpusDataSize)
    {
        uint32_t BlockSize = *(uint32_t*)(SoundBuffer.get() + OpusConsumed + OpusDataOffset);
        OpusConsumed += 4;

        auto DecoderResult = opus_decode(
            Decoder,
            (SoundBuffer.get() + OpusConsumed + OpusDataOffset),
            BlockSize,
            PCMBuffer.get(),
            960,
            0);

        // Any negative is a failure in Opus
        if (DecoderResult < 0)
            return nullptr;

        // Output to Buffer
        TempWriter.Write((uint8_t*)PCMBuffer.get(), 960 * 2 * SoundData.ChannelCount);

        // Advance Info
        OpusConsumed       += BlockSize;
        PCMDataSize        += 960 * 2 * SoundData.ChannelCount;
    }

    // Prepare to read the sound data, for WAV, we must include a WAV header...
    auto Result = std::make_unique<XSound>();

    // The offset of which to store the data
    uint32_t DataOffset = 0;

    // We'll convert all BOCW sounds to 16bit PCM WAV
    Result->DataBuffer = new int8_t[PCMDataSize + (size_t)Sound::GetMaximumWAVHeaderSize()];
    Result->DataType = SoundDataTypes::WAV_WithHeader;
    Result->DataSize = (uint32_t)(PCMDataSize + Sound::GetMaximumWAVHeaderSize());

    DataOffset += Sound::GetMaximumWAVHeaderSize();

    // Make the header
    Sound::WriteWAVHeaderToStream(Result->DataBuffer, (uint32_t)Sound->FrameRate, (uint32_t)Sound->ChannelsCount, PCMDataSize);

    // Copy output
    std::memcpy(Result->DataBuffer + DataOffset, TempWriter.GetCurrentStream(), PCMDataSize);

    return Result;
}

#pragma pack(push, 1)
struct BOCWXMaterialImage
{
    uint64_t ImagePtr;
    uint32_t SemanticHash;
    uint8_t Padding[0xC];
};
#pragma pack(pop)

struct BOCWMaterialTechniqueSet
{
    uint64_t Hash;
    uint64_t Hash2;
    uint64_t Flags;
    uint64_t Passed[18];
};

struct BOCWMaterialTechnique
{
    uint64_t Hash;
    uint8_t Padding[32];
    uint64_t ShadersPtr;
};

struct BOCWMaterialTechniqueShader
{
    uint64_t Hash;
    uint64_t ShaderPtr;
    uint64_t ShaderSize;
};

#pragma pack(push, 1)
struct BOCWXMaterialEx
{
    uint64_t NamePtr;
    uint8_t Padding[0x20];
    uint64_t TechsetPtr;
    uint64_t ImageTablePtr;
    uint64_t UnkPtr;
    uint64_t MaterialInstanceDataPtr;
    uint8_t Padding1[96];
    uint64_t PerPassBuffers[13];
    uint64_t CBuffersSize;
    uint64_t CBuffersPtr;
    uint8_t Padding2[40];
    uint8_t ImageCount;
    uint8_t Padding3[15];
};
#pragma pack(pop)

const XMaterial_t GameBlackOpsCW::ReadXMaterial(uint64_t MaterialPointer)
{
    // Prepare to parse the material
    auto MaterialData = CoDAssets::GameInstance->Read<BOCWXMaterialEx>(MaterialPointer);
    // Mask the name (some bits are used for other stuffs)
    MaterialData.NamePtr &= 0xFFFFFFFFFFFFFFF;
    // Allocate a new material with the given image count
    XMaterial_t Result(MaterialData.ImageCount);
    // Clean the name, then apply it
    Result.MaterialName = Strings::Format("xmaterial_%llx", MaterialData.NamePtr);
    // Clean the tech name, then apply it
    Result.TechsetName = Strings::Format("xtechset_%llx", CoDAssets::GameInstance->Read<uint64_t>(MaterialData.TechsetPtr));

    // Check for an override in the name DB
    if (AssetNameCache.NameDatabase.find(MaterialData.NamePtr) != AssetNameCache.NameDatabase.end())
        Result.MaterialName = FileSystems::GetFileNamePurgeExtensions(AssetNameCache.NameDatabase[MaterialData.NamePtr]);

    // Iterate over material images, assign proper references if available
    for (uint32_t m = 0; m < MaterialData.ImageCount; m++)
    {
        // Read the image info
        auto ImageInfo = CoDAssets::GameInstance->Read<BOCWXMaterialImage>(MaterialData.ImageTablePtr);

        // Get Hash and mask it (some bits are used for other stuffs)
        auto ImageHash = CoDAssets::GameInstance->Read<uint64_t>(ImageInfo.ImagePtr) & 0xFFFFFFFFFFFFFFF;

        // Get the image name
        auto ImageName = Strings::Format("ximage_%llx", ImageHash);

        // Check for an override in the name DB
        if (AssetNameCache.NameDatabase.find(ImageHash) != AssetNameCache.NameDatabase.end())
            ImageName = AssetNameCache.NameDatabase[ImageHash];

        // Default type
        auto DefaultUsage = ImageUsageType::Unknown;
        // Check 
        switch (ImageInfo.SemanticHash)
        {
        case 0xA0AB1041:
            DefaultUsage = ImageUsageType::DiffuseMap;
            break;
        case 0x59D30D0F:
            DefaultUsage = ImageUsageType::NormalMap;
            break;
        case 0xEC443804:
            DefaultUsage = ImageUsageType::SpecularMap;
            break;
        }

        // Assign the new image
        Result.Images.emplace_back(DefaultUsage, ImageInfo.SemanticHash, ImageInfo.ImagePtr, ImageName);

        // Advance
        MaterialData.ImageTablePtr += sizeof(BOCWXMaterialImage);
    }

    // Grab pixel shader for this pass, as it'll contain the most useful reflection info.
    // We also need to determine if this is a deferred or foward material by pointer, it's the
    // easiest way.
    auto TechSetData = CoDAssets::GameInstance->Read<BOCWMaterialTechniqueSet>(MaterialData.TechsetPtr);
    auto TechSetPassIndex = TechSetData.Passed[6] != 0 ? 6 : 8;
    auto TechSetPassData = CoDAssets::GameInstance->Read<BOCWMaterialTechnique>(TechSetData.Passed[TechSetPassIndex]);
    auto PixelShader = CoDAssets::GameInstance->Read<BOCWMaterialTechniqueShader>(CoDAssets::GameInstance->Read<uint64_t>(TechSetPassData.ShadersPtr + 24));
    auto PixelShaderBuffer = std::make_unique<uint8_t[]>(PixelShader.ShaderSize);
    auto PixelShaderSize = CoDAssets::GameInstance->Read(PixelShaderBuffer.get(), PixelShader.ShaderPtr, PixelShader.ShaderSize);

    // We take 2 different paths, for forward materials, we'll need to resolve their types
    // via reflection, but for GBuffer it's a lot simpler due to the constant data
    // so we can skip shader stuff for gbuffer materials, and skip a lot of useless
    // info within gbuffer instance info and get exact stuff we want like tints and 
    // ranges
    // Still need to look into it more, but it seems to be correct to do this
    if (TechSetPassIndex == 6)
    {
        // Start DXC
        IDxcLibrary* library = nullptr;
        ID3D12ShaderReflection* reflection{};
        IDxcContainerReflection* pReflection{};
        IDxcBlobEncoding* blob = nullptr;
        ID3D12ShaderReflection* ppReflection{};
        UINT32 shaderIdx = 0;
        D3D12_SHADER_DESC desc{};

        // Ensure we're init
        if (!FAILED(DXCDLLSupport.Initialize()) &&
            !FAILED(DXCDLLSupport.CreateInstance(CLSID_DxcContainerReflection, &pReflection)) &&
            !FAILED(DXCDLLSupport.CreateInstance(CLSID_DxcLibrary, &library)) &&
            !FAILED(library->CreateBlobWithEncodingFromPinned(PixelShaderBuffer.get(), PixelShader.ShaderSize, 0, &blob)) &&
            !FAILED(pReflection->Load(blob)) &&
            !FAILED(pReflection->FindFirstPartKind(hlsl::DFCC_ShaderStatistics, &shaderIdx)) &&
            !FAILED(pReflection->GetPartReflection(shaderIdx, __uuidof(ID3D12ShaderReflection), (void**)&ppReflection)) &&
            !FAILED(ppReflection->GetDesc(&desc)))
        {
            ID3D12ShaderReflectionConstantBuffer* constBuf = ppReflection->GetConstantBufferByName("$Globals");

            D3D12_SHADER_BUFFER_DESC bufDesc{};
            D3D12_SHADER_VARIABLE_DESC varDesc{};
            D3D12_SHADER_TYPE_DESC typeDesc{};

            if (!FAILED(constBuf->GetDesc(&bufDesc)))
            {
                auto CBuffers = std::make_unique<uint8_t[]>(MaterialData.CBuffersSize);
                auto CBuffersSize = CoDAssets::GameInstance->Read(CBuffers.get(), MaterialData.CBuffersPtr, MaterialData.CBuffersSize);
                auto CBufferOffset = CoDAssets::GameInstance->Read<uint32_t>(CoDAssets::GameInstance->Read<uint64_t>(MaterialData.PerPassBuffers[TechSetPassIndex] + 16));

                for (UINT i = 0; i < bufDesc.Variables; i++)
                {
                    auto variable = constBuf->GetVariableByIndex(i);

                    // From what we know in BO3, Treyarch generate these from Techsets
                    // and therefore we assume they can only be certain types with no nested
                    // structures, etc.
                    if (!FAILED(variable->GetDesc(&varDesc)) && !FAILED(variable->GetType()->GetDesc(&typeDesc)))
                    {
                        switch (typeDesc.Type)
                        {
                        case D3D_SVT_BOOL:
                        case D3D_SVT_FLOAT:
                            Result.Settings.emplace_back(
                                varDesc.Name,
                                "float",
                                (float*)(CBuffers.get() + CBufferOffset + varDesc.StartOffset),
                                typeDesc.Columns);
                            break;
                        case D3D_SVT_INT:
                            Result.Settings.emplace_back(
                                varDesc.Name,
                                "int",
                                (int32_t*)(CBuffers.get() + CBufferOffset + varDesc.StartOffset),
                                typeDesc.Columns);
                            break;
                        case D3D_SVT_UINT:
                            Result.Settings.emplace_back(
                                varDesc.Name,
                                "uint",
                                (uint32_t*)(CBuffers.get() + CBufferOffset + varDesc.StartOffset),
                                typeDesc.Columns);
                            break;
                        }
                    }
                }
            }
#if _DEBUG
            else
            {
                printf("WARNING: Failed to get $Globals for material: %s\n", Result.MaterialName.c_str());
            }
#endif
        }
    }
    else
    {
        auto MaterialInstanceData = std::make_unique<uint8_t[]>(220);
        auto MaterialInstanceDataSize = CoDAssets::GameInstance->Read(MaterialInstanceData.get(), MaterialData.MaterialInstanceDataPtr, 220);

        Result.Settings.emplace_back(
            "colorTint",
            "float3",
            (float*)(MaterialInstanceData.get() + 8),
            3);
        Result.Settings.emplace_back(
            "specColorTint",
            "float3",
            (float*)(MaterialInstanceData.get() + 40),
            3);
        Result.Settings.emplace_back(
            "perceptualRoughnessRange",
            "float2",
            (float*)(MaterialInstanceData.get() + 44),
            2);
    }


    // Return it
    return Result;
}

std::unique_ptr<XImageDDS> GameBlackOpsCW::LoadXImage(const XImage_t& Image)
{
    // Prepare to load an image, we need to rip loaded and streamed ones
    uint32_t ResultSize = 0;

    // We must read the image data
    auto ImageInfo = CoDAssets::GameInstance->Read<BOCWGfxImage>(Image.ImagePtr);

    // Every streamed mip the package cache can serve, largest first.  This is a
    // fallback chain rather than a single choice: Exists() only says the object
    // is indexed, and extraction can still fail, in which case a smaller mip or
    // the mip resident in game memory is worth far more than the silent skip
    // this used to produce.  The first entry is the same mip the old
    // single-pass selection picked, so a working image is unaffected.
    struct MipCandidate
    {
        uint64_t Hash;
        uint32_t Size;
        uint32_t Width;
        uint32_t Height;
    };
    std::vector<MipCandidate> MipCandidates;

    // Loop and collect
    for (uint32_t i = 0; i < ImageInfo.GfxMipMaps; i++)
    {
        // Load Mip Map
        auto MipMap = CoDAssets::GameInstance->Read<BOCWGfxMip>(ImageInfo.GfxMipsPtr);
        // Checking it exists covers users without HD Texture Packs
        if (MipMap.HashID != 0 && CoDAssets::GamePackageCache->Exists(MipMap.HashID))
        {
            MipCandidates.push_back(MipCandidate{
                MipMap.HashID,
                MipMap.Size,
                (uint32_t)(ImageInfo.LoadedMipWidth >> (ImageInfo.GfxMipMaps - i - 1)),
                (uint32_t)(ImageInfo.LoadedMipHeight >> (ImageInfo.GfxMipMaps - i - 1)) });
        }
        // Advance Mip Map Pointer
        ImageInfo.GfxMipsPtr += sizeof(BOCWGfxMip);
    }

    // Largest first, keeping the original order among equal sizes
    std::stable_sort(MipCandidates.begin(), MipCandidates.end(),
        [](const MipCandidate& Left, const MipCandidate& Right) { return Left.Size > Right.Size; });

    uint32_t LargestWidth = 0;
    uint32_t LargestHeight = 0;

    // Calculate proper image format (Convert signed to unsigned)
    switch (ImageInfo.ImageFormat)
    {
    // Fix invalid BC1_SRGB images, swap to BC1_UNORM
    case 72: ImageInfo.ImageFormat = 71; break;
    // Fix invalid BC2_SRGB images, swap to BC2_UNORM
    case 75: ImageInfo.ImageFormat = 74; break;
    // Fix invalid BC3_SRGB images, swap to BC3_UNORM
    case 78: ImageInfo.ImageFormat = 77; break;
    // Fix invalid BC7_SRGB images, swap to BC7_UNORM
    case 99: ImageInfo.ImageFormat = 98; break;
    }

    // Buffer
    std::unique_ptr<uint8_t[]> ImageData = nullptr;

    // We have a streamed image, prepare to extract, dropping to the next mip
    // down whenever an indexed object cannot actually be read back
    for (auto& Candidate : MipCandidates)
    {
        ImageData = CoDAssets::GamePackageCache->ExtractPackageObject(Candidate.Hash, ResultSize);

        // Take the first one that yields data
        if (ImageData != nullptr && ResultSize > 0)
        {
            LargestWidth = Candidate.Width;
            LargestHeight = Candidate.Height;
            break;
        }

        // Try the next mip down
        ImageData = nullptr;
        ResultSize = 0;
    }

    // Nothing streamed could be served, so fall back to the mip resident in
    // game memory.  This used to run only when no mip was indexed at all, which
    // meant an image whose indexed mip failed to extract was dropped outright.
    if (ImageData == nullptr)
    {
        // Set sizes
        LargestWidth = ImageInfo.LoadedMipWidth;
        LargestHeight = ImageInfo.LoadedMipHeight;

        // Temporary size
        uintptr_t ImageMemoryResult = 0;
        // We have a loaded image, prepare to dump from memory
        auto ImageMemoryBuffer = CoDAssets::GameInstance->Read(ImageInfo.LoadedMipPtr, ImageInfo.LoadedMipSize, ImageMemoryResult);

        // Make sure we got it, and got something.  A read that succeeds with
        // zero bytes -- the image's memory is no longer resident -- used to
        // produce a non-null, empty buffer, and from there a DDS with a header
        // and no surface that every converter rightly refuses.
        if (ImageMemoryBuffer != nullptr)
        {
            if (ImageMemoryResult > 0)
            {
                // Allocate a safe block
                ImageData = std::make_unique<uint8_t[]>((uint32_t)ImageMemoryResult);
                // Copy data over
                std::memcpy(ImageData.get(), ImageMemoryBuffer, ImageMemoryResult);

                // Set size
                ResultSize = (uint32_t)ImageMemoryResult;
            }

            // Clean up
            delete[] ImageMemoryBuffer;
        }
    }

    // Prepare if we have it.  No pixels is not an image: reporting the failure
    // is what lets the caller record why, instead of writing a surfaceless DDS.
    if (ImageData != nullptr && ResultSize > 0)
    {
        // Prepare to create a MemoryDDS file
        auto Result = CoDRawImageTranslator::TranslateBC(ImageData, ResultSize, LargestWidth, LargestHeight, ImageInfo.ImageFormat);

        // Check for, and apply patch if required, if we got a raw result
        if (Result != nullptr && Image.ImageUsage == ImageUsageType::NormalMap && (SettingsManager::GetSetting("patchnormals", "true") == "true"))
        {
            // Set normal map patch
            Result->ImagePatchType = ImagePatch::Normal_Expand;
        }

        // Return it
        return Result;
    }

    // Failed to load the image
    return nullptr;
}

struct BlendShapeTargetInfo
{
    uint32_t Name;
    uint32_t Index;
};

struct BlendShapeVertexInfo
{
    uint32_t Offset;
    uint32_t Count;
};

struct BlendShapeVertex
{
    uint16_t VertexIndex;
    uint16_t X;
    uint16_t Y;
    uint16_t Z;
};

void GameBlackOpsCW::LoadXModel(const XModelLod_t& ModelLOD, const std::unique_ptr<WraithModel>& ResultModel)
{
    // Check if we want Vertex Colors
    bool ExportColors = (SettingsManager::GetSetting("exportvtxcolor", "true") == "true");
    // Read the mesh information
    auto MeshInfo = CoDAssets::GameInstance->Read<BOCWXModelMeshInfo>(ModelLOD.LODStreamInfoPtr);

    // A buffer for the mesh data
    std::unique_ptr<uint8_t[]> MeshDataBuffer = nullptr;
    // Resulting size
    uint64_t MeshDataBufferSize = 0;

    // Vertex has extended vertex information
    bool HasExtendedVertexInfo = (MeshInfo.StatusFlag & 64) != 0;

    // Determine if we need to load the mesh or not (Seems flag == 8 is loaded)
    if ((MeshInfo.StatusFlag & 0x3F) == 8)
    {
        // Result size
        uintptr_t ResultSize = 0;
        // The mesh is already loaded, just read it
        auto TemporaryBuffer = CoDAssets::GameInstance->Read(MeshInfo.XModelMeshBufferPtr, MeshInfo.XModelMeshBufferSize, ResultSize);

        // Copy and clean up
        if (TemporaryBuffer != nullptr)
        {
            // Allocate safe
            MeshDataBuffer = std::make_unique<uint8_t[]>(MeshInfo.XModelMeshBufferSize);
            // Copy over
            std::memcpy(MeshDataBuffer.get(), TemporaryBuffer, (size_t)ResultSize);
            // Set size
            MeshDataBufferSize = ResultSize;

            // Clean up
            delete[] TemporaryBuffer;
        }
    }
    else
    {
        // Result size
        uint32_t ResultSize = 0;
        // We must read from the cache
        MeshDataBuffer = CoDAssets::GamePackageCache->ExtractPackageObject(ModelLOD.LODStreamKey, ResultSize);
        // Set size
        MeshDataBufferSize = ResultSize;
    }

    // Continue on success
    if (MeshDataBuffer != nullptr)
    {
        // Make a reader to begin reading the mesh (Don't close)
        auto MeshReader = MemoryReader((int8_t*)MeshDataBuffer.get(), MeshDataBufferSize, true);
        // The total weighted verticies
        // uint32_t TotalReadWeights = 0;
        // Prepare it for submeshes
        ResultModel->PrepareSubmeshes((uint32_t)ModelLOD.Submeshes.size());

        // Start by reading blendshape info
        auto Vertices = std::make_unique<std::vector<std::pair<uint32_t, Vector3>>[]>(MeshInfo.VertexCount);

        if (MeshInfo.BlendShapeIndexes != 0 && MeshInfo.BlendShapeCounts != 0)
        {
            for (size_t i = 0; i < ((size_t)MeshInfo.ShapeCount + (size_t)MeshInfo.FuckKnowsAgain); i++)
            {
                auto TargetInfo = CoDAssets::GameInstance->Read<BlendShapeTargetInfo>(MeshInfo.BlendShapeIndexes + i * sizeof(BlendShapeTargetInfo));
                auto VertexInfo = CoDAssets::GameInstance->Read<BlendShapeVertexInfo>(MeshInfo.BlendShapeCounts + TargetInfo.Index * sizeof(BlendShapeVertexInfo));

                // TODO: It seems like this might be Normal/Tangent data if we hit the same
                // shape again, there must be a flag for it, Blender doesn't support setting them so
                // not sure if it is worth ripping them 
                // See: c_t9_eng_hero_park_head from campaign
                if (TargetInfo.Index >= MeshInfo.ShapeCount)
                    continue;

                // Now we can be sure this is a unique shape, and we're hitting the first instance
                // which will be delta positions
                auto ShapeIndex = ResultModel->BlendShapes.size();
                ResultModel->BlendShapes.push_back(CoDAssets::GameStringHandler(TargetInfo.Name));
                // Jump to vertex position data, advance to this submeshes verticies
                MeshReader.SetPosition(MeshInfo.BlendshapesOffset + (size_t)VertexInfo.Offset);

                for (size_t j = 0; j < (size_t)VertexInfo.Count; j++)
                {
                    auto ValueForVertex = MeshReader.Read<BlendShapeVertex>();

                    auto X = HalfFloats::ToFloat(ValueForVertex.X);
                    auto Y = HalfFloats::ToFloat(ValueForVertex.Y);
                    auto Z = HalfFloats::ToFloat(ValueForVertex.Z);

                    Vertices[ValueForVertex.VertexIndex].push_back(std::make_pair(
                        (uint32_t)ShapeIndex,
                        Vector3(
                        HalfFloats::ToFloat(ValueForVertex.X),
                        HalfFloats::ToFloat(ValueForVertex.Y),
                        HalfFloats::ToFloat(ValueForVertex.Z)
                    )));
                }
            }
        }

        // Iterate over submeshes
        for (auto& Submesh : ModelLOD.Submeshes)
        {
            // Create and grab a new submesh
            auto& Mesh = ResultModel->AddSubmesh();

            // Set the material (COD has 1 per submesh)
            Mesh.AddMaterial(Submesh.MaterialIndex);

            // Prepare the mesh for the data
            Mesh.PrepareMesh(Submesh.VertexCount, Submesh.FaceCount);

            // Jump to vertex position data, advance to this submeshes verticies
            MeshReader.SetPosition(MeshInfo.VertexOffset + (Submesh.VertexPtr * 12));

            // Iterate over verticies
            for (uint32_t i = 0; i < Submesh.VertexCount; i++)
            {
                // Make a new vertex
                auto& Vertex = Mesh.AddVertex();

                // Read and assign position
                Vertex.Position = MeshReader.Read<Vector3>();
                Vertex.BlendShapeDeltas = Vertices[Submesh.VertexPtr + i];
            }

            // Jump to vertex info data, advance to this submeshes info, seek further for extended vertex info
            MeshReader.SetPosition(MeshInfo.UVOffset + (Submesh.VertexPtr * (HasExtendedVertexInfo ? 24 : 16)));

            // Iterate over verticies
            for (uint32_t i = 0; i < Submesh.VertexCount; i++)
            {
                // Grab the reference
                auto& Vertex = Mesh.Verticies[i];

                // Read vertex data
                auto VertexData = MeshReader.Read<GfxStreamVertex>();

                // Add UV layer
                Vertex.AddUVLayer(HalfFloats::ToFloat(VertexData.UVUPosition), HalfFloats::ToFloat(VertexData.UVVPosition));
                // Unpack normal
                Vertex.Normal.X = ((float)(((VertexData.VertexNormal >> 00) & ((1 << 10) - 1)) - 512) / 511.0f);
                Vertex.Normal.Y = ((float)(((VertexData.VertexNormal >> 10) & ((1 << 10) - 1)) - 512) / 511.0f);
                Vertex.Normal.Z = ((float)(((VertexData.VertexNormal >> 20) & ((1 << 10) - 1)) - 512) / 511.0f);

                // Add Colors if we want them
                if (ExportColors)
                {
                    Vertex.Color[0] = VertexData.Color[0];
                    Vertex.Color[1] = VertexData.Color[1];
                    Vertex.Color[2] = VertexData.Color[2];
                    Vertex.Color[3] = VertexData.Color[3];
                }
                else
                {
                    Vertex.Color[0] = 0xFF;
                    Vertex.Color[1] = 0xFF;
                    Vertex.Color[2] = 0xFF;
                    Vertex.Color[3] = 0xFF;
                }

                // Skip extended vertex information (first 4 bytes seems to be UV, possibly for better camo UV Mapping)
                if (HasExtendedVertexInfo)
                    MeshReader.Advance(8);
            }

            // Jump to vertex weight data, advance to this submeshes info
            MeshReader.SetPosition(MeshInfo.WeightsOffset + (Submesh.VertexPtr * 12));

            // Iterate over verticies
            for (uint32_t i = 0; i < Submesh.VertexCount; i++)
            {
                // Grab the reference
                auto& Vertex = Mesh.Verticies[i];
                
                // Check if we're a complex weight, up to four weights
                if (((uint8_t)Submesh.WeightCounts[0] & 2) > 0)
                {
                    // Read weight data
                    auto VertexWeight = MeshReader.Read<GfxStreamWeight>();

                    // Add weights for each index if it exists
                    // Mask off bit, seems to be blendshape related
                    Vertex.AddVertexWeight(VertexWeight.WeightID1 & ~32768, (VertexWeight.WeightVal1 / 255.0f));

                    if (VertexWeight.WeightVal2 > 0)
                        Vertex.AddVertexWeight(VertexWeight.WeightID2 & ~32768, (VertexWeight.WeightVal2 / 255.0f));
                    if (VertexWeight.WeightVal3 > 0)
                        Vertex.AddVertexWeight(VertexWeight.WeightID3 & ~32768, (VertexWeight.WeightVal3 / 255.0f));
                    if (VertexWeight.WeightVal4 > 0)
                        Vertex.AddVertexWeight(VertexWeight.WeightID4 & ~32768, (VertexWeight.WeightVal4 / 255.0f));
                }
                else
                {
                    // Simple weight
                    Vertex.AddVertexWeight(0, 1.0);
                }
            }

            // Jump to face data, advance to this submeshes faces
            MeshReader.SetPosition(MeshInfo.FacesOffset + (Submesh.FacesPtr * 2));

            // Iterate over faces
            for (uint32_t i = 0; i < Submesh.FaceCount; i++)
            {
                // Read data
                auto Face = MeshReader.Read<GfxStreamFace>();

                // Add the face
                Mesh.AddFace(Face.Index1, Face.Index2, Face.Index3);
            }
        }
    }
}

std::string GameBlackOpsCW::LoadStringEntry(uint64_t Index)
{
    // Calculate Offset to String (Offsets[3] = StringTable)
    auto Offset = CoDAssets::GameOffsetInfos[5] + (Index * 16);
    // Read Info
    auto StringHash = CoDAssets::GameInstance->Read<uint64_t>(Offset + 16) & 0xFFFFFFFFFFFFFFF;

    // Attempt to locate string
    auto StringEntry = StringCache.NameDatabase.find(StringHash);

    // Not Encrypted
    if (StringEntry != StringCache.NameDatabase.end())
        return StringEntry->second;
    else
        return Strings::Format("xstring_%llx", StringHash);
}
void GameBlackOpsCW::PerformInitialSetup()
{
    // Load Caches
    AssetNameCache.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(),    "package_index\\fnv1a_xmaterials.wni"));
    AssetNameCache.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(),    "package_index\\fnv1a_ximages.wni"));
    AssetNameCache.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(),    "package_index\\fnv1a_xsounds.wni"));
    AssetNameCache.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(),    "package_index\\fnv1a_xmodels.wni"));
    AssetNameCache.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(),    "package_index\\fnv1a_xanims.wni"));
    StringCache.LoadIndex(FileSystems::CombinePath(FileSystems::GetApplicationPath(),       "package_index\\fnv1a_string.wni"));
    // Prepare to copy the oodle dll
    auto OurPath = FileSystems::CombinePath(FileSystems::GetApplicationPath(), "oo2core_8_win64.dll");
    // Copy if not exists
    if (!FileSystems::FileExists(OurPath))
        FileSystems::CopyFile(FileSystems::CombinePath(FileSystems::GetDirectoryName(CoDAssets::GameInstance->GetProcessPath()), "oo2core_8_win64.dll"), OurPath);
}

std::string GameBlackOpsCW::ExportModelPlacements(const std::string& Directory, const std::function<void(uint32_t)>& Progress)
{
    if(CoDAssets::GameID!=SupportedGames::BlackOpsCW || !CoDAssets::GameInstance || !BOCWDBAssetPoolsOffset) return "Load a supported Cold War map first.";
    TerrainResearch::Capture C(FileSystems::CombinePath(Directory, "diagnostics"),Progress);
    auto Desc=C.Span(BOCWDBAssetPoolsOffset+sizeof(BOCWXAssetPoolData)*0xAB,sizeof(BOCWXAssetPoolData),"district_pool.bin","District pool");
    if(Desc.size()!=sizeof(BOCWXAssetPoolData)) return "District pool unavailable.";
    BOCWXAssetPoolData P{}; memcpy(&P,Desc.data(),sizeof(P));
    if(P.AssetSize!=96 || P.PoolSize>16 || P.AssetsLoaded!=1) return "Unsupported district pool layout or occupancy.";
    auto Headers=C.Span(P.PoolPtr,uint64_t(P.AssetSize)*P.PoolSize,"district_headers.bin","District headers");
    if(Headers.size()!=uint64_t(P.AssetSize)*P.PoolSize) return "District headers unreadable.";
    auto Occupancy=CWPoolProbe::FreeSlots(Headers,P.AssetSize,P.PoolPtr,P.PoolFreeHeadPtr,P.AssetsLoaded);
    if(!Occupancy.Valid) return "District occupancy unavailable.";
    for(uint32_t I=0;I<P.PoolSize;++I) if(!Occupancy.Free.count(I))
    {
        std::vector<uint8_t> Slot(Headers.begin()+I*P.AssetSize,Headers.begin()+(I+1)*P.AssetSize);
        CWMapWorldCapture::CaptureDistricts(C,0xAB,Slot);
    }
    const bool SourceStable = C.VerifySpan(BOCWDBAssetPoolsOffset+sizeof(BOCWXAssetPoolData)*0xAB, Desc, "district_pool.bin") &&
        C.VerifySpan(P.PoolPtr, Headers, "district_headers.bin");
    auto D=C.Report.value("district_static_models",TerrainResearch::json::object());
    D["complete"] = D.value("complete",false) && SourceStable;
    C.Report["district_static_models"] = D;
    C.Report["placement_source_unchanged"] = SourceStable;
    C.Finish();
    if(!D.value("saved",false)) return "Placement JSON could not be saved.";
    // Keep the user-facing document a plain array; capture evidence stays in diagnostics.
    std::ifstream Input(FileSystems::CombinePath(FileSystems::CombinePath(Directory, "diagnostics"), "static_models.json"));
    TerrainResearch::json Document;
    Input >> Document;
    Document["complete"] = D.value("complete",false);
    Document["placement_source_unchanged"] = SourceStable;
    if (!Document.contains("StaticModels") || !Document["StaticModels"].is_array())
        return "Placement JSON has no model array.";
    for (auto& Row : Document["StaticModels"])
        ModelExportNaming::PublishPlacementName(Row);
    std::ofstream Output(FileSystems::CombinePath(Directory, "static_models.json"), std::ios::binary);
    Output << Document["StaticModels"].dump(2);
    Output.close();
    if (!Output) return "Placement JSON could not be saved.";
    Document.erase("StaticModels");
    Document.erase("UniqueModels");
    std::ofstream Report(FileSystems::CombinePath(Directory, "placement_report.json"), std::ios::binary);
    Report << Document.dump(2);
    Report.close();
    if (!Report) return "Placements saved, but placement_report.json could not be saved.";
    Progress(100);
    return std::string(D.value("complete",false)?"Complete export: ":"Partial export: ")+std::to_string(D.value("instances",0))+
        " placements saved. " + std::to_string(D.value("recovered_package_districts",0)) +
        " districts recovered from local packages; " + std::to_string(D.value("unresolved_districts",0)) +
        " unresolved. Open static_models.json. Validation details are in placement_report.json.";
}


std::string GameBlackOpsCW::ExportRadiantBrushes(const std::string& Directory, const std::function<void(uint32_t, const std::string&)>& Progress)
{
    if(CoDAssets::GameID!=SupportedGames::BlackOpsCW || !CoDAssets::GameInstance || !BOCWDBAssetPoolsOffset)
        return "Load Game with a Cold War map open first.";
    FileSystems::CreateDirectory(Directory);
    CoDRawFile_t Asset;Asset.ResearchPoolIndex=0x18;
    return ExportResearchPool(&Asset,Directory,true,Progress)
        ? "Brush prefab exported. Open latest export folder for the .map and metadata."
        : "Brush export failed. Check the capture diagnostics and bundled brush_export runtime.";
}
