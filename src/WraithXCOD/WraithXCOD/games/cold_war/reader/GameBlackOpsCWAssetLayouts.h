#pragma once

#include <cstdint>

#pragma region Black Ops Cold War

#pragma pack(push, 1)
struct BOCWSoundAsset
{
    uint64_t NamePtr;
    uint32_t FrameCount;
    uint8_t FrameRateIndex;
    uint8_t ChannelCount;
    uint8_t Looping;
    uint8_t Format;
    uint32_t Unknown2;
    uint32_t BufferSize;
    uint8_t Padding[32];
    uint64_t StreamKey;
    uint64_t StreamInfoPtr;
    uint8_t Padding1[16];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXAnim
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
    uint64_t DataIntPtr;
    uint64_t UnknownZero2;
    uint64_t DataShortPtr;
    uint64_t RandomDataShortPtr;
    uint8_t Unknown3[0x18];
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
struct BOCWGfxMip
{
    uint64_t HashID;

    uint8_t Padding[0x10];

    uint32_t Size;
    uint16_t Width;
    uint16_t Height;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWGfxImage
{
    uint64_t NamePtr;
    uint64_t UnknownPtr1;
    uint64_t UnknownZero;
    uint64_t UnknownZero2;
    uint64_t UnknownZero3;
    uint64_t LoadedMipPtr;
    uint64_t GfxMipsPtr;
    uint8_t Padding[96];
    uint32_t LoadedMipSize;
    uint32_t ImageFormat;
    uint16_t LoadedMipWidth;
    uint16_t LoadedMipHeight;
    uint8_t LoadedMipLevels;
    uint8_t Padding1[19];
    uint8_t GfxMipMaps;
    uint8_t Padding2[23];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXMaterial
{
    uint64_t NamePtr;
    uint8_t Padding[0x20];
    uint64_t TechsetPtr;
    uint64_t ImageTablePtr;
    uint8_t Padding2[0x110];
    uint8_t ImageCount;
    uint8_t Padding3[15];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXSkeleton
{
    uint64_t NamePtr;
    uint64_t BoneIDsPtr;
    uint64_t UnknownPtr2;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;
    uint64_t UnknownPtr1;
    uint16_t BoneCounts[4];
    uint64_t UnknownZero2;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXModel
{
    uint64_t NamePtr;
    uint64_t XSkeletonPtr;
    uint64_t XCollisionPtr;
    uint64_t UnknownPtr2;
    uint64_t ModelLodPtrs[8];
    uint64_t MaterialHandlesPtr;
    uint64_t UnknownPtr4;
    uint16_t NumLods;
    uint16_t UnkValue01;
    uint8_t Padding3[0x74];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXModelLod
{
    uint64_t NamePtr;
    uint64_t XSurfacePtr;
    uint64_t XModelMeshPtr;
    uint64_t UnknownPtr;
    uint64_t LODStreamKey;
    uint8_t Padding[0x10];
    float LodDistance;
    uint8_t NumSurfs;
    uint8_t SurfacesIndex;
    uint16_t Pad;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXModelSurface
{
    uint8_t Flag1;
    uint8_t Flag2;
    uint16_t VertexCount;
    uint16_t FacesCount;
    uint16_t Padding;
    uint32_t VerticiesIndex;
    uint32_t FacesIndex;
    uint8_t Padding2[0x20];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BOCWXModelMeshInfo
{
    uint8_t StatusFlag;
    uint8_t Flag2;
    uint8_t Flag3;
    uint8_t Flag4;

    uint32_t VertexCount;
    uint32_t WeightCount;
    uint32_t FacesCount;
    uint32_t BlendCount;
    uint32_t BlendShapeCount;
    uint8_t Padding[0x8];

    uint64_t XModelMeshBufferPtr;
    uint32_t XModelMeshBufferSize;

    uint32_t VertexOffset;
    uint32_t UVOffset;
    uint32_t FacesOffset;
    uint32_t WeightsOffset;
    uint32_t BlendshapesOffset;

    uint8_t UnknownData[360];

    uint32_t FuckKnows;
    uint32_t ShapeCount;
    uint32_t FuckKnowsAgain;
    uint32_t HowTheFuck;
    uint64_t BlendShapeNames;
    uint64_t BlendShapeIndexes;
    uint64_t BlendShapeCounts;
};
#pragma pack(pop)

#pragma endregion
