#include "assets/preview/PreviewImage.h"
#include "DirectXTex.h"

#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <vector>

namespace
{
    std::vector<uint8_t> DDS(const DirectX::ScratchImage& Image, uint32_t AlphaMode = 0)
    {
        auto Metadata = Image.GetMetadata();
        Metadata.SetAlphaMode(static_cast<DirectX::TEX_ALPHA_MODE>(AlphaMode));
        DirectX::Blob Blob;
        assert(SUCCEEDED(DirectX::SaveToDDSMemory(Image.GetImages(), Image.GetImageCount(),
            Metadata, DirectX::DDS_FLAGS_FORCE_DX10_EXT_MISC2, Blob)));
        const auto* Start = static_cast<const uint8_t*>(Blob.GetBufferPointer());
        return { Start, Start + Blob.GetBufferSize() };
    }
}

int main()
{
    DirectX::ScratchImage Pixels;
    assert(SUCCEEDED(Pixels.Initialize2D(DXGI_FORMAT_R8G8B8A8_UNORM, 4, 4, 1, 1)));
    auto* Raw = Pixels.GetPixels();
    for (size_t I = 0; I < 16; ++I)
    {
        Raw[I * 4] = 80; Raw[I * 4 + 1] = 120; Raw[I * 4 + 2] = 160;
        Raw[I * 4 + 3] = I == 0 ? 0 : I == 1 ? 128 : 255;
    }
    auto Bytes = DDS(Pixels);
    auto Decoded = PreviewData::DecodeDDS(Bytes.data(), Bytes.size(), 1024, 4096);
    assert(Decoded.error.empty() && Decoded.width == 4 && Decoded.height == 4);
    assert(Decoded.sourceWidth == 4 && Decoded.sourceHeight == 4 && Decoded.hasAlpha);
    assert(Decoded.rgba.size() == 64 && std::memcmp(Decoded.rgba.data(), Raw, 64) == 0);

    auto Opaque = PreviewData::DecodeDDS(Bytes.data(), Bytes.size(), 1024, 4096, true);
    assert(Opaque.error.empty() && !Opaque.hasAlpha);
    assert(Opaque.rgba[0] == 80 && Opaque.rgba[3] == 255 && Opaque.rgba[7] == 255);
    auto Small = PreviewData::DecodeDDS(Bytes.data(), Bytes.size(), 2, 4096);
    assert(Small.error.empty() && Small.width == 2 && Small.height == 2 && Small.rgba.size() == 16);
    auto Budget = PreviewData::DecodeDDS(Bytes.data(), Bytes.size(), 1024, 16);
    assert(Budget.error.empty() && Budget.rgba.size() <= 16);

    // Color compressed through the same DirectXTex DDS path as game handlers.
    DirectX::ScratchImage Compressed;
    assert(SUCCEEDED(DirectX::Compress(Pixels.GetImages(), Pixels.GetImageCount(), Pixels.GetMetadata(),
        DXGI_FORMAT_BC3_UNORM, DirectX::TEX_COMPRESS_DEFAULT, 1.f, Compressed)));
    auto BC3 = DDS(Compressed);
    auto DecodedBC3 = PreviewData::DecodeDDS(BC3.data(), BC3.size(), 1024, 4096);
    assert(DecodedBC3.error.empty() && DecodedBC3.hasAlpha && DecodedBC3.rgba[3] == 0);
    assert(DecodedBC3.rgba.size() == 64 && DecodedBC3.rgba[7] < 200);

    // Premultiplied channels become straight alpha for WebGL's texture contract.
    for (size_t I = 0; I < 16; ++I)
    {
        Raw[I * 4] = 64; Raw[I * 4 + 1] = 32; Raw[I * 4 + 2] = 16; Raw[I * 4 + 3] = 128;
    }
    auto Premultiplied = DDS(Pixels, DirectX::TEX_ALPHA_MODE_PREMULTIPLIED);
    auto Straight = PreviewData::DecodeDDS(Premultiplied.data(), Premultiplied.size(), 1024, 4096);
    assert(Straight.error.empty() && Straight.hasAlpha);
    assert(Straight.rgba[0] >= 126 && Straight.rgba[0] <= 129 && Straight.rgba[3] == 128);

    DirectX::ScratchImage Array;
    assert(SUCCEEDED(Array.Initialize2D(DXGI_FORMAT_R8G8B8A8_UNORM, 4, 4, 2, 1)));
    std::memset(Array.GetPixels(), 255, Array.GetPixelsSize());
    auto ArrayBytes = DDS(Array);
    auto First = PreviewData::DecodeDDS(ArrayBytes.data(), ArrayBytes.size(), 1024, 4096);
    assert(First.error.empty() && First.firstSlice && First.rgba.size() == 64);
    assert(!PreviewData::DecodeDDS(nullptr, 0, 1024, 4096).error.empty());
    assert(!PreviewData::DecodeDDS(Bytes.data(), 127, 1024, 4096).error.empty());
    assert(!PreviewData::DecodeDDS(Bytes.data(), Bytes.size(), 0, 4096).error.empty());
    assert(!PreviewData::DecodeDDS(Bytes.data(), Bytes.size(), 1024, 3).error.empty());
    auto Corrupt = Bytes;
    Corrupt[0] = 0;
    assert(!PreviewData::DecodeDDS(Corrupt.data(), Corrupt.size(), 1024, 4096).error.empty());
    std::cout << "Preview DDS RGBA, alpha, BC3, resize, budgets, arrays and malformed inputs passed\n";
}
