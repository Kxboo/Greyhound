#pragma once

#include <cstdint>
#include <cstddef>

#pragma pack(push, 1)
struct MW4XModelLod
{
    uint64_t MeshPtr;
    uint64_t SurfsPtr;

    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint8_t Padding[40];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XModel
{
    uint64_t NamePtr;
    uint16_t NumSurfaces;
    uint8_t NumLods;
    uint8_t MaxLods;

    uint8_t Padding[8];

    uint8_t NumBones;
    uint8_t NumRootBones;
    uint16_t UnkBoneCount;

    uint8_t Padding3[0x80];

    uint64_t BoneIDsPtr;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;
    uint64_t UnknownPtr;
    uint64_t UnknownPtr2;
    uint64_t MaterialHandlesPtr;

    MW4XModelLod ModelLods[6];

    uint8_t Padding4[80];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XModelMesh
{
    uint64_t NamePtr;
    uint64_t SurfsPtr;
    uint64_t LODStreamKey;
    uint8_t Padding[0x18];

    uint64_t MeshBufferPointer;
    uint16_t NumSurfs;
    uint8_t Padding2[38];

};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XModelMeshBufferInfo
{
    uint64_t BufferPtr; // 0 if the model is not loaded, otherwise a pointer, even if streamed
    uint32_t BufferSize;
    uint32_t Streamed;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XModelSurface
{
    uint16_t StatusFlag;
    uint16_t VertexCount;
    uint16_t FacesCount;
    uint16_t Padding6;
    uint8_t VertListCount;

    uint8_t PaddingNew[11];
    uint16_t WeightCounts[8];
    uint8_t Padding1[4];

    // Offset 1 - Vertex Data (Offsets and UV)
    // Offset 2 - Face Indices
    // Offset 3 - Unknown, 24-bytes per entry, count not found
    // Offset 4 - Vertex Colours, not always present (4 * Vertex Count)
    // Offset 5 - Unknown, Half Floats that work when parsed as UVs (4 * Vertex Count)
    // Offset 6 - Unknown, might be normal values, not always present (4 * Vertex Count)
    // Offset 7 - Not seen yet; Always -1
    // Offset 8 - Not seen yet; Always -1
    uint32_t Offsets[12];

    uint64_t MeshBufferPointer;
    uint64_t Padding3;
    uint64_t RigidWeightsPtr;
    uint64_t WeightsPtr;

    uint8_t Padding4[40];

    float XOffset;
    float YOffset;
    float ZOffset;
    float Scale;
    float Min;
    float Max;
    uint8_t Padding5[24];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4GfxMip
{
    uint64_t HashID;
    uint8_t Padding[24];
    uint32_t Size;
    uint16_t Width;
    uint16_t Height;
};
#pragma pack(pop)

#pragma pack(push, 1)
template <size_t Size>
struct MW4GfxMipArray
{
    MW4GfxMip Levels[Size];

    size_t GetImageSize(size_t i)
    {
        if (i == 0)
            return (size_t)(Levels[i].Size >> 4);
        else
            return (size_t)((Levels[i].Size >> 4) - (Levels[i - 1].Size >> 4));
    }

    size_t GetMipCount()
    {
        return Size;
    }
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4GfxImage
{
    uint64_t NamePtr;

    uint8_t Padding[12];

    uint8_t ImageFormat;

    uint8_t Padding2[15];

    uint16_t LoadedMipWidth;
    uint16_t LoadedMipHeight;

    uint8_t Padding3[10];

    uint8_t LoadedMipLevels;

    uint8_t Padding4[5];

    MW4GfxMipArray<4> Mips;

    uint8_t Padding5[16];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XAnim
{
    uint64_t NamePtr;

    uint64_t BoneIDsPtr;
    uint64_t DataBytePtr;
    uint64_t DataShortPtr;
    uint64_t DataIntPtr;
    uint64_t RandomDataShortPtr;
    uint64_t RandomDataBytePtr;
    uint64_t RandomDataIntPtr;
    uint64_t LongIndiciesPtr;
    uint64_t NotificationsPtr;
    uint8_t PaddingNew[0x8];
    uint64_t DeltaPartsPtr;
    uint8_t Padding[0xC];

    float Framerate;

    uint8_t Padding2[14];

    uint16_t NumFrames;
    uint8_t Flags;

    uint8_t NoneRotatedBoneCount;
    uint8_t TwoDRotatedBoneCount;
    uint8_t NormalRotatedBoneCount;
    uint8_t TwoDStaticRotatedBoneCount;
    uint8_t NormalStaticRotatedBoneCount;
    uint8_t NormalTranslatedBoneCount;
    uint8_t PreciseTranslatedBoneCount;
    uint8_t StaticTranslatedBoneCount;
    uint8_t NoneTranslatedBoneCount;
    uint8_t TotalBoneCount;

    uint8_t NotificationCount;

    uint8_t AssetType;

    uint8_t Padding3[27];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XMaterial
{
    uint64_t NamePtr;
    uint8_t Padding[20];
    uint8_t ImageCount;
    uint8_t Padding2[35];
    uint64_t TechsetPtr;
    uint64_t ImageTablePtr;
    uint8_t Padding3[40];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4XMaterialImage
{
    uint32_t Type;
    uint8_t Padding[4];
    uint64_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW4SoundBank
{
    uint64_t NamePtr;
    uint64_t BankNamePtr;
    uint64_t LanguagePtr;
    uint64_t TypePtr;
    uint64_t AliasCount;
    uint64_t AliasesPtr;
    uint8_t Padding[448];
    uint64_t SoundBankPtr;
    uint64_t Unk1;
};
#pragma pack(pop)
