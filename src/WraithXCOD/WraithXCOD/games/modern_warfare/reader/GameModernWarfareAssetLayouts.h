#pragma once

#include <cstdint>

#pragma region Modern Warfare

#pragma pack(push, 1)
struct MWXMaterial
{
    uint32_t NamePtr;

    uint8_t Padding[0x36];

    uint8_t ImageCount;

    uint8_t Padding2[9];

    uint32_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWXMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[4];
    uint32_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWGfxImage
{
    uint8_t Padding[0x18];

    uint16_t Width;
    uint16_t Height;

    uint8_t Padding2[2];

    uint8_t MipLevels;
    uint8_t Streamed;

    uint32_t NamePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWXModelSurface
{
    int8_t TileMode;
    int8_t Deformed;

    uint16_t VertexCount;
    uint16_t FacesCount;

    uint8_t Padding[6];

    uint32_t FacesPtr;

    uint16_t WeightCounts[4];
    uint32_t WeightsPtr;
    uint32_t VerticiesPtr;

    uint32_t VertListCount;
    uint32_t RigidWeightsPtr;

    uint32_t PartBits[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWXModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint32_t PartBits[5];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWXModel
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

    MWXModelLod ModelLods[4];

    uint8_t Padding[0xC];

    uint32_t BoneInfoPtr;

    uint8_t Padding2[0x1C];

    uint16_t NumLods;

    uint8_t Padding3[0x16];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWXAnimDeltaParts
{
    uint32_t DeltaTranslationsPtr;
    uint32_t Delta2DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWXAnim
{
    uint32_t NamePtr;

    uint8_t Padding[10];

    uint16_t NumFrames;
    uint8_t Looped;
    uint8_t isDelta;

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
struct MWLoadedSound
{
    uint32_t NamePtr;
    uint32_t UnknownInt;
    uint32_t SoundDataPtr;
    uint32_t SoundDataSize;
    uint32_t FrameRate;
    uint32_t BitsPerSample;
    uint32_t Channels;
    uint32_t FrameCount;
    uint32_t UnknownInt2;
    uint32_t UnknownPtr;
    uint32_t UnknownPtr2;
};
#pragma pack(pop)

#pragma endregion
