#pragma once

#include <cstdint>

#pragma region Modern Warfare 3

#pragma pack(push, 1)
struct MW3XMaterial
{
    uint32_t NamePtr;

    uint8_t Padding[0x4A];

    uint8_t ImageCount;

    uint8_t Padding2[9];

    uint32_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3XMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[4];
    uint32_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3GfxImage
{
    uint8_t Padding[0x14];

    uint16_t Width;
    uint16_t Height;

    uint8_t MipLevels;
    uint8_t Streamed;

    uint8_t Padding2[2];

    uint32_t NamePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3XModelSurface
{
    int8_t TileMode;
    int8_t Deformed;

    uint16_t VertexCount;
    uint16_t FacesCount;

    uint8_t Padding[0xA];

    uint32_t FacesPtr;

    uint16_t WeightCounts[4];
    uint32_t WeightsPtr;
    uint32_t VerticiesPtr;

    uint32_t VertListCount;
    uint32_t RigidWeightsPtr;

    uint32_t PartBits[6];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3XModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint8_t Padding[28];

    uint32_t SurfsPtr;

    uint8_t Padding2[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3XModel
{
    uint32_t NamePtr;
    uint8_t NumBones;
    uint8_t NumRootBones;
    uint8_t NumSurfaces;
    uint8_t LodRampType;

    uint8_t Padding[0x1C];

    uint32_t BoneIDsPtr;
    uint32_t ParentListPtr;
    uint32_t RotationsPtr;
    uint32_t TranslationsPtr;
    uint32_t PartClassificationPtr;
    uint32_t BaseMatriciesPtr;
    uint32_t MaterialHandlesPtr;

    MW3XModelLod ModelLods[4];

    uint8_t MaxLods;
    uint8_t NumLods;

    uint8_t Padding2[0x42];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3XAnim
{
    uint32_t NamePtr;

    uint8_t Padding[10];

    uint16_t NumFrames;
    uint8_t Looped;

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
    uint8_t isDefault;

    uint8_t Padding3[10];

    float Framerate;
    float Frequency;

    uint32_t BoneIDsPtr;
    uint32_t DataBytePtr;
    uint32_t DataShortPtr;
    uint32_t DataIntPtr;
    uint32_t RandomDataShortPtr;
    uint32_t RandomDataBytePtr;
    uint32_t RandomDataIntPtr;
    uint32_t LongIndiciesPtr;
    uint32_t NotificationsPtr;
    uint32_t DeltaPartsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MW3XAnimDeltaParts
{
    uint32_t DeltaTranslationsPtr;
    uint32_t Delta2DRotationsPtr;
    uint32_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma endregion
