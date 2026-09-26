#pragma once

#include <cstdint>

#pragma region Black Ops 1

#pragma pack(push, 1)
const struct BOFxEffectDef
{
    uint32_t NamePtr;

    uint8_t Flags;
    uint8_t EFPriority;
    uint8_t Reserved[2];

    uint32_t TotalSize;
    uint32_t MSECLoopingLife;

    uint32_t ElemDefCountLooping;
    uint32_t ElemDefCountOneShot;
    uint32_t ElemDefCountEmission;

    uint32_t FxElementsPtr;

    float BoundingBoxDim[3];
    float BoundingSphere[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXMaterial
{
    uint32_t NamePtr;

    uint8_t Padding[166];

    uint8_t ImageCount;

    uint8_t Padding2[9];

    uint32_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[8];
    uint32_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOGfxImage
{
    uint8_t Padding[20];

    uint16_t Width;
    uint16_t Height;

    uint8_t Padding2[2];

    uint8_t MipLevels;
    uint8_t Streamed;

    uint8_t Padding3[16];

    uint32_t NamePtr;
    uint32_t Hash;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint32_t PartBits[6];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXModel
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

    BOXModelLod ModelLods[4];

    uint8_t Padding[0x10];

    uint32_t BoneInfoPtr;

    uint8_t Padding2[0x1C];

    uint16_t NumLods;

    uint8_t Padding3[0x22];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXModelSurface
{
    int8_t TileMode;
    int8_t VertListCount;

    uint16_t Flags;
    uint16_t VertexCount;
    uint16_t FacesCount;
    uint16_t BaseTriIndex;
    uint16_t BaseVertIndex;

    uint32_t FacesPtr;

    uint16_t WeightCounts[4];
    uint32_t WeightsPtr;
    uint32_t TensionPtr;

    uint32_t VerticiesPtr;
    uint32_t D3DVBufferPtr;
    uint32_t RigidWeightsPtr;
    uint32_t D3DIBufferPtr;

    uint32_t PartBits[5];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXAnimDeltaParts
{
    uint32_t DeltaTranslationsPtr;
    uint32_t Delta2DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOXAnim
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
struct BOXRawFile
{
    uint32_t NamePtr;

    uint32_t AssetSize;
    uint32_t RawDataPtr;
};
#pragma pack(pop)

#pragma endregion
