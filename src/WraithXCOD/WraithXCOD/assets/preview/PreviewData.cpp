#include "stdafx.h"
#include "assets/preview/PreviewData.h"
#include "assets/preview/PreviewImage.h"
#include "assets/CoDAssets.h"
#include "exporters/CoDXModelTranslator.h"

#include <array>
#include <cfloat>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
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
    }

    Result Build(const CoDAsset_t* asset, const Options& options, const std::function<bool()>& cancelled)
    {
        Result result;
        try
        {
            Check(cancelled);
            if (!asset) throw std::runtime_error("Choose a model or image to preview.");
            if (asset->AssetType != WraithAssetType::Model && asset->AssetType != WraithAssetType::Image)
                throw std::runtime_error("Preview is available for models and images.");
            if (!options.maxBytes || options.maxBytes > 256ull * 1024 * 1024 || !options.maxTextureDimension || !options.maxImageDimension)
                throw std::runtime_error("Preview limits are invalid.");
            ColorScope colors;
            WaitForCache(CoDAssets::GamePackageCache.get(), cancelled);
            WaitForCache(CoDAssets::OnDemandCache.get(), cancelled);
            result.metadata = { {"version", 1}, {"name", asset->AssetName},
                {"kind", asset->AssetType == WraithAssetType::Model ? "model" : "image"},
                {"textures", nlohmann::json::array()}, {"missingTextures", 0} };
            if (asset->AssetType == WraithAssetType::Model)
                Model(result, static_cast<const CoDModel_t*>(asset), options, cancelled);
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
