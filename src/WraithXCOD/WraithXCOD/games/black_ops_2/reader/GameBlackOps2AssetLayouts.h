#pragma once

#include <cstdint>

#pragma region Black Ops 2

#pragma pack(push, 1)
const struct BO2FxEffectDef
{
    uint32_t NamePtr;

    uint16_t Flags;
    uint16_t EFPriority;

    uint16_t ElemDefCountLooping;
    uint16_t ElemDefCountOneShot;
    uint16_t ElemDefCountEmission;

    uint16_t Padding;

    uint32_t TotalSize;
    uint32_t MSECLoopingLife;
    uint32_t MSECNonLoopingLife;

    uint32_t FxElementsPtr;

    float BoundingBoxDim[3];
    float BoundingCenter[3];

    float OcclusionQueryDepthBias;

    uint32_t OcclusionQueryFadeIn;
    uint32_t OcclusionQueryFadeOut;

    float OcclusionQueryScaleRange[2];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XMaterial
{
    uint32_t NamePtr;

    uint8_t Padding[80];

    uint8_t ImageCount;

    uint8_t Padding2[11];

    uint32_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[8];
    uint32_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2GfxImage
{
    uint8_t Padding[20];

    uint16_t Width;
    uint16_t Height;

    uint8_t Padding2[2];

    uint8_t MipLevels;
    uint8_t Streamed;

    uint8_t Padding3[12];

    uint32_t KeyLower;

    uint8_t Padding4[28];

    uint32_t NamePtr;
    uint32_t KeyUpper;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint32_t PartBits[5];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XModel
{
    uint32_t NamePtr;
    uint8_t NumBones;
    uint8_t NumRootBones;
    uint8_t NumSurfaces;
    uint8_t LodRampType;

    uint32_t BoneIDsPtr;
    uint32_t ParentListPtr;
    uint32_t RotationsPtr;
    uint32_t TranslationsPtr;
    uint32_t PartClassificationPtr;
    uint32_t BaseMatriciesPtr;
    uint32_t SurfacesPtr;
    uint32_t MaterialHandlesPtr;

    BO2XModelLod ModelLods[4];

    uint8_t Padding[0xC];

    uint32_t BoneInfoPtr;

    uint8_t Padding2[0x1C];

    uint16_t NumLods;

    uint8_t Padding3[0x32];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XModelSurface
{
    int8_t TileMode;
    int8_t VertListCount;

    uint16_t Flags;
    uint16_t VertexCount;
    uint16_t FacesCount;
    uint16_t BaseVertIndex;
    uint16_t BaseTriIndex;

    uint32_t FacesPtr;

    uint16_t WeightCounts[4];
    uint32_t WeightsPtr;
    uint32_t TensionPtr;

    uint32_t VerticiesPtr;
    uint32_t D3DVBufferPtr;
    uint32_t RigidWeightsPtr;
    uint32_t D3DIBufferPtr;

    uint32_t PartBits[5];

    uint8_t Padding[0xC];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XAnim
{
    uint32_t NamePtr;

    uint8_t Padding[10];

    uint16_t NumFrames;
    uint8_t Looped;
    uint8_t isDelta;

    uint8_t Padding2[0x6];

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

    uint8_t Padding3[11];

    float Framerate;
    float Frequency;

    uint8_t Padding4[0x8];

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
struct BO2XAnimDeltaParts
{
    uint32_t DeltaTranslationsPtr;
    uint32_t Delta2DRotationsPtr;
    uint32_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO2XRawFile
{
    uint32_t NamePtr;

    uint32_t AssetSize;
    uint32_t RawDataPtr;
};
#pragma pack(pop)

#pragma endregion
