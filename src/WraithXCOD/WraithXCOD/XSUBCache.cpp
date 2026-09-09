#include "stdafx.h"
#include "XSUBCache.h"
#include "Strings.h"
#include "FileSystems.h"
// We need the game files structs
#include "DBGameFiles.h"

// We need the following classes
#include "FileSystems.h"
#include "Strings.h"
#include "Compression.h"
#include "BinaryReader.h"
#include "MemoryReader.h"
#include "Siren.h"
#include "XSUBObjectLayout.h"

// We need the file system classes.
#include "CoDFileHandle.h"

#pragma pack(push, 1)
struct BOCWXSubHeader
{
    uint32_t Magic;
    uint16_t Unknown1;
    uint16_t Version;
    uint64_t Unknown;
    uint64_t Type;
    uint64_t Size;
    uint8_t UnknownHashes[1896];
    int64_t FileCount;
    int64_t DataOffset;
    int64_t DataSize;
    int64_t HashCount;
    int64_t HashOffset;
    int64_t HashSize;
    int64_t Unknown3;
    int64_t UnknownOffset;
    int64_t Unknown4;
    int64_t IndexCount;
    int64_t IndexOffset;
    int64_t IndexSize;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXSubHashEntry
{
    uint64_t Key;
    uint64_t PackedInfo;
};
#pragma pack(pop)

XSUBCache::XSUBCache()
{
    // Default, attempt to load the siren lib
    Siren::Initialize(L"oo2core_8_win64.dll");
}

XSUBCache::~XSUBCache()
{
    // Clean up if need be
    Siren::Shutdown();
}

void XSUBCache::LoadPackageCache(const std::string& BasePath)
{
    // Call Base function first!
    CoDPackageCache::LoadPackageCache(BasePath);

    // Grab files
    FileSystem->EnumerateFiles("*.xsub", [this](const std::string& name, const size_t size)
    {
        try
        {
            this->LoadPackage(name);
        }
        catch (...)
        {

        }
    });

    // We've finished loading, set status
    this->SetLoadedState();
}

bool XSUBCache::LoadPackage(const std::string& FilePath)
{
#ifdef _DEBUG
    std::cout << "XSUBCache::LoadPackage(): Parsing " << FilePath << "\n";
#endif

    // Call Base function first
    CoDPackageCache::LoadPackage(FilePath);

    // Add to package files
    auto PackageIndex = (uint32_t)PackageFilePaths.size();

    // Open CASC File
    // TODO: Implement read, seek, etc. right in this handle class.
    auto Reader = CoDFileHandle(FileSystem->OpenFile(FilePath, "r"), FileSystem.get());

    // Read the header
    auto Header = Reader.Read<BOCWXSubHeader>();

    // Check if we have data (Type 3 is data, others are just metadata and refs)
    if (Header.Type != 3)
        return true;


    // Verify the magic and offset
    if (Header.Magic == 0x4950414b && Header.HashOffset < Reader.Size())
    {
        // Jump to hash offset
        Reader.Seek(Header.HashOffset, SEEK_SET);
        // Hash result size
        uint64_t HashResult = 0;
        // Read Buffer
        auto Buffer = Reader.Read(Header.HashCount * sizeof(BOCWXSubHashEntry));
        // Read the hash data into a buffer
        auto HashData = MemoryReader((int8_t*)Buffer.release(), Header.HashCount * sizeof(BOCWXSubHashEntry));

        // Loop and setup entries
        for (int64_t i = 0; i < Header.HashCount; i++)
        {
            // Read it
            auto Entry = HashData.Read<BOCWXSubHashEntry>();

            // Prepare a cache entry
            PackageCacheObject NewObject;
            // Set data
            NewObject.Offset = (Entry.PackedInfo >> 32) << 7;
            NewObject.CompressedSize = (Entry.PackedInfo >> 1) & 0x3FFFFFFF;
            NewObject.UncompressedSize = 0;
            NewObject.PackageFileIndex = PackageIndex;

            // Append to database
            CacheObjects.insert(std::make_pair(Entry.Key, NewObject));
        }

        // Append the file path
        PackageFilePaths.push_back(FilePath);

#ifdef _DEBUG
        std::cout << "XSUBCache::LoadPackage(): Added " << FilePath << " to cache.\n";
#endif

        // No issues
        return true;
    }

#ifdef _DEBUG
    std::cout << "XSUBCache::LoadPackage(): Failed to parse package.\n";
#endif

    // Failed
    return false;
}

std::unique_ptr<uint8_t[]> XSUBCache::ExtractPackageObjectRaw(uint64_t CacheID, uint32_t & ResultSize)
{
    // Prepare to extract if found
    if (CacheObjects.find(CacheID) != CacheObjects.end())
    {
        // Aquire lock
        std::lock_guard<std::shared_mutex> Gaurd(ReadMutex);

        // Take cache data, and extract from the XPAK (Uncompressed size = offset of data segment!)
        auto& CacheInfo = CacheObjects[CacheID];
        // Get the XPAK name
        auto& XPAKFileName = PackageFilePaths[CacheInfo.PackageFileIndex];
        // Open CASC File
        auto Reader = CoDFileHandle(FileSystem->OpenFile(XPAKFileName, "r"), FileSystem.get());
        // Hop to the beginning offset
        Reader.Seek(CacheInfo.Offset, SEEK_SET);

        // Allocate just the raw size of the buffer, that's all we're returning
        auto ResultBuffer = Reader.Read(CacheInfo.CompressedSize);

        // Set result size
        ResultSize = (uint32_t)CacheInfo.CompressedSize;
        // Return the safe buffer
        return ResultBuffer;
    }

    // Set
    ResultSize = 0;
    // Failed to find data
    return nullptr;
}

std::unique_ptr<uint8_t[]> XSUBCache::ExtractPackageObject(uint64_t CacheID, uint32_t& ResultSize)
{
    ResultSize = 0;
    std::lock_guard<std::shared_mutex> Guard(ReadMutex);
    const auto Found = CacheObjects.find(CacheID);
    if (Found == CacheObjects.end()) return nullptr;
    const auto& Info = Found->second;
    if (Info.PackageFileIndex >= PackageFilePaths.size()) return nullptr;
    auto Reader = CoDFileHandle(FileSystem->OpenFile(PackageFilePaths[Info.PackageFileIndex], "r"), FileSystem.get());
    if (!Reader.IsValid()) return nullptr;
    const auto FileSize = Reader.Size();
    if (!Info.CompressedSize || Info.Offset > FileSize || Info.CompressedSize > FileSize - Info.Offset)
        return nullptr;
    Reader.Seek(Info.Offset, SEEK_SET);
    if (Reader.Tell() != Info.Offset) return nullptr;
    auto Encoded = Reader.Read(Info.CompressedSize);
    std::vector<XSUBObjectLayout::Block> Blocks;
    if (!Encoded || !XSUBObjectLayout::Parse(Encoded.get(), Info.CompressedSize, Info.Offset, Blocks))
        return nullptr;

    // This decoder returns a uint32-sized object. Bound individual allocations
    // too: a bogus prefix must not request gigabytes before rejection.
    constexpr size_t OutputLimit = 1024ull * 1024 * 1024;
    constexpr size_t LZ4BlockLimit = 0x2400000;
    std::vector<uint8_t> Decoded;
    uint64_t Remaining = Info.UncompressedSize;
    for (const auto& Block : Blocks)
    {
        const uint8_t* Source = Encoded.get() + Block.Offset;
        size_t InputSize = Block.Size, Expected = 0;
        switch (Block.Codec)
        {
        case 0: Expected = InputSize; break;
        case 3: Expected = LZ4BlockLimit; break;
        case 8: case 9:
            Expected = XSUBObjectLayout::U32(Source);
            Source += 4; InputSize -= 4;
            if (!Expected || !InputSize) return nullptr;
            break;
        case 6:
            if (!Remaining || !InputSize) return nullptr;
            Expected = static_cast<size_t>((std::min)(Remaining, uint64_t(262112)));
            Remaining -= Expected;
            break;
        default: continue; // Non-data command/padding, already span-checked.
        }
        if (Expected > OutputLimit - Decoded.size()) return nullptr;
        const auto Before = Decoded.size();
        Decoded.resize(Before + Expected);
        size_t Actual = Expected;
        if (Block.Codec == 0)
        {
            if (InputSize) std::memcpy(Decoded.data() + Before, Source, InputSize);
            Remaining = Remaining >= InputSize ? Remaining - InputSize : 0;
        }
        else if (Block.Codec == 3)
            Actual = Compression::DecompressLZ4Block(reinterpret_cast<const int8_t*>(Source),
                reinterpret_cast<int8_t*>(Decoded.data() + Before), static_cast<int32_t>(InputSize), static_cast<int32_t>(Expected));
        else
            Actual = Siren::Decompress(Source, InputSize, Decoded.data() + Before, Expected);
        if (Block.Codec != 0 && (!Actual || Actual > Expected || (Block.Codec != 3 && Actual != Expected)))
            return nullptr;
        Decoded.resize(Before + Actual);
    }
    if (Decoded.empty()) return nullptr;
    auto Result = std::make_unique<uint8_t[]>(Decoded.size());
    std::memcpy(Result.get(), Decoded.data(), Decoded.size());
    ResultSize = static_cast<uint32_t>(Decoded.size());
    return Result;
}
