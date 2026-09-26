#pragma once

#include <cstdint>

#pragma region Black Ops 4

#pragma pack(push, 1)
struct BO4XMaterialImage
{
    uint64_t ImagePtr;
    uint32_t SemanticHash;
    uint8_t Padding[0x14];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4XMaterial
{
    uint64_t NamePtr;
    uint64_t Unk01;

    uint8_t Padding[0x28];

    uint64_t ImageTablePtr;

    uint8_t Padding2[0xF0];

    uint8_t ImageCount;

    uint8_t Padding3[7];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4GfxMip
{
    uint64_t HashID;

    uint8_t Padding[0x18];

    uint32_t Size;
    uint16_t Width;
    uint16_t Height;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4GfxImageOriginal // Leaving this here in case they switch it back
{
    uint64_t NamePtr;

    uint64_t UnknownPtr1;
    uint64_t UnknownZero;

    uint64_t LoadedMipPtr;

    uint64_t UnknownHash;
    uint64_t UnknownZero2;

    BO4GfxMip MipLevels[4];

    uint8_t Padding[0x28];

    uint32_t LoadedMipSize;
    uint32_t ImageFormat;

    uint16_t LoadedMipWidth;
    uint16_t LoadedMipHeight;
    uint8_t LoadedMipLevels;

    uint8_t Padding2[0x1B];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4GfxImage
{
    uint64_t UnknownPtr;

    uint64_t UnknownPtr1;
    uint64_t UnknownZero;

    uint64_t LoadedMipPtr;

    uint64_t NamePtr;
    uint64_t UnknownZero2;

    uint64_t GfxMipsPtr;

    uint8_t Padding[0x28];

    uint32_t LoadedMipSize;
    uint32_t ImageFormat;

    uint16_t LoadedMipWidth;
    uint16_t LoadedMipHeight;
    uint8_t LoadedMipLevels;

    uint8_t Padding2[0x10];

    uint8_t GfxMipMaps;

    uint8_t Padding3[0xA];


};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4XModelMeshInfo
{
    uint8_t StatusFlag;
    uint8_t Flag2;
    uint8_t Flag3;
    uint8_t Flag4;

    uint32_t VertexCount;
    uint32_t WeightCount;
    uint32_t FacesCount;

    uint8_t Padding[0x10];

    uint64_t XModelMeshBufferPtr;
    uint32_t XModelMeshBufferSize;

    uint32_t VertexOffset;
    uint32_t UVOffset;
    uint32_t FacesOffset;
    uint32_t WeightsOffset;
};
#pragma pack(pop)


#pragma pack(push, 1)
struct BO4XModelSurface
{
    uint8_t Flag1;
    uint8_t Flag2;
    uint8_t Flag3;
    uint8_t Flag4;

    uint16_t VertexCount;
    uint16_t FacesCount;

    uint32_t VerticiesIndex;
    uint32_t FacesIndex;

    uint8_t Padding[0x20];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4XModelLod
{
    uint64_t UnknownZero;
    uint64_t NameHash;
    uint64_t XSurfacePtr;
    uint64_t XModelMeshPtr;
    uint64_t UnknownPtr;

    uint64_t LODStreamKey;

    uint8_t Padding[0x18];

    float LodDistance;

    uint8_t NumSurfs;
    uint8_t SurfacesIndex;

    uint16_t UnknownFlags;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4XModel
{
    uint64_t NamePtr;
    uint64_t UnknownZero;
    uint64_t BoneIDsPtr;
    uint64_t UnknownPtr2;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;
    uint64_t UnknownPtr1;

    uint8_t Padding[0x28];

    uint64_t ModelLodPtrs[8];

    uint64_t MaterialHandlesPtr;
    uint64_t UnknownPtr4;

    uint32_t NumLods;

    uint8_t Padding3[0x78];

    uint16_t NumCosmeticBones;

    uint8_t Padding4[0x5];

    uint8_t NumBones;
    uint8_t NumRootBones;
    uint16_t NumUnknown;
    uint8_t Padding5;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4XAnim
{
    uint64_t UnknownPtr;
    uint64_t BoneIDsPtr;
    uint64_t UnknownZero1;
    uint64_t DeltaPartsPtr;

    uint8_t Unknown1[0x10];

    uint64_t UnknownPtr2;
    uint64_t NotificationsPtr;

    uint8_t Unknown2[0x18];

    uint64_t DataBytePtr;
    uint64_t UnknownZero3;
    uint64_t RandomDataBytePtr;

    uint64_t NamePtr;
    uint64_t UnknownZero;

    uint64_t DataIntPtr;
    uint64_t UnknownZero2;
    uint64_t DataShortPtr;
    uint64_t RandomDataShortPtr;

    uint8_t Unknown3[0x20];

    float Framerate;
    float Frequency;

    uint8_t Unknown4[0x34];

    uint16_t NoneRotatedBoneCount;
    uint16_t TwoDRotatedBoneCount;
    uint16_t NormalRotatedBoneCount;
    uint16_t TwoDStaticRotatedBoneCount;
    uint16_t NormalStaticRotatedBoneCount;
    uint16_t NormalTranslatedBoneCount;
    uint16_t PreciseTranslatedBoneCount;
    uint16_t StaticTranslatedBoneCount;
    uint16_t NoneTranslatedBoneCount;
    uint16_t TotalBoneCount;

    uint8_t NotificationCount;
    uint8_t AssetType;
    uint16_t Unknown6;

    uint16_t NumFrames;

    uint8_t Unknown[0x1A];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO4XAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma endregion
