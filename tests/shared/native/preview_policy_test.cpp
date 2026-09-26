#include "assets/preview/PreviewPolicy.h"

#include <cassert>
#include <iostream>
#include <limits>
#include <string>

namespace
{
    struct Mesh { uint32_t VertexCount, FaceCount; };
    struct Lod { std::vector<Mesh> Submeshes; };
    struct Material { std::string MaterialName; uint64_t ImagePointer; };
}

int main()
{
    PreviewData::Options Options;
    const std::vector<Material> Materials{
        { "same_name", 0x1111 }, { "same_name", 0x2222 }, { "missing_image", 0 }
    };
    // Duplicate labels must never merge the source bindings for two surfaces.
    assert(PreviewData::MaterialAt(Materials, 0)->ImagePointer == 0x1111);
    assert(PreviewData::MaterialAt(Materials, 1)->ImagePointer == 0x2222);
    assert(PreviewData::MaterialAt(Materials, 2)->ImagePointer == 0);
    assert(PreviewData::MaterialAt(Materials, 3) == nullptr);
    assert(PreviewData::MaterialAt(Materials, std::numeric_limits<size_t>::max()) == nullptr);

    const std::vector<Lod> Lods{
        { {} },                              // empty source LOD
        { { { 900000, 1200000 } } },         // oversize source LOD
        { { { 200000, 120000 } } },          // lower usable LOD
        { { { 300, 120 }, { 80, 40 } } },   // cheap streamed fallback
        { { { 200000, 120000 } } },          // ties retain source order
        { { { 90, 0 } } }                   // vertex-only is not a model
    };
    const auto Ranked = PreviewData::CandidateLods(Lods, Options);
    assert(Ranked.size() == 3);
    assert(Ranked[0].index == 2 && Ranked[1].index == 4 && Ranked[2].index == 3);
    assert(Ranked[2].vertices == 380 && Ranked[2].triangles == 160);
    assert(PreviewData::CandidateLods(std::vector<Lod>{}, Options).empty());
    assert(!PreviewData::FitsGeometry(0, 1, Options));
    assert(!PreviewData::FitsGeometry(1, 0, Options));
    assert(!PreviewData::FitsGeometry(std::numeric_limits<uint64_t>::max(), 1, Options));
    assert(!PreviewData::FitsGeometry(1, std::numeric_limits<uint64_t>::max(), Options));
    Options.maxSubmeshes = 1;
    assert(PreviewData::CandidateLods(Lods, Options).size() == 2);
    Options.maxBytes = 48;
    assert(PreviewData::FitsGeometry(1, 1, Options));
    Options.maxBytes = 47;
    assert(!PreviewData::FitsGeometry(1, 1, Options));
    Options.maxBytes = 0;
    assert(!PreviewData::FitsGeometry(1, 1, Options));

    Options.maxTextureBytes = 4096;
    Options.maxTextures = 2;
    assert(PreviewData::FitsTexture(0, 4096, 0, Options));
    assert(!PreviewData::FitsTexture(1, 4096, 0, Options));
    assert(!PreviewData::FitsTexture(0, 1, 2, Options));
    assert(!PreviewData::FitsTexture(std::numeric_limits<uint64_t>::max(), 1, 0, Options));
    assert(!PreviewData::FitsTexture(1, std::numeric_limits<uint64_t>::max(), 0, Options));
    std::cout << "Preview positional materials, missing bindings, empty/large LODs and budgets passed\n";
}
