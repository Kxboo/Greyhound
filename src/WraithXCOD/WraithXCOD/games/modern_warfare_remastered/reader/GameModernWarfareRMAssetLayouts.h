#pragma once

#include <cstdint>

#pragma region Modern Warfare RM

#pragma pack(push, 1)
struct MWRXMaterial
{
    uint64_t NamePtr;

    uint8_t Padding[0x118];

    uint8_t ImageCount;

    uint8_t Padding2[15];

    uint64_t ImageTablePtr;

    uint8_t Padding3[0x118];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRXMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[4];
    uint64_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRPAKImageEntry
{
    uint64_t ImageOffset;
    uint64_t ImageEndOffset;
    uint64_t ImagePAKInfoPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRGfxMip
{
    uint16_t Width;
    uint16_t Height;

    uint8_t Padding[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRGfxImage
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

    MWRGfxMip MipLevels[3];

    uint64_t NamePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRXModelSurface
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

    uint8_t Padding[32];

    uint64_t RigidWeightsPtr;
    uint64_t UnknownPtr;
    uint64_t WeightsPtr;

    uint8_t Padding2[0xA8];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRXModelLod
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
struct MWRXModel
{
    uint64_t NamePtr;
    uint8_t NumBones;
    uint8_t NumRootBones;
    uint8_t NumSurfaces;
    uint8_t LodRampType;

    uint8_t Padding[0x2C];

    uint64_t BoneIDsPtr;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;
    uint64_t UnknownPtr;
    uint64_t UnknownPtr2;
    uint64_t MaterialHandlesPtr;

    MWRXModelLod ModelLods[6];

    uint8_t NumLods;
    uint8_t MaxLods;

    uint8_t Padding2[0xA6];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRXAnim
{
    uint64_t NamePtr;

    uint8_t Padding[6];

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

    uint8_t Padding2[2];

    uint8_t NotificationCount;

    uint8_t AssetType;

    uint8_t Padding3[0x11];

    float Framerate;

    uint8_t Padding4[0x4];

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

    uint8_t Padding5[0x50];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRXAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRSoundAlias
{
    uint64_t NamePtr;
    uint64_t EntriesPtr;
    uint64_t Unknown1;
    uint8_t EntryCount;
    uint8_t Padding[0x7];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRSoundAliasEntry
{
    uint64_t NamePtr;
    uint8_t Padding[0x18];
    uint64_t FileSpecPtr;
    uint8_t Padding2[0xD0];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRSoundAliasFileSpec
{
    uint8_t Type;
    uint8_t Padding[0x7];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct MWRStreamedSound
{
    uint8_t Padding[2];
    uint16_t PackageIndex;
    uint32_t Exists;
    uint64_t Offset;
    uint64_t Size;
    uint32_t Length;
    uint32_t Padding3;
    uint64_t Padding4;
};
#pragma pack(pop)

#pragma endregion
