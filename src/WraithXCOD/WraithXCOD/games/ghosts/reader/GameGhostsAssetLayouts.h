#pragma once

#include <cstdint>

#pragma region Ghosts

#pragma pack(push, 1)
const struct GhostsFxEffectDef
{
    uint64_t NamePtr;

    uint32_t Flags;
    uint32_t TotalSize;
    uint32_t MSECLoopingLife;

    uint32_t ElemDefCountLooping;
    uint32_t ElemDefCountOneShot;
    uint32_t ElemDefCountEmission;

    float ElemMaxRadius;
    float OcclusionQueryDepthBias;

    uint32_t OcclusionQueryFadeIn;
    uint32_t OcclusionQueryFadeOut;

    float OcclusionQueryScaleRange[2];

    uint64_t FxElementsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsXMaterial
{
    uint64_t NamePtr;

    uint8_t Padding[0x1BC];

    uint8_t ImageCount;

    uint8_t Padding2[19];

    uint64_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsXMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[4];
    uint64_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsPAKImageEntry
{
    uint64_t ImageOffset;
    uint64_t ImageEndOffset;
    uint64_t ImagePAKInfoPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsGfxMip
{
    uint16_t Width;
    uint16_t Height;

    uint8_t Padding[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsGfxImage
{
    uint64_t NextHead;

    uint8_t Padding[16];

    uint8_t ImageFormat;
    uint8_t Padding5[3];
    uint8_t MapType;

    uint8_t Padding2[24];

    uint8_t Streamed;

    uint8_t Padding3[10];

    uint16_t Width;
    uint16_t Height;

    uint8_t Padding4[4];

    GhostsGfxMip MipLevels[3];

    uint64_t NamePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsXModelSurface
{
    int8_t TileMode;
    int8_t Deformed;

    uint16_t VertexCount;
    uint16_t FacesCount;
    uint8_t VertListCount;
    uint8_t PaddingCount;

    uint16_t WeightCounts[8];

    uint64_t VerticiesPtr;
    uint64_t FacesPtr;

    uint8_t Padding[24];

    uint64_t RigidWeightsPtr;
    uint64_t WeightsPtr;

    uint8_t Padding2[0x98];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsXModelLod
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
struct GhostsXModel
{
    uint64_t NamePtr;
    uint8_t NumBones;
    uint8_t NumRootBones;
    uint8_t NumSurfaces;
    uint8_t LodRampType;

    uint8_t Padding[0x24];

    uint64_t BoneIDsPtr;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;
    uint64_t UnknownPtr;
    uint64_t MaterialHandlesPtr;

    GhostsXModelLod ModelLods[6];

    uint8_t MaxLods;
    uint8_t NumLods;

    uint8_t Padding2[0x66];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsXAnim
{
    uint64_t NamePtr;

    uint8_t Padding[10];

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

    uint8_t Padding3[0xb];

    float Framerate;

    uint8_t Padding4[0x8];

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
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsXAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsSoundAlias
{
    uint64_t NamePtr;
    uint64_t EntriesPtr;
    uint8_t EntryCount;
    uint8_t Padding[0x7];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsSoundAliasEntry
{
    uint64_t NamePtr;
    uint8_t Padding[0x20];
    uint64_t FileSpecPtr;
    uint8_t Padding2[0x98];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsStreamedSound
{
    uint16_t Localization;
    uint16_t PackageIndex;
    uint8_t Padding[4];
    uint64_t Offset;
    uint64_t Size;
    uint32_t Length;
};
#pragma pack(pop)


#pragma pack(push, 1)
struct GhostsPrimedSound
{
    uint16_t Localization;
    uint16_t PackageIndex;
    uint8_t Padding[4];
    uint64_t Offset;
    uint64_t Size;
    uint64_t LoadedSoundPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct GhostsLoadedSound
{
    uint64_t NamePtr;
    uint64_t SoundDataPtr;
    uint8_t Padding1[8];
    uint32_t FrameRate;
    uint32_t SoundDataSize;
    uint32_t FrameCount;
    uint32_t ByteRate;
    uint8_t Channels;
    uint8_t Padding2[15];
};
#pragma pack(pop)

#pragma endregion
