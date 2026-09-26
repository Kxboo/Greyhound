#pragma once

#include <cstdint>

#pragma region InfiniteWarfare

#pragma pack(push, 1)
struct IWXMaterial
{
    uint64_t NamePtr;

    uint8_t Padding[40];

    uint8_t ImageCount;

    uint8_t Padding2[15];

    uint64_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWXMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[4];
    uint64_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWPAKImageEntry
{
    uint64_t ImageOffset;
    uint64_t ImageEndOffset;
    uint64_t ImagePAKInfoPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWGfxMip
{
    uint16_t Width;
    uint16_t Height;

    uint8_t Padding[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWGfxImage
{
    uint64_t NextHead;
    uint8_t Padding[16];
    uint8_t ImageFormat;
    uint8_t Padding5[7];
    uint8_t MapType;
    uint8_t Padding2[7];
    uint32_t Size;
    uint32_t Size2;
    uint16_t LoadedWidth;
    uint16_t LoadedHeight;
    uint16_t LoadedDepth;
    uint16_t LoadedArrays;
    uint8_t Flags;
    uint8_t Streamed;
    uint8_t Padding3[14];
    uint16_t Width;
    uint16_t Height;
    uint8_t Padding4[4];
    IWGfxMip MipLevels[3];
    uint64_t NamePtr;
};
#pragma pack(pop)


#pragma pack(push, 1)
struct IWXModelSurface
{
    int8_t TileMode;
    int8_t Deformed;

    uint16_t VertexCount;
    uint16_t FacesCount;
    uint8_t VertListCount;
    uint8_t PaddingCount;

    uint16_t WeightCounts[8];

    uint8_t Padding[8];

    uint64_t VerticiesPtr;
    uint64_t FacesPtr;

    uint8_t Padding2[24];

    uint64_t RigidWeightsPtr;
    uint64_t WeightsPtr;

    uint8_t Padding3[0xA8];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWXModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint8_t Padding[40];

    uint64_t SurfsPtr;

    uint8_t Padding2[8];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWXModel
{
    uint64_t NamePtr;

    uint8_t Padding[3];

    uint8_t NumLods;
    uint8_t MaxLods;

    uint8_t Padding2[7];

    uint8_t NumBones;
    uint8_t NumRootBones;
    uint8_t NumSurfaces;
    uint8_t LodRampType;

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

    IWXModelLod ModelLods[6];

    uint8_t Padding4[0x80];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWXAnim
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
    uint64_t DeltaPartsPtr;

    uint8_t Padding[0xC];

    float Framerate;

    uint8_t Padding2[0xC];

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

    uint8_t Padding3[5];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct IWXAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma endregion

#pragma pack(push, 1)
struct IWXModelSurfaceT
{
    int8_t TileMode;
    int8_t Deformed;

    uint16_t VertexCount;
    uint16_t FacesCount;
    uint8_t VertListCount;
    uint8_t PaddingCount;

    uint16_t WeightCounts[8];

    uint8_t Padding[8];

    uint64_t VerticiesPtr;
    uint64_t FacesPtr;

    uint8_t Padding2[24];

    uint64_t RigidWeightsPtr;
    uint64_t WeightsPtr;

    uint8_t Padding3[0xA8];
};
#pragma pack(pop)
