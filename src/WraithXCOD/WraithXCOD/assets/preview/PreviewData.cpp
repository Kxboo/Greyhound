#include "stdafx.h"
#include "assets/preview/PreviewData.h"
#include "assets/preview/PreviewImage.h"
#include "assets/CoDAssets.h"
#include "exporters/CoDXModelTranslator.h"
#include "games/cold_war/reader/GameBlackOpsCW.h"
#include "games/cold_war/reader/GameBlackOpsCWAssetLayouts.h"
#include "games/black_ops_4/reader/GameBlackOps4.h"
#include "games/black_ops_4/reader/GameBlackOps4AssetLayouts.h"

#include <array>
#include <cfloat>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <thread>
#include <unordered_map>

namespace PreviewData
{
    namespace
    {
        struct Cancelled {};

        void Check(const std::function<bool()>& cancelled)
        {
            if (cancelled && cancelled()) throw Cancelled{};
        }

        void WaitForCache(CoDPackageCache* cache, const std::function<bool()>& cancelled)
        {
            if (!cache) return;
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(90);
            // HasCacheLoaded also covers the interval between launching a cache
            // thread and that thread setting IsCacheLoading. The owner keeps the
            // cache alive while this cancellable wait runs.
            while (!cache->HasCacheLoaded())
            {
                Check(cancelled);
                if (std::chrono::steady_clock::now() >= deadline)
                    throw std::runtime_error("Game packages are still loading. Try Preview again shortly.");
                std::this_thread::sleep_for(std::chrono::milliseconds(25));
            }
            Check(cancelled);
        }

        struct ColorScope
        {
            bool previous = CoDAssets::PreviewVertexColors;
            ColorScope() { CoDAssets::PreviewVertexColors = true; }
            ~ColorScope() { CoDAssets::PreviewVertexColors = previous; }
        };

        struct Vertex
        {
            float position[3];
            float normal[3];
            float uv[2];
            uint8_t color[4];
        };
        static_assert(sizeof(Vertex) == 36, "Preview wire vertex layout changed");

        size_t Append(Result& result, const void* data, size_t size, const Options& options)
        {
            const size_t padding = (4 - result.bytes.size() % 4) % 4;
            if (result.bytes.size() > options.maxBytes || padding > options.maxBytes - result.bytes.size() ||
                size > options.maxBytes - result.bytes.size() - padding)
                throw std::runtime_error("Asset exceeds the preview buffer limit.");
            result.bytes.insert(result.bytes.end(), padding, 0);
            const auto offset = result.bytes.size();
            if (size) result.bytes.insert(result.bytes.end(), static_cast<const uint8_t*>(data), static_cast<const uint8_t*>(data) + size);
            return offset;
        }

        int AppendImage(Result& result, const DecodedImage& image, const std::string& name, const Options& options)
        {
            auto& textures = result.metadata["textures"];
            const int index = static_cast<int>(textures.size());
            const auto offset = Append(result, image.rgba.data(), image.rgba.size(), options);
            textures.push_back({ {"offset", offset}, {"byteLength", image.rgba.size()},
                {"width", image.width}, {"height", image.height}, {"sourceWidth", image.sourceWidth},
                {"sourceHeight", image.sourceHeight}, {"hasAlpha", image.hasAlpha},
                {"firstSlice", image.firstSlice}, {"name", name}, {"format", "rgba8"} });
            return index;
        }

        bool ValidateGeometry(const WraithModel& model, const XModelLod_t& source, const Options& options,
            const std::function<bool()>& cancelled)
        {
            // Readers currently emit one translated submesh per source submesh.
            // If that contract changes, never silently shift material assignments.
            if (model.Submeshes.size() != source.Submeshes.size()) return false;
            uint64_t vertices = 0, triangles = 0;
            for (size_t i = 0; i < model.Submeshes.size(); ++i)
            {
                Check(cancelled);
                const auto& mesh = model.Submeshes[i];
                // WWII leaves an empty translated slot when a per-surface
                // streamed block is unavailable. Do not present that partial
                // high-detail LOD as complete; try a lower usable candidate.
                if ((source.Submeshes[i].VertexCount && mesh.Verticies.empty()) ||
                    (source.Submeshes[i].FaceCount && mesh.Faces.empty())) return false;
                vertices += mesh.Verticies.size();
                triangles += mesh.Faces.size();
                for (const auto& vertex : mesh.Verticies)
                    if (!std::isfinite(vertex.Position.X) || !std::isfinite(vertex.Position.Y) || !std::isfinite(vertex.Position.Z)) return false;
                for (const auto& face : mesh.Faces)
                    if (face.Index1 >= mesh.Verticies.size() || face.Index2 >= mesh.Verticies.size() || face.Index3 >= mesh.Verticies.size()) return false;
            }
            return FitsGeometry(vertices, triangles, options);
        }

