#include "assets/preview/PreviewImage.h"

#include <algorithm>
#include <cstring>
#include "DirectXTex.h"

namespace PreviewData
{
    DecodedImage DecodeDDS(const uint8_t* bytes, size_t byteLength, uint32_t maxDimension,
        uint64_t maxOutputBytes, bool opaque)
    {
        DecodedImage result;
        constexpr uint64_t MaxDDSBytes = 256ull * 1024 * 1024;
        constexpr uint64_t MaxDecodedPixels = 16ull * 1024 * 1024;
        if (!bytes || byteLength < 128 || byteLength > MaxDDSBytes || !maxDimension || maxOutputBytes < 4)
        {
            result.error = "Image data is empty or exceeds the preview limit.";
            return result;
        }

        DirectX::TexMetadata metadata{};
        if (FAILED(DirectX::GetMetadataFromDDSMemory(bytes, byteLength, DirectX::DDS_FLAGS_NONE, metadata)) ||
            !metadata.width || !metadata.height || metadata.width > 16384 || metadata.height > 16384 ||
            !metadata.arraySize || metadata.arraySize > 2048 || metadata.depth > 2048 || metadata.mipLevels > 16)
        {
            result.error = "Image DDS metadata is invalid or exceeds the preview limit.";
            return result;
        }
        result.sourceWidth = static_cast<uint32_t>(metadata.width);
        result.sourceHeight = static_cast<uint32_t>(metadata.height);
        result.firstSlice = metadata.arraySize > 1 || metadata.depth > 1;

        // Check scratch storage before DirectXTex allocates it. Block-compressed
        // inputs remain compressed here; only one selected mip is decompressed.
        uint64_t scratchBytes = 0;
        for (size_t mip = 0; mip < metadata.mipLevels; ++mip)
        {
            size_t rowPitch = 0, slicePitch = 0;
            if (FAILED(DirectX::ComputePitch(metadata.format, (std::max)(size_t(1), metadata.width >> mip),
                (std::max)(size_t(1), metadata.height >> mip), rowPitch, slicePitch)))
            {
                result.error = "Image format is unsupported.";
                return result;
            }
            const uint64_t slices = metadata.arraySize * (std::max)(size_t(1), metadata.depth >> mip);
            if (slicePitch > MaxDDSBytes || slices > MaxDDSBytes / (std::max)(size_t(1), slicePitch) ||
                slicePitch * slices > MaxDDSBytes - scratchBytes)
            {
                result.error = "Image array exceeds the preview memory limit.";
                return result;
            }
            scratchBytes += slicePitch * slices;
        }

        DirectX::ScratchImage source;
        if (FAILED(DirectX::LoadFromDDSMemory(bytes, byteLength, DirectX::DDS_FLAGS_NONE, &metadata, source)))
        {
            result.error = "Image data could not be decoded.";
            return result;
        }
        size_t mip = 0;
        while (mip + 1 < metadata.mipLevels &&
            ((metadata.width >> mip) > maxDimension || (metadata.height >> mip) > maxDimension)) ++mip;
        const DirectX::Image* current = source.GetImage(mip, 0, 0);
        if (!current || current->width * current->height > MaxDecodedPixels)
        {
            result.error = "Image has no mip within the preview decoding limit.";
            return result;
        }

        DirectX::ScratchImage decompressed, converted, straight, resized;
        DirectX::Image normalized = *current;
        normalized.format = DirectX::MakeTypelessUNORM(normalized.format);
        const auto rgbaFormat = DirectX::IsSRGB(normalized.format) ?
            DXGI_FORMAT_R8G8B8A8_UNORM_SRGB : DXGI_FORMAT_R8G8B8A8_UNORM;
        if (DirectX::IsCompressed(normalized.format))
        {
            if (FAILED(DirectX::Decompress(normalized, rgbaFormat, decompressed)))
            {
                result.error = "Image compression is unsupported.";
                return result;
            }
            current = decompressed.GetImage(0, 0, 0);
        }
        else current = &normalized;
        if (current->format != DXGI_FORMAT_R8G8B8A8_UNORM && current->format != DXGI_FORMAT_R8G8B8A8_UNORM_SRGB)
        {
            if (FAILED(DirectX::Convert(*current, rgbaFormat, DirectX::TEX_FILTER_DEFAULT,
                DirectX::TEX_THRESHOLD_DEFAULT, converted)))
            {
                result.error = "Image pixels could not be converted to RGBA.";
                return result;
            }
            current = converted.GetImage(0, 0, 0);
        }
        if (metadata.IsPMAlpha() && !opaque)
        {
            if (FAILED(DirectX::PremultiplyAlpha(*current, DirectX::TEX_PMALPHA_REVERSE, straight)))
            {
                result.error = "Image alpha could not be converted.";
                return result;
            }
            current = straight.GetImage(0, 0, 0);
        }

        size_t width = current->width, height = current->height;
        const double scale = (std::min)(1.0, double(maxDimension) / double((std::max)(width, height)));
        width = (std::max)(size_t(1), size_t(width * scale));
        height = (std::max)(size_t(1), size_t(height * scale));
        while (uint64_t(width) * height > maxOutputBytes / 4)
        {
            width = (std::max)(size_t(1), width / 2);
            height = (std::max)(size_t(1), height / 2);
        }
        if (width != current->width || height != current->height)
        {
            if (FAILED(DirectX::Resize(*current, width, height,
                static_cast<DirectX::TEX_FILTER_FLAGS>(DirectX::TEX_FILTER_FANT | DirectX::TEX_FILTER_FORCE_NON_WIC), resized)))
            {
                result.error = "Image could not be resized for preview.";
                return result;
            }
            current = resized.GetImage(0, 0, 0);
        }
        result.width = static_cast<uint32_t>(width);
        result.height = static_cast<uint32_t>(height);
        result.rgba.resize(width * height * 4);
        for (size_t y = 0; y < height; ++y)
            std::memcpy(result.rgba.data() + y * width * 4, current->pixels + y * current->rowPitch, width * 4);
        for (size_t i = 3; i < result.rgba.size(); i += 4)
        {
            if (opaque) result.rgba[i] = 255;
            else if (result.rgba[i] != 255) result.hasAlpha = true;
        }
        return result;
    }
}
