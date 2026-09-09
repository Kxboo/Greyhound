#include <functional>
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <array>
#include <vector>
#include <functional>

// We need the DBGameAssets and CoDAssetType classes
#include "DBGameAssets.h"
#include "CoDAssetType.h"
#include "WraithModel.h"
#include "WraithNameIndex.h"

// Handles reading from Black Ops CW
class GameBlackOpsCW
{
public:
    static std::string ExportModelPlacements(const std::string& Directory, const std::function<void(uint32_t)>& Progress);

    // -- Game Name Caches
    static WraithNameIndex AssetNameCache;
    static WraithNameIndex StringCache;

    // -- Game functions

    // Loads offsets for Black Ops CW
    static bool LoadOffsets();
    // Loads assets for Black Ops CW
    static bool LoadAssets();
    // Walk the whole DBAssetPools table and report every populated pool.  The
    // terrain work only ever needed pool 0xB1, but decals -- which carry road
    // markings and are composited over the terrain layers -- live in a pool
    // whose index is not known.  Enumerating is how it gets identified.
    static std::string DescribeAssetPools(uint32_t MaximumPoolIndex);
    // Copy one pool's raw asset headers out for offline inspection.  Several
    // pools carry the same name hash as the TerrainGfx asset, so they are
    // per-map terrain siblings; dumping them is how their contents get
    // identified without guessing at a layout.
    static bool DumpAssetPool(uint32_t PoolIndex, const std::string& OutputPath,
        uint32_t MaximumAssets);
    // Follow the (count, pointer) pairs inside one pool's asset header and copy
    // each referenced array out.  The terrain siblings store their real payload
    // behind those pairs, so this is what turns a 72-byte header into data.
    static std::string DumpAssetArrays(uint32_t PoolIndex,
        const std::string& OutputDirectory);
    // Sweep every populated pool: header plus each referenced array.  Finding
    // an unknown format means looking at all of them, not guessing indices.
    static std::string DumpAllPools(uint32_t MaximumPoolIndex,
        const std::string& OutputDirectory);
    // Copy a span of memory at a known address.  Decal records reference their
    // material by raw pointer, and those descriptors live outside any pool we
    // enumerate, so reading them needs the address the record supplies.
    static bool PeekMemory(uint64_t Address, uint32_t Bytes,
        const std::string& OutputPath);
    // Read the name hash at an asset address and look it up in the loaded
    // dictionaries; empty when the hash is not in them.
    static std::string ResolveNameHash(uint64_t Address);
    // Find the terrain decal placement array and export it with its materials.
    // Discovery is by shape, not by a remembered index: a decal record is 48
    // bytes whose +0x20 qword points inside the material pool, which no other
    // array in the scene satisfies.  Returns the manifest JSON.
    static std::string ExportTerrainDecals(const std::string& ExportPath);
    // Additional raw evidence for the source-data contract, with bounded reads,
    // explicit coverage and no reconstructed spline/mesh substituted for source.
    static bool ExportTerrainResearch(const CoDTerrain_t* Terrain,
        const std::string& ExportPath, const std::vector<uint64_t>& ProbeMaterials,
        const std::function<void(uint32_t)>& ReportProgress);

    static bool ExportResearchPool(const CoDRawFile_t* Asset, const std::string& ExportPath, bool Radiant = false, const std::function<void(uint32_t, const std::string&)>& Progress = {});
    static std::string ExportRadiantBrushes(const std::string& Directory, const std::function<void(uint32_t, const std::string&)>& Progress);

    // Reads an XAnim from Black Ops CW
    static std::unique_ptr<XAnim_t> ReadXAnim(const CoDAnim_t* Animation);
    // Reads a XModel from Black Ops CW
    static std::unique_ptr<XModel_t> ReadXModel(const CoDModel_t* Model);
    // Reads a XImage from Black Ops CW
    static std::unique_ptr<XImageDDS> ReadXImage(const CoDImage_t* Image);
    // Reads an XSound from World War 2
    static std::unique_ptr<XSound> ReadXSound(const CoDSound_t* Sound);
    // Reads an XMaterial from it's logical offset in memory
    static const XMaterial_t ReadXMaterial(uint64_t MaterialPointer);
    // Reads an XImageDDS from a image reference from Black Ops CW
    static std::unique_ptr<XImageDDS> LoadXImage(const XImage_t& Image);
    // Loads a streamed XModel lod, streaming from cache if need be
    static void LoadXModel(const XModelLod_t& ModelLOD, const std::unique_ptr<WraithModel>& ResultModel);

    // String Handlers for Black Ops CW
    static std::string LoadStringEntry(uint64_t Index);

    // Perform setup required before ripping
    static void PerformInitialSetup();

private:
    // -- Game offsets databases

    // A list of offsets for Black Ops CW single player
    static std::array<DBGameInfo, 3> SinglePlayerOffsets;

    // -- Game utilities
};