        void Model(Result& result, const CoDModel_t* asset, const Options& options, const std::function<bool()>& cancelled)
        {
            Check(cancelled);
            auto source = CoDAssets::LoadModelForPreview(asset);
            Check(cancelled);
            if (!source) throw std::runtime_error("The game reader could not load this model.");
            if (source->ModelLods.size() > 256 || uint64_t(source->BoneCount) + source->CosmeticBoneCount > 65536 ||
                source->RootBoneCount > uint64_t(source->BoneCount) + source->CosmeticBoneCount)
                throw std::runtime_error("Model metadata exceeds the preview limits.");
            const auto candidates = CandidateLods(source->ModelLods, options);
            if (candidates.empty()) throw std::runtime_error("This model has no nonempty LOD within the preview limits.");

            std::unique_ptr<WraithModel> translated;
            std::vector<XMaterial_t> materials;
            uint32_t lod = 0;
            bool fallback = false;
            for (const auto& candidate : candidates)
            {
                Check(cancelled);
                auto& sourceLod = source->ModelLods[candidate.index];
                // The export translator deduplicates names and rewrites material
                // indices. Save the unmerged source references first.
                auto positionalMaterials = sourceLod.Materials;
                if (sourceLod.Materials.size() > sourceLod.Submeshes.size())
                    sourceLod.Materials.erase(sourceLod.Materials.begin() + sourceLod.Submeshes.size(), sourceLod.Materials.end());
                try
                {
                    translated = CoDXModelTranslator::TranslateXModel(source, candidate.index);
                }
                catch (...)
                {
                    Check(cancelled);
                    translated.reset();
                }
                Check(cancelled);
                if (translated && ValidateGeometry(*translated, sourceLod, options, cancelled))
                {
                    lod = candidate.index;
                    materials = std::move(positionalMaterials);
                    break;
                }
                translated.reset();
                fallback = true;
            }
            if (!translated) throw std::runtime_error("No usable model LOD is available from the game or its packages.");
            // A higher-detail LOD may have been omitted before any data was read.
            for (const auto& sourceLod : source->ModelLods)
            {
                uint64_t faces = 0;
                for (const auto& mesh : sourceLod.Submeshes) faces += mesh.FaceCount;
                if (faces > translated->FaceCount()) fallback = true;
            }
            result.metadata["lod"] = lod;
            result.metadata["sourceLodCount"] = source->ModelLods.size();
            result.metadata["lodFallback"] = fallback;
            result.metadata["vertexStride"] = sizeof(Vertex);
            result.metadata["upAxis"] = "Z";
            result.metadata["meshes"] = nlohmann::json::array();
            std::array<float, 3> minimum = { FLT_MAX, FLT_MAX, FLT_MAX };
            std::array<float, 3> maximum = { -FLT_MAX, -FLT_MAX, -FLT_MAX };
            uint64_t vertices = 0, triangles = 0;
            for (size_t i = 0; i < translated->Submeshes.size(); ++i)
            {
                Check(cancelled);
                const auto& mesh = translated->Submeshes[i];
                if (mesh.Verticies.empty() || mesh.Faces.empty()) continue;
                const auto vertexOffset = result.bytes.size();
                size_t vertexNumber = 0;
                for (const auto& sourceVertex : mesh.Verticies)
                {
                    if ((vertexNumber++ % 4096) == 0) Check(cancelled);
                    Vertex vertex{};
                    vertex.position[0] = sourceVertex.Position.X;
                    vertex.position[1] = sourceVertex.Position.Y;
                    vertex.position[2] = sourceVertex.Position.Z;
                    vertex.normal[0] = sourceVertex.Normal.X;
                    vertex.normal[1] = sourceVertex.Normal.Y;
                    vertex.normal[2] = sourceVertex.Normal.Z;
                    const float normalLength = vertex.normal[0] * vertex.normal[0] + vertex.normal[1] * vertex.normal[1] + vertex.normal[2] * vertex.normal[2];
                    if (!std::isfinite(normalLength) || normalLength < 1e-12f)
                    {
                        vertex.normal[0] = vertex.normal[1] = 0;
                        vertex.normal[2] = 1;
                    }
                    if (!sourceVertex.UVLayers.empty())
                    {
                        vertex.uv[0] = std::isfinite(sourceVertex.UVLayers[0].X) ? sourceVertex.UVLayers[0].X : 0;
                        vertex.uv[1] = std::isfinite(sourceVertex.UVLayers[0].Y) ? sourceVertex.UVLayers[0].Y : 0;
                    }
                    std::memcpy(vertex.color, sourceVertex.Color, sizeof(vertex.color));
                    for (size_t axis = 0; axis < 3; ++axis)
                    {
                        minimum[axis] = (std::min)(minimum[axis], vertex.position[axis]);
                        maximum[axis] = (std::max)(maximum[axis], vertex.position[axis]);
                    }
                    Append(result, &vertex, sizeof(vertex), options);
                }
                const auto indexOffset = result.bytes.size();
                for (const auto& face : mesh.Faces)
                {
                    const uint32_t indices[3] = { face.Index1, face.Index2, face.Index3 };
                    Append(result, indices, sizeof(indices), options);
                }
                const auto* material = MaterialAt(materials, i);
                result.metadata["meshes"].push_back({ {"vertexOffset", vertexOffset}, {"vertexCount", mesh.Verticies.size()},
                    {"indexOffset", indexOffset}, {"indexCount", mesh.Faces.size() * 3}, {"texture", -1},
                    {"materialName", material ? material->MaterialName : "Neutral"}, {"sourceSubmesh", i} });
                vertices += mesh.Verticies.size();
                triangles += mesh.Faces.size();
            }
            translated.reset();
            source.reset();
            result.metadata["vertexCount"] = vertices;
            result.metadata["triangleCount"] = triangles;
            std::array<double, 3> center{}, extent{};
            for (size_t axis = 0; axis < 3; ++axis)
            {
                center[axis] = (double(minimum[axis]) + maximum[axis]) * 0.5;
                extent[axis] = (double(maximum[axis]) - minimum[axis]) * 0.5;
            }
            result.metadata["bounds"] = { {"min", minimum}, {"max", maximum}, {"center", center},
                {"radius", (std::max)(0.001, std::sqrt(extent[0] * extent[0] + extent[1] * extent[1] + extent[2] * extent[2]))} };

            uint64_t textureBytes = 0;
            uint32_t missing = 0;
            std::unordered_map<std::string, int> textureCache;
            for (auto& mesh : result.metadata["meshes"])
            {
                Check(cancelled);
                const auto* material = MaterialAt(materials, mesh["sourceSubmesh"].get<size_t>());
                int texture = -1;
                if (material && CoDAssets::GameXImageHandler)
                {
                    for (const auto& image : material->Images)
                    {
                        if (image.ImageUsage != ImageUsageType::DiffuseMap) continue;
                        Check(cancelled);
                        // Two materials with the same name may reference distinct
                        // images. Only actual image identity participates in reuse.
                        const auto key = std::to_string(image.ImagePtr) + ":" + std::to_string(image.SemanticHash) + ":" + image.ImageName;
                        const auto existing = textureCache.find(key);
                        if (existing != textureCache.end()) texture = existing->second;
                        else
                        {
                            try
                            {
                                const uint64_t available = (std::min)(options.maxTextureBytes - textureBytes,
                                    options.maxBytes - result.bytes.size());
                                if (FitsTexture(textureBytes, 4, static_cast<uint32_t>(result.metadata["textures"].size()), options) && available >= 4)
                                {
                                    auto dds = CoDAssets::GameXImageHandler(image);
                                    Check(cancelled);
                                    if (dds)
                                    {
                                        // IW color alpha is a shader-packed channel,
                                        // not transparency. Other games retain alpha.
                                        const bool opaque = CoDAssets::GameID == SupportedGames::InfiniteWarfare;
                                        auto decoded = DecodeDDS(reinterpret_cast<uint8_t*>(dds->DataBuffer), dds->DataSize,
                                            options.maxTextureDimension, available, opaque);
                                        Check(cancelled);
                                        if (decoded.error.empty())
                                        {
                                            texture = AppendImage(result, decoded, image.ImageName, options);
                                            textureBytes += decoded.rgba.size();
                                        }
                                    }
                                }
                            }
                            catch (const Cancelled&) { throw; }
                            catch (...) { Check(cancelled); }
                            textureCache.emplace(key, texture);
                        }
                        if (texture >= 0)
                        {
                            mesh["imageName"] = image.ImageName;
                            break;
                        }
                    }
                }
                mesh["texture"] = texture;
                if (texture < 0) ++missing;
            }
            result.metadata["missingTextures"] = missing;
            result.metadata["textureBytes"] = textureBytes;
        }

