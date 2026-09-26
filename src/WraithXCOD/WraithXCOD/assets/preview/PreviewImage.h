#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace PreviewData
{
    struct DecodedImage
    {
        uint32_t width = 0, height = 0;
        uint32_t sourceWidth = 0, sourceHeight = 0;
        bool hasAlpha = false;
        bool firstSlice = false;
        std::vector<uint8_t> rgba;
        std::string error;
    };

    // Keeps the first array/cube/depth slice and a bounded usable mip. Alpha is
    // retained as straight RGBA; shader-packed non-opacity alpha may be ignored
    // explicitly by the model caller, never by an export preference.
    DecodedImage DecodeDDS(const uint8_t* bytes, size_t byteLength, uint32_t maxDimension,
        uint64_t maxOutputBytes, bool opaque = false);
}
