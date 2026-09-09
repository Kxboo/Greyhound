#include <cassert>
#include <cstddef>
#include <vector>
#include "../src/WraithXCOD/WraithXCOD/CWModelLodSelection.h"
struct Surface { uint64_t FaceCount, VertexCount; };
struct Lod { std::vector<Surface> Submeshes; float Distance; };
int main()
{
    using CWModelLodSelection::Select;
    // Live wz_zoo fire extinguisher: the old distance test selected index 5.
    std::vector<Lod> Door = {
        {{{87,139}},1.01323f}, {{{273,332}},0.14168f},
        {{{466,545}},0.06555f}, {{{728,720}},0.04673f},
        {{{1080,1028}},0.04021f}, {{{1708,1618}},0.02696f},
        {{{2561,2306}},0.02745f}};
    assert(Select(Door) == 6);
    // Live hashed model: closest distance is index 2, denser geometry is 3.
    assert(Select(std::vector<Lod>{{{{76,154}},8.47744f},
        {{{866,1110}},0.36807f}, {{{2563,2459}},0.07000f},
        {{{3944,3185}},0.13911f}}) == 3);
    assert(Select(std::vector<Lod>{}) == -1);
    assert(Select(std::vector<Lod>{{{},0}}) == -1);
    assert(Select(std::vector<Lod>{{{{12,8}},10},{{{0,20}},0}}) == 0);
    // Surface count and index order do not decide detail. Sum all surfaces.
    assert(Select(std::vector<Lod>{{{{10,8},{10,8}},1},{{{30,20}},100}}) == 1);
    assert(Select(std::vector<Lod>{{{{30,20}},100},{{{10,8},{10,8}},1}}) == 0);
    // Geometry counts can exceed 32 bits in aggregate.
    assert(Select(std::vector<Lod>{{{{0xffffffff,20},{10,8}},1},{{{30,20}},0}}) == 0);
}