        void Terrain(Result& result, const CoDTerrain_t* asset, const Options& options,
            const std::function<bool()>& cancelled)
        {
            if (CoDAssets::GameID != SupportedGames::BlackOpsCW)
                throw std::runtime_error("Terrain preview currently requires Cold War.");
            if (!asset->AssetPointer || asset->AssetSize < 0x50)
                throw std::runtime_error("TerrainGfx header is unavailable.");

            auto Read64 = [](uint64_t address) { return CoDAssets::GameInstance->Read<uint64_t>(address); };
            const uint64_t root = Read64(asset->AssetPointer + 0x10);
            const uint64_t count = Read64(asset->AssetPointer + 0x30);
            const uint64_t imageTable = Read64(asset->AssetPointer + 0x38);
            const uint64_t idCount = Read64(asset->AssetPointer + 0x40);
            if (!root || !imageTable || !count || count != idCount || count > 4096)
                throw std::runtime_error("TerrainGfx image table is unavailable.");

            uintptr_t rootBytesRead = 0;
            auto rootBytes = CoDAssets::GameInstance->Read(static_cast<uintptr_t>(root), 0x104, rootBytesRead);
            if (!rootBytes || rootBytesRead != 0x104)
            {
                delete[] rootBytes;
                throw std::runtime_error("TerrainGfx mapping is unavailable.");
            }
            auto RootFloat = [rootBytes](size_t offset) { float value; std::memcpy(&value, rootBytes + offset, 4); return value; };
            auto Root16 = [rootBytes](size_t offset) { uint16_t value; std::memcpy(&value, rootBytes + offset, 2); return value; };
            const float originX = RootFloat(0xE8), originY = RootFloat(0xEC);
            const float cellSize = RootFloat(0xF0), heightBias = RootFloat(0xF4), heightRange = RootFloat(0xF8);
            const uint32_t width = Root16(0x100), height = Root16(0x102);
            delete[] rootBytes;
            if (!std::isfinite(originX) || !std::isfinite(originY) || !std::isfinite(cellSize) ||
                !std::isfinite(heightBias) || !std::isfinite(heightRange) || cellSize <= 0 ||
                heightRange <= 0 || width < 2 || height < 2 || width > 16384 || height > 16384)
                throw std::runtime_error("TerrainGfx height mapping is invalid.");

            uintptr_t tableBytesRead = 0;
            auto table = CoDAssets::GameInstance->Read(static_cast<uintptr_t>(imageTable),
                static_cast<uintptr_t>(count * 8), tableBytesRead);
            if (!table || tableBytesRead != count * 8)
            {
                delete[] table;
                throw std::runtime_error("TerrainGfx images are unavailable.");
            }
            uint64_t colorPointer = 0, heightPointer = 0;
            uint32_t heightImageWidth = 0, heightImageHeight = 0;
            std::vector<uint64_t> imagePointers(static_cast<size_t>(count), 0);
            std::vector<uint32_t> imageFormats(static_cast<size_t>(count), 0);
            std::vector<uint32_t> imageWidths(static_cast<size_t>(count), 0);
            std::vector<uint32_t> imageHeights(static_cast<size_t>(count), 0);
            int heightScore = -1;
            for (uint64_t i = 0; i < count; ++i)
            {
                if ((i & 31) == 0) Check(cancelled);
                uint64_t pointer = 0;
                std::memcpy(&pointer, table + i * 8, 8);
                if (!pointer) continue;
                const auto info = CoDAssets::GameInstance->Read<BOCWGfxImage>(pointer);
                imagePointers[static_cast<size_t>(i)] = pointer;
                imageFormats[static_cast<size_t>(i)] = info.ImageFormat;
                imageWidths[static_cast<size_t>(i)] = info.LoadedMipWidth;
                imageHeights[static_cast<size_t>(i)] = info.LoadedMipHeight;
                const auto hash = info.NamePtr & 0x0FFFFFFFFFFFFFFFull;
                const auto found = GameBlackOpsCW::AssetNameCache.NameDatabase.find(hash);
                const std::string name = found == GameBlackOpsCW::AssetNameCache.NameDatabase.end()
                    ? std::string() : found->second;
                if (name.find("terrain_combined_maps") != std::string::npos &&
                    name.size() >= 2 && name.compare(name.size() - 2, 2, "_0") == 0 &&
                    info.ImageFormat == 78)
                    colorPointer = pointer;
                // Some maps keep the R16 height at twice the composite resolution:
                // 4095 samples span the same terrain as a 2048-sample color grid.
                const bool exactHeight = info.LoadedMipWidth == width && info.LoadedMipHeight == height;
                const bool denseHeight = uint64_t(info.LoadedMipWidth) == uint64_t(width) * 2 - 1 &&
                    uint64_t(info.LoadedMipHeight) == uint64_t(height) * 2 - 1;
                const int score = info.ImageFormat == 56 && (exactHeight || denseHeight)
                    ? (name.find("terrain_height_maps") != std::string::npos ? 4 : 0) +
                      (exactHeight ? 2 : 1) : -1;
                if (score > heightScore)
                {
                    heightPointer = pointer;
                    heightImageWidth = info.LoadedMipWidth;
                    heightImageHeight = info.LoadedMipHeight;
                    heightScore = score;
                }
            }
            delete[] table;
            if (!colorPointer)
            {
                // Map-wide composites occur as BC3 color followed by BC5 normal.
                // The R16 height may precede that pair and have denser samples.
                for (size_t i = 0; i + 1 < imagePointers.size(); ++i)
                {
                    if (imageFormats[i] == 78 &&
                        (imageFormats[i + 1] == 83 || imageFormats[i + 1] == 84) &&
                        imageWidths[i] == width && imageHeights[i] == height &&
                        imagePointers[i] && imagePointers[i + 1])
                    {
                        colorPointer = imagePointers[i];
                        break;
                    }
                }
            }
            if (!colorPointer || !heightPointer)
                throw std::runtime_error("TerrainGfx color or height image is unavailable for this map.");

            auto colorDDS = GameBlackOpsCW::LoadXImage(XImage_t(ImageUsageType::Unknown, 0,
                colorPointer, "terrain_combined_maps_0"));
            Check(cancelled);
            if (!colorDDS || !colorDDS->DataBuffer)
                throw std::runtime_error("TerrainGfx color image could not be loaded.");
            auto color = DecodeDDS(reinterpret_cast<const uint8_t*>(colorDDS->DataBuffer),
                colorDDS->DataSize, options.maxTextureDimension,
                (std::min)(options.maxTextureBytes, options.maxBytes), true);
            Check(cancelled);
            if (!color.error.empty()) throw std::runtime_error(color.error);
            if (color.firstSlice)
                throw std::runtime_error("TerrainGfx color image uses an unsupported image array.");

            auto heightDDS = GameBlackOpsCW::LoadXImage(XImage_t(ImageUsageType::Unknown, 0,
                heightPointer, "terrain_height_maps"));
            Check(cancelled);
            if (!heightDDS || !heightDDS->DataBuffer || heightDDS->DataSize < 148)
                throw std::runtime_error("TerrainGfx height image could not be loaded.");
            const auto* data = reinterpret_cast<const uint8_t*>(heightDDS->DataBuffer);
            if (std::memcmp(data, "DDS ", 4) != 0)
                throw std::runtime_error("TerrainGfx height image has an invalid DDS header.");
            uint32_t ddsWidth = 0, ddsHeight = 0;
            std::memcpy(&ddsHeight, data + 12, 4);
            std::memcpy(&ddsWidth, data + 16, 4);
            const size_t headerBytes = std::memcmp(data + 84, "DX10", 4) == 0 ? 148 : 128;
            const uint64_t heightBytes = uint64_t(heightImageWidth) * heightImageHeight * 2;
            if (ddsWidth != heightImageWidth || ddsHeight != heightImageHeight ||
                heightBytes > heightDDS->DataSize - headerBytes)
                throw std::runtime_error("TerrainGfx height dimensions do not match the mapping.");
            const auto* samples = data + headerBytes;

            // A small regular grid is the lowest useful detail for an overview.
            // Both height and color are read directly from the selected live asset.
            constexpr uint32_t maxCells = 128;
            const uint32_t cellsX = (std::min)(width, maxCells);
            const uint32_t cellsY = (std::min)(height, maxCells);
            const uint64_t vertices = uint64_t(cellsX + 1) * (cellsY + 1);
            const uint64_t triangles = uint64_t(cellsX) * cellsY * 2;
            if (!FitsGeometry(vertices, triangles, options))
                throw std::runtime_error("Terrain exceeds the preview geometry limit.");
            result.metadata["vertexStride"] = sizeof(Vertex);
            result.metadata["upAxis"] = "Z";
            result.metadata["lod"] = "coarse";
            result.metadata["vertexCount"] = vertices;
            result.metadata["triangleCount"] = triangles;
            result.metadata["meshes"] = nlohmann::json::array();
            result.metadata["colorSource"] = "terrain_combined_maps_0";
            const auto texture = AppendImage(result, color, "terrain_combined_maps_0", options);
            const auto vertexOffset = result.bytes.size();
            float minZ = FLT_MAX, maxZ = -FLT_MAX;
            for (uint32_t y = 0; y <= cellsY; ++y)
            {
                Check(cancelled);
                const uint32_t sy = uint64_t(y) * (height - 1) / cellsY;
                for (uint32_t x = 0; x <= cellsX; ++x)
                {
                    const uint32_t sx = uint64_t(x) * (width - 1) / cellsX;
                    uint16_t sample = 0;
                    const uint32_t hx = uint64_t(sx) * (ddsWidth - 1) / (width - 1);
                    const uint32_t hy = uint64_t(sy) * (ddsHeight - 1) / (height - 1);
                    std::memcpy(&sample, samples + (uint64_t(hy) * ddsWidth + hx) * 2, 2);
                    Vertex vertex{};
                    vertex.position[0] = originX + sx * cellSize;
                    vertex.position[1] = originY + sy * cellSize;
                    vertex.position[2] = heightBias + (sample / 65535.0f) * heightRange;
                    vertex.normal[2] = 1.0f;
                    vertex.uv[0] = float(sx) / float(width - 1);
                    vertex.uv[1] = float(sy) / float(height - 1);
                    std::memset(vertex.color, 255, sizeof(vertex.color));
                    minZ = (std::min)(minZ, vertex.position[2]);
                    maxZ = (std::max)(maxZ, vertex.position[2]);
                    Append(result, &vertex, sizeof(vertex), options);
                }
            }
            const auto indexOffset = result.bytes.size();
            for (uint32_t y = 0; y < cellsY; ++y)
            {
                Check(cancelled);
                for (uint32_t x = 0; x < cellsX; ++x)
                {
                    const uint32_t a = y * (cellsX + 1) + x;
                    const uint32_t indices[6] = {a, a + cellsX + 1, a + cellsX + 2,
                        a, a + cellsX + 2, a + 1};
                    Append(result, indices, sizeof(indices), options);
                }
            }
            result.metadata["meshes"].push_back({{"vertexOffset", vertexOffset}, {"vertexCount", vertices},
                {"indexOffset", indexOffset}, {"indexCount", triangles * 3}, {"texture", texture},
                {"materialName", "TerrainGfx"}});
            result.metadata["bounds"] = {{"min", {originX, originY, minZ}},
                {"max", {originX + (width - 1) * cellSize, originY + (height - 1) * cellSize, maxZ}}};
            result.metadata["textureBytes"] = color.rgba.size();
        }

