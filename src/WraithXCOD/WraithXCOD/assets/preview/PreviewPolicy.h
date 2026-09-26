#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace PreviewData
{
    struct Options
    {
        uint64_t maxVertices = 500000;
        uint64_t maxTriangles = 1000000;
        uint64_t maxBytes = 64ull * 1024 * 1024;
        uint64_t maxTextureBytes = 24ull * 1024 * 1024;
        uint32_t maxTextureDimension = 1024;
        uint32_t maxImageDimension = 2048;
        uint32_t maxTextures = 64;
        uint32_t maxSubmeshes = 2048;
    };

    struct LodCandidate
    {
        uint32_t index;
        uint64_t vertices;
        uint64_t triangles;
    };

    inline bool FitsGeometry(uint64_t vertices, uint64_t triangles, const Options& options)
    {
        return vertices != 0 && triangles != 0 && vertices <= options.maxVertices &&
            triangles <= options.maxTriangles && vertices <= options.maxBytes / 36 &&
            triangles <= (options.maxBytes - vertices * 36) / 12;
    }

    // Rank usable detail levels by actual geometry. Empty and oversized LODs
    // never reach a reader; unavailable streamed LODs can fall through this list.
    template<class Lods>
    std::vector<LodCandidate> CandidateLods(const Lods& lods, const Options& options)
    {
        std::vector<LodCandidate> result;
        for (size_t i = 0; i < lods.size(); ++i)
        {
            uint64_t vertices = 0, triangles = 0;
            for (const auto& mesh : lods[i].Submeshes)
            {
                vertices += mesh.VertexCount;
                triangles += mesh.FaceCount;
            }
            if (lods[i].Submeshes.size() <= options.maxSubmeshes && FitsGeometry(vertices, triangles, options))
                result.push_back({ static_cast<uint32_t>(i), vertices, triangles });
        }
        std::stable_sort(result.begin(), result.end(), [](const LodCandidate& a, const LodCandidate& b)
        {
            return a.triangles != b.triangles ? a.triangles > b.triangles : a.vertices > b.vertices;
        });
        return result;
    }

    // A material name is a label, never an identity. Translators may merge names
    // for export, but the original LOD material array stays indexed by surface.
    template<class Materials>
    const typename Materials::value_type* MaterialAt(const Materials& materials, size_t submesh)
    {
        return submesh < materials.size() ? &materials[submesh] : nullptr;
    }

    inline bool FitsTexture(uint64_t used, uint64_t bytes, uint32_t count, const Options& options)
    {
        return count < options.maxTextures && used <= options.maxTextureBytes &&
            bytes <= options.maxTextureBytes - used;
    }
}
