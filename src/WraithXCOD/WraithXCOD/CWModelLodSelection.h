#pragma once
#include <cstddef>
#include <cstdint>

namespace CWModelLodSelection
{
    // CW's distance values need not decrease with increasing geometry detail.
    // Count geometry instead; keep the earlier index when both counts tie.
    template<class Lods> int32_t Select(const Lods& Items)
    {
        int32_t Best = -1;
        uint64_t BestFaces = 0, BestVertices = 0;
        for (std::size_t Index = 0; Index < Items.size(); ++Index)
        {
            uint64_t Faces = 0, Vertices = 0;
            for (const auto& Surface : Items[Index].Submeshes)
            {
                Faces += Surface.FaceCount;
                Vertices += Surface.VertexCount;
            }
            if (!Faces || !Vertices) continue;
            if (Best < 0 || Faces > BestFaces ||
                (Faces == BestFaces && Vertices > BestVertices))
            {
                Best = static_cast<int32_t>(Index);
                BestFaces = Faces;
                BestVertices = Vertices;
            }
        }
        return Best;
    }
}