        std::vector<uint8_t> ReadBO4Bytes(uint64_t address, size_t size,
            const std::function<bool()>& cancelled)
        {
            if (address < 0x10000 || address >= 0x0000800000000000ull ||
                size > 64ull * 1024 * 1024 || size > 0x0000800000000000ull - address)
                throw std::runtime_error("BO4 terrain memory span is invalid.");
            std::vector<uint8_t> bytes(size);
            for (size_t offset = 0; offset < size;)
            {
                Check(cancelled);
                const auto count = (std::min)(size - offset, size_t(4 * 1024 * 1024));
                uintptr_t got = 0;
                std::unique_ptr<int8_t[]> chunk(CoDAssets::GameInstance->Read(
                    address + offset, static_cast<uintptr_t>(count), got));
                if (!chunk || got != count)
                    throw std::runtime_error("BO4 terrain data is not resident in the loaded map.");
                std::memcpy(bytes.data() + offset, chunk.get(), count);
                offset += count;
            }
            return bytes;
        }

        float BO4BC4Sample(const std::vector<uint8_t>& bytes, uint32_t side,
            uint32_t x, uint32_t y)
        {
            const size_t block = (size_t(y / 4) * (side / 4) + x / 4) * 8;
            if (block + 8 > bytes.size()) return 0;
            const uint8_t a = bytes[block], b = bytes[block + 1];
            uint64_t bits = 0;
            for (int i = 0; i < 6; ++i) bits |= uint64_t(bytes[block + 2 + i]) << (i * 8);
            const auto index = (bits >> (3 * ((y % 4) * 4 + x % 4))) & 7;
            if (index == 0) return a / 255.0f;
            if (index == 1) return b / 255.0f;
            if (a > b) return ((8 - index) * a + (index - 1) * b) / (7.0f * 255.0f);
            if (index == 6) return 0;
            if (index == 7) return 1;
            return ((6 - index) * a + (index - 1) * b) / (5.0f * 255.0f);
        }

