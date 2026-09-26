// Integration test: actual exporter -> independently parsed DDS -> unchanged samples.
#include "stdafx.h"
#include "exporters/CoDRawImageTranslator.h"
#include <stdexcept>
#include <fstream>

static std::string OutputDirectory;

static void Check(bool Condition, const char* Message)
{
    if (!Condition) throw std::runtime_error(Message);
}

static void RoundTrip(uint8_t Format, uint32_t Width, uint32_t Height,
    uint32_t BytesPerPixel, uint32_t Levels = 1)
{
    uint32_t Size = 0;
    for (uint32_t L = 0; L < Levels; ++L)
        Size += std::max(1u, Width >> L) * std::max(1u, Height >> L) * BytesPerPixel;
    auto Raw = std::make_unique<uint8_t[]>(Size);
    // Includes zeros, all-one bits, and arbitrary integer bit patterns.
    for (uint32_t I = 0; I < Size; ++I) Raw[I] = uint8_t(I * 73u + (I >> 3));
    const auto DDS = CoDRawImageTranslator::TranslateBC(Raw, Size, Width, Height, Format, Levels);
    Check(DDS && DDS->DataBuffer, "export failed");
    DirectX::TexMetadata Metadata{};
    DirectX::ScratchImage Decoded;
    Check(SUCCEEDED(DirectX::LoadFromDDSMemory(DDS->DataBuffer, DDS->DataSize,
        DirectX::DDS_FLAGS_NONE, &Metadata, Decoded)), "DDS reader rejected export");
    Check(Metadata.format == DXGI_FORMAT(Format), "DDS format changed sample interpretation");
    Check(Metadata.width == Width && Metadata.height == Height && Metadata.mipLevels == Levels,
        "DDS dimensions or mip count changed");
    size_t Offset = 0;
    for (uint32_t L = 0; L < Levels; ++L)
    {
        const auto* Image = Decoded.GetImage(L, 0, 0);
        Check(Image != nullptr, "missing mip");
        const size_t RowBytes = std::max(1u, Width >> L) * BytesPerPixel;
        for (size_t Row = 0; Row < Image->height; ++Row)
        {
            Check(memcmp(Raw.get() + Offset, Image->pixels + Row * Image->rowPitch, RowBytes) == 0,
                "raw samples changed");
            Offset += RowBytes;
        }
    }
    Check(Offset == Size, "not every input byte was verified");
    if (!OutputDirectory.empty())
    {
        const auto Name = OutputDirectory + "/format_" + std::to_string(Format) + "_" +
            std::to_string(Width) + "x" + std::to_string(Height) + ".dds";
        std::ofstream File(Name, std::ios::binary);
        File.write(reinterpret_cast<const char*>(DDS->DataBuffer), DDS->DataSize);
        Check(File.good(), "could not save integration fixture");
    }
}

int main(int Argc, char** Argv)
{
    if (Argc > 1) OutputDirectory = Argv[1];
    try
    {
        RoundTrip(56, 1024, 1024, 2); // Saved CW heightfield dimensions.
        RoundTrip(42, 128, 256, 4);   // Packed 8x4 hole bits.
        RoundTrip(42, 129, 129, 4);   // Non-power-of-two control grid.
        RoundTrip(62, 1024, 1024, 1); // Existing categorical index format.
        RoundTrip(56, 8, 4, 2, 3);
        RoundTrip(42, 3, 5, 4);
        std::cout << "6 terrain DDS round trips passed; all payload bytes unchanged\n";
        return 0;
    }
    catch (const std::exception& Error)
    {
        std::cerr << Error.what() << '\n';
        return 1;
    }
}