        bool BO4Solid(const std::vector<uint8_t>& words, uint32_t tiles, uint32_t x, uint32_t y)
        {
            const size_t word = (size_t(y / 4) * (tiles * 4 + 1) + x / 8) * 4;
            if (word + 4 > words.size()) return false;
            uint32_t value = 0;
            std::memcpy(&value, words.data() + word, 4);
            return (value >> ((x & 7) + 8 * (y & 3))) & 1;
        }

        struct BO4LayerPreview
        {
            float uv[8]{};
            uint16_t weightSlice = 4095;
            const DecodedImage* color = nullptr;
            std::vector<uint8_t> weights;
        };

        void TerrainBO4(Result& result, const CoDTerrain_t* asset, const Options& options,
            const std::function<bool()>& cancelled)
        {
            if (!asset->AssetPointer || asset->AssetSize < 0x30 ||
                CoDAssets::GameOffsetInfos.size() < 3 || CoDAssets::GamePoolSizes.size() < 3)
                throw std::runtime_error("BO4 TerrainGfx header or image pool is unavailable.");
            const auto Read64 = [](uint64_t at) { return CoDAssets::GameInstance->Read<uint64_t>(at); };
            const auto Read32 = [](uint64_t at) { return CoDAssets::GameInstance->Read<uint32_t>(at); };
            const uint64_t sectorCount = Read64(asset->AssetPointer + 0x10);
            const uint64_t sectorArray = Read64(asset->AssetPointer + 0x18);
            if (!sectorArray || sectorCount < 1 || sectorCount > 256)
                throw std::runtime_error("BO4 TerrainGfx sector list is invalid.");

            const uint64_t imagePool = CoDAssets::GameOffsetInfos[2];
            const uint64_t imagePoolBytes = uint64_t(CoDAssets::GamePoolSizes[2]) * sizeof(BO4GfxImage);
            auto IsImage = [imagePool, imagePoolBytes](uint64_t at)
            {
                return imagePoolBytes && at >= imagePool && at - imagePool < imagePoolBytes &&
                    (at - imagePool) % sizeof(BO4GfxImage) == 0;
            };
            struct GridImage { uint64_t pointer; BO4GfxImage image; };
            std::vector<GridImage> gridImages;
            std::set<uint64_t> seenImages;
            for (uint64_t sector = 0; sector < sectorCount; ++sector)
            {
                Check(cancelled);
                const uint64_t base = sectorArray + sector * 0x148;
                if (Read32(base + 0xF0) != 33)
                    throw std::runtime_error("BO4 TerrainGfx sector layout is unsupported.");
                for (const size_t side : {size_t(0xD0), size_t(0x110), size_t(0x128), size_t(0x138)})
                {
                    const uint64_t pointer = Read64(base + side + 8);
                    if (!pointer) continue;
                    std::vector<uint8_t> bytes;
                    for (size_t length = 8192; length >= 256 && bytes.empty(); length /= 2)
                    {
                        try { bytes = ReadBO4Bytes(pointer, length, cancelled); }
                        catch (const std::runtime_error&) { Check(cancelled); }
                    }
                    for (size_t at = 0; at + 8 <= bytes.size(); at += 8)
                    {
                        uint64_t candidate = 0;
                        std::memcpy(&candidate, bytes.data() + at, 8);
                        if (!IsImage(candidate) || !seenImages.insert(candidate).second) continue;
                        const auto image = CoDAssets::GameInstance->Read<BO4GfxImage>(candidate);
                        const uint32_t w = image.LoadedMipWidth, h = image.LoadedMipHeight;
                        const bool square = w == h && w >= 68 && (w - 4) % 32 == 0;
                        const bool cutout = w >= 9 && h == w * 2 - 1 && (w - 1) % 4 == 0;
                        if (square || cutout) gridImages.push_back({candidate, image});
                    }
                }
            }
            if (gridImages.empty() || gridImages.size() % 3)
                throw std::runtime_error("BO4 sector height, cutout, and weight images were not found.");
            struct GridSet { GridImage height, cutout, weight; uint32_t tiles; };
            std::map<uint32_t, GridSet> grids;
            for (size_t i = 0; i < gridImages.size(); i += 3)
            {
                const auto& h = gridImages[i].image;
                const auto& c = gridImages[i + 1].image;
                const auto& w = gridImages[i + 2].image;
                const uint32_t tiles = (h.LoadedMipWidth - 4) / 32;
                if (h.ImageFormat != 56 || c.ImageFormat != 42 || w.ImageFormat != 80 ||
                    h.LoadedMipWidth != h.LoadedMipHeight ||
                    w.LoadedMipWidth != h.LoadedMipWidth || w.LoadedMipHeight != h.LoadedMipHeight ||
                    c.LoadedMipWidth != tiles * 4 + 1 || c.LoadedMipHeight != tiles * 8 + 1 ||
                    !grids.emplace(tiles, GridSet{gridImages[i], gridImages[i + 1], gridImages[i + 2], tiles}).second)
                    throw std::runtime_error("BO4 sector image sequence does not match its grid.");
            }

            std::map<uint64_t, DecodedImage> colors;
            std::array<float, 3> minimum = {FLT_MAX, FLT_MAX, FLT_MAX};
            std::array<float, 3> maximum = {-FLT_MAX, -FLT_MAX, -FLT_MAX};
            uint64_t allVertices = 0, allTriangles = 0;
            uint32_t approximateLayers = 0;
            result.metadata["vertexStride"] = sizeof(Vertex);
            result.metadata["upAxis"] = "Z";
            result.metadata["lod"] = "coarse";
            result.metadata["meshes"] = nlohmann::json::array();
            for (uint64_t sector = 0; sector < sectorCount; ++sector)
            {
                Check(cancelled);
                const uint64_t base = sectorArray + sector * 0x148;
                const uint64_t levelList = Read64(base + 0x50);
                const uint32_t tiles = levelList ? Read32(levelList) : 0;
                const auto found = grids.find(tiles);
                if (found == grids.end() || tiles > 256 || !tiles)
                    throw std::runtime_error("BO4 sector has no matching grid images.");
                const auto& grid = found->second;
                const uint32_t side = tiles * 32 + 4, span = tiles * 32;
                const uint32_t slice = Read32(base + 0xE4);
                const uint64_t heightSliceBytes = uint64_t(side) * side * 2;
                const uint64_t cutoutSliceBytes = uint64_t(tiles * 4 + 1) * (tiles * 8 + 1) * 4;
                const uint64_t weightSliceBytes = uint64_t(side / 4) * (side / 4) * 8;
                if (!grid.height.image.LoadedMipPtr || !grid.cutout.image.LoadedMipPtr ||
                    !grid.weight.image.LoadedMipPtr ||
                    (uint64_t(slice) + 1) * heightSliceBytes > grid.height.image.LoadedMipSize ||
                    (uint64_t(slice) + 1) * cutoutSliceBytes > grid.cutout.image.LoadedMipSize)
                    throw std::runtime_error("BO4 sector grid slice is unavailable.");
                const auto heights = ReadBO4Bytes(grid.height.image.LoadedMipPtr + slice * heightSliceBytes,
                    static_cast<size_t>(heightSliceBytes), cancelled);
                const auto cutout = ReadBO4Bytes(grid.cutout.image.LoadedMipPtr + slice * cutoutSliceBytes,
                    static_cast<size_t>(cutoutSliceBytes), cancelled);
                const float minX = CoDAssets::GameInstance->Read<float>(base + 0xB8);
                const float minY = CoDAssets::GameInstance->Read<float>(base + 0xBC);
                const float units = CoDAssets::GameInstance->Read<float>(base + 0xFC);
                const float bias = CoDAssets::GameInstance->Read<float>(base + 0x100) +
                    CoDAssets::GameInstance->Read<float>(base + 0x90);
                const float range = CoDAssets::GameInstance->Read<float>(base + 0x104);
                float placement[12]{};
                const auto placementBytes = ReadBO4Bytes(base + 0x88, sizeof(placement), cancelled);
                std::memcpy(placement, placementBytes.data(), sizeof(placement));
                const float r00 = placement[3], r01 = placement[4];
                const float r10 = placement[6], r11 = placement[7];
                auto Axis = [](float x) { return std::abs(x - std::round(x)) < 0.001f && std::abs(x) <= 1.001f; };
                if (!std::isfinite(minX) || !std::isfinite(minY) || !std::isfinite(units) ||
                    !std::isfinite(bias) || !std::isfinite(range) || units <= 0 || range <= 0 ||
                    !Axis(r00) || !Axis(r01) || !Axis(r10) || !Axis(r11) ||
                    std::abs(r00 * r11 - r01 * r10) < 0.99f)
                    throw std::runtime_error("BO4 sector transform is unsupported.");
                const auto Local = [span, r00, r01, r10, r11](float x, float y)
                {
                    const float dx = x - span * 0.5f, dy = y - span * 0.5f;
                    const auto col = static_cast<uint32_t>((std::max)(0.0f,
                        (std::min)(float(span), std::round(dx * r00 + dy * r01 + span * 0.5f))));
                    const auto row = static_cast<uint32_t>((std::max)(0.0f,
                        (std::min)(float(span), std::round(dx * r10 + dy * r11 + span * 0.5f))));
                    return std::make_pair(col, row);
                };

                const uint64_t layerCount = Read64(base + 0x110);
                const uint64_t layerTable = Read64(base + 0x118);
                const uint64_t weightCount = Read64(base + 0x138);
                const uint64_t weightTable = Read64(base + 0x140);
                if (!layerCount || layerCount > 64 || layerCount != weightCount || !layerTable || !weightTable)
                    throw std::runtime_error("BO4 sector layer list is unavailable.");
                const auto layerBytes = ReadBO4Bytes(layerTable, static_cast<size_t>(layerCount * 0x108), cancelled);
                const auto sourceSlices = ReadBO4Bytes(weightTable, static_cast<size_t>(layerCount * 2), cancelled);
                std::vector<BO4LayerPreview> layers(static_cast<size_t>(layerCount));
                for (size_t k = 0; k < layers.size(); ++k)
                {
                    Check(cancelled);
                    auto& layer = layers[k];
                    std::memcpy(layer.uv, layerBytes.data() + k * 0x108 + 0x10, sizeof(layer.uv));
                    std::memcpy(&layer.weightSlice, sourceSlices.data() + k * 2, 2);
                    if (layer.weightSlice == 4095) continue;
                    if (layer.weightSlice != 4094)
                    {
                        if ((uint64_t(layer.weightSlice) + 1) * weightSliceBytes > grid.weight.image.LoadedMipSize)
                            throw std::runtime_error("BO4 terrain layer weight slice is unavailable.");
                        layer.weights = ReadBO4Bytes(grid.weight.image.LoadedMipPtr +
                            uint64_t(layer.weightSlice) * weightSliceBytes,
                            static_cast<size_t>(weightSliceBytes), cancelled);
                    }
                    uint64_t materialPtr = 0;
                    std::memcpy(&materialPtr, layerBytes.data() + k * 0x108, 8);
                    if (!materialPtr)
                        throw std::runtime_error("BO4 terrain layer material is unavailable.");
                    const auto material = CoDAssets::GameInstance->Read<BO4XMaterial>(materialPtr);
                    if (!material.ImageTablePtr || !material.ImageCount || material.ImageCount > 16)
                        throw std::runtime_error("BO4 terrain layer color binding is unavailable.");
                    uint64_t colorPtr = 0;
                    for (uint32_t image = 0; image < material.ImageCount; ++image)
                    {
                        const auto binding = CoDAssets::GameInstance->Read<BO4XMaterialImage>(
                            material.ImageTablePtr + image * sizeof(BO4XMaterialImage));
                        if (binding.SemanticHash == 0xA0AB1041 && IsImage(binding.ImagePtr))
                        { colorPtr = binding.ImagePtr; break; }
                    }
                    if (!colorPtr)
                        throw std::runtime_error("BO4 terrain layer has no colorMap image.");
                    auto cached = colors.find(colorPtr);
                    if (cached == colors.end())
                    {
                        auto dds = GameBlackOps4::LoadXImage(XImage_t(ImageUsageType::DiffuseMap, 0,
                            colorPtr, "terrain_layer_color"));
                        Check(cancelled);
                        if (!dds || !dds->DataBuffer)
                            throw std::runtime_error("BO4 terrain layer color could not be loaded.");
                        auto image = DecodeDDS(reinterpret_cast<const uint8_t*>(dds->DataBuffer),
                            dds->DataSize, (std::min)(options.maxTextureDimension, uint32_t(256)),
                            256ull * 256 * 4, false);
                        if (!image.error.empty()) throw std::runtime_error(image.error);
                        cached = colors.emplace(colorPtr, std::move(image)).first;
                    }
                    layer.color = &cached->second;
                }

                const uint32_t cells = (std::min)(span, uint32_t(128));
                const uint64_t vertices = uint64_t(cells + 1) * (cells + 1);
                if (allVertices + vertices > options.maxVertices)
                    throw std::runtime_error("BO4 map exceeds the preview vertex limit.");
                const size_t vertexOffset = result.bytes.size();
                for (uint32_t y = 0; y <= cells; ++y)
                {
                    Check(cancelled);
                    for (uint32_t x = 0; x <= cells; ++x)
                    {
                        const float gx = float(uint64_t(x) * span) / cells;
                        const float gy = float(uint64_t(y) * span) / cells;
                        const auto local = Local(gx, gy);
                        uint16_t sample = 0;
                        std::memcpy(&sample, heights.data() +
                            (uint64_t(local.second) * side + local.first) * 2, 2);
                        Vertex vertex{};
                        vertex.position[0] = minX + gx * units;
                        vertex.position[1] = minY + gy * units;
                        vertex.position[2] = bias + (sample / 65535.0f) * range;
                        vertex.normal[2] = 1;
                        vertex.uv[0] = float(x) / cells;
                        vertex.uv[1] = float(y) / cells;
                        float rgb[3] = {0.05f, 0.05f, 0.05f};
                        for (const auto& layer : layers)
                        {
                            if (!layer.color) continue;
                            const float weight = layer.weightSlice == 4094 ? 1.0f :
                                BO4BC4Sample(layer.weights, side, local.first, local.second);
                            if (weight <= 0) continue;
                            const float u = vertex.position[0] * layer.uv[0] +
                                vertex.position[1] * layer.uv[1] + vertex.position[2] * layer.uv[2] + layer.uv[3];
                            const float v = vertex.position[0] * layer.uv[4] +
                                vertex.position[1] * layer.uv[5] + vertex.position[2] * layer.uv[6] + layer.uv[7];
                            if (!std::isfinite(u) || !std::isfinite(v)) continue;
                            const auto& image = *layer.color;
                            const uint32_t tx = uint32_t(std::floor((u - std::floor(u)) * image.width)) % image.width;
                            const uint32_t ty = uint32_t(std::floor((v - std::floor(v)) * image.height)) % image.height;
                            const size_t pixel = (size_t(ty) * image.width + tx) * 4;
                            for (size_t channel = 0; channel < 3; ++channel)
                            {
                                const float source = std::pow(image.rgba[pixel + channel] / 255.0f, 2.2f);
                                rgb[channel] += (source - rgb[channel]) * weight;
                            }
                        }
                        for (size_t channel = 0; channel < 3; ++channel)
                            vertex.color[channel] = static_cast<uint8_t>((std::min)(255.0f,
                                std::round(std::pow((std::max)(0.0f, rgb[channel]), 1.0f / 2.2f) * 255.0f)));
                        vertex.color[3] = 255;
                        for (size_t axis = 0; axis < 3; ++axis)
                        {
                            minimum[axis] = (std::min)(minimum[axis], vertex.position[axis]);
                            maximum[axis] = (std::max)(maximum[axis], vertex.position[axis]);
                        }
                        Append(result, &vertex, sizeof(vertex), options);
                    }
                }
                const size_t indexOffset = result.bytes.size();
                uint64_t sectorTriangles = 0;
                for (uint32_t y = 0; y < cells; ++y)
                {
                    Check(cancelled);
                    for (uint32_t x = 0; x < cells; ++x)
                    {
                        const auto local = Local((x + 0.5f) * span / cells,
                            (y + 0.5f) * span / cells);
                        if (!BO4Solid(cutout, tiles, local.first, local.second)) continue;
                        const uint32_t a = y * (cells + 1) + x;
                        const uint32_t indices[6] = {a, a + cells + 1, a + cells + 2,
                            a, a + cells + 2, a + 1};
                        Append(result, indices, sizeof(indices), options);
                        sectorTriangles += 2;
                    }
                }
                if (!sectorTriangles) throw std::runtime_error("BO4 sector has no visible terrain at preview detail.");
                result.metadata["meshes"].push_back({{"vertexOffset", vertexOffset}, {"vertexCount", vertices},
                    {"indexOffset", indexOffset}, {"indexCount", sectorTriangles * 3}, {"texture", -1},
                    {"materialName", "TerrainGfx sector " + std::to_string(sector)}});
                allVertices += vertices;
                allTriangles += sectorTriangles;
                approximateLayers += static_cast<uint32_t>(layers.size());
            }
            if (!FitsGeometry(allVertices, allTriangles, options))
                throw std::runtime_error("BO4 map exceeds the preview geometry limit.");
            result.metadata["vertexCount"] = allVertices;
            result.metadata["triangleCount"] = allTriangles;
            result.metadata["missingTextures"] = 0;
            result.metadata["textureBytes"] = 0;
            result.metadata["sectorCount"] = sectorCount;
            result.metadata["sourceLayerCount"] = approximateLayers;
            result.metadata["colorSource"] = "BO4 colorMap layers and BC4 weights (coarse preview)";
            result.metadata["bounds"] = {{"min", minimum}, {"max", maximum}};
        }
    }

    Result Build(const CoDAsset_t* asset, const Options& options, const std::function<bool()>& cancelled)
    {
        Result result;
        try
        {
            Check(cancelled);
            if (!asset) throw std::runtime_error("Choose a model, image, or terrain to preview.");
            if (asset->AssetType != WraithAssetType::Model && asset->AssetType != WraithAssetType::Image &&
                asset->AssetType != WraithAssetType::Terrain)
                throw std::runtime_error("Preview is available for models, images, and terrain.");
            if (!options.maxBytes || options.maxBytes > 256ull * 1024 * 1024 || !options.maxTextureDimension || !options.maxImageDimension)
                throw std::runtime_error("Preview limits are invalid.");
            ColorScope colors;
            WaitForCache(CoDAssets::GamePackageCache.get(), cancelled);
            WaitForCache(CoDAssets::OnDemandCache.get(), cancelled);
            result.metadata = { {"version", 1}, {"name", asset->AssetName},
                {"kind", asset->AssetType == WraithAssetType::Model ? "model" :
                    asset->AssetType == WraithAssetType::Terrain ? "terrain" : "image"},
                {"textures", nlohmann::json::array()}, {"missingTextures", 0} };
            if (asset->AssetType == WraithAssetType::Model)
                Model(result, static_cast<const CoDModel_t*>(asset), options, cancelled);
            else if (asset->AssetType == WraithAssetType::Terrain)
            {
                if (CoDAssets::GameID == SupportedGames::BlackOps4)
                    TerrainBO4(result, static_cast<const CoDTerrain_t*>(asset), options, cancelled);
                else
                    Terrain(result, static_cast<const CoDTerrain_t*>(asset), options, cancelled);
            }
            else
            {
                auto dds = CoDAssets::LoadImageForPreview(static_cast<const CoDImage_t*>(asset));
                Check(cancelled);
                if (!dds) throw std::runtime_error("Image data is unavailable from the game or its packages.");
                auto decoded = DecodeDDS(reinterpret_cast<uint8_t*>(dds->DataBuffer), dds->DataSize,
                    options.maxImageDimension, (std::min)(options.maxTextureBytes, options.maxBytes));
                Check(cancelled);
                if (!decoded.error.empty()) throw std::runtime_error(decoded.error);
                AppendImage(result, decoded, asset->AssetName, options);
            }
            Check(cancelled);
            result.metadata["byteLength"] = result.bytes.size();
        }
        catch (const Cancelled&)
        {
            result = Result{};
            result.cancelled = true;
        }
        catch (const std::exception& error)
        {
            result = Result{};
            result.error = error.what();
        }
        catch (...)
        {
            result = Result{};
            result.error = "The game reader could not prepare this preview.";
        }
        return result;
    }
}
