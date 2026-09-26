#pragma once

#include <cstdint>

#pragma region World War 2

#pragma pack(push, 1)
struct WWIIXMaterial
{
    uint64_t NamePtr;

    uint8_t Padding[0x9A];

    uint8_t ImageCount;

    uint8_t Padding2[0x15];

    uint64_t TechsetPtr;
    uint64_t ImageTablePtr;
    uint64_t UnknownPtr;
    uint64_t ConstantsPtr;

    uint8_t Padding3[144];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXMaterialImage
{
    uint32_t SemanticHash;
    uint8_t Padding[4];
    uint64_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIPAKImageEntry
{
    uint64_t ImageInfoPacked;
    uint64_t ImagePAKInfoPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIGfxMip
{
    uint16_t Width;
    uint16_t Height;

    uint8_t Padding[4];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIGfxImage
{
    uint64_t NamePtr;

    uint8_t Padding[0x18];

    uint64_t LoadedImagePtr;

    uint16_t Width;
    uint16_t Height;
    uint32_t ImageBufferSize;

    WWIIGfxMip MipLevels[3];

    uint8_t ImageFormat;

    uint8_t Padding2[0x17];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIISoundAlias
{
    uint64_t NamePtr;
    uint64_t AliasEntrysPtr;
    uint64_t Unknown1;
    uint64_t AliasEntryCount;
};

struct WWIISoundEntry
{
    uint64_t AliasNamePtr;
    uint8_t Unknown1[0x20];
    uint64_t SoundFilePtr;
    uint8_t Unknown2[0x120];
};

struct WWIISoundFileBase
{
    uint8_t SoundFileType;
    uint8_t SoundFileExists;
    uint8_t Padding[6];
};

struct WWIILoadedSoundFile
{
    uint64_t SoundFileName;

    uint8_t Unknown1[0x28];

    uint32_t BufferSize;
    uint32_t FrameCount;
    uint16_t FrameRate;
    uint8_t ChannelCount;
    uint16_t BitsPerSample;
    uint8_t BlockAlign;
    uint8_t Format;
    uint8_t Padding;

    uint64_t SoundDataPtr;
    uint32_t SoundDataSize;
};

struct WWIIPrimedSoundFile
{
    uint64_t IsPrimed;
    uint64_t SoundFilePath;
    uint64_t SoundFileName;
    uint64_t PackFileOffset;
    uint32_t PackFileSize;

    uint8_t IsLocalized;
    uint8_t Flag1;
    uint8_t PackFileIndex;
    uint8_t Flag2;

    uint32_t BufferSize;
    uint32_t FrameCount;
    uint16_t FrameRate;
    uint8_t ChannelCount;
    uint16_t BitsPerSample;
    uint8_t BlockAlign;
    uint8_t Format;
    uint8_t Padding;
};

struct WWIIStreamedSoundFile
{
    uint64_t ExtendedInfoPtr;

    uint64_t IsLoaded;
    uint64_t SoundFilePath;
    uint64_t SoundFileName;

    uint64_t PackFileOffset;
    uint32_t PackFileSize;

    uint8_t IsLocalized;
    uint8_t Flag1;
    uint8_t PackFileIndex;
    uint8_t Flag2;
};

struct WWIIStreamedSoundInfo
{
    uint64_t SoundFileName;

    uint8_t Unknown1[0x28];

    uint32_t BufferSize;
    uint32_t FrameCount;
    uint16_t FrameRate;
    uint8_t ChannelCount;
    uint16_t BitsPerSample;
    uint8_t BlockAlign;
    uint8_t Format;
    uint8_t Padding;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXStreamSurface
{
    uint16_t Unknown1;

    char SubmeshKeyHash[0x21];

    uint8_t Padding1;

    uint32_t VerticiesCount;
    uint32_t TriIndiciesCount;

    uint32_t Unknown2;

    uint64_t UnknownPtr1;
    uint64_t UnknownPtr2;
    uint64_t LoadedSurfaceInfoPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXStreamSurfaceInfo
{
    uint64_t FacesPtr;
    uint64_t VertexPositionsPtr;
    uint64_t VertexTangentsPtr;
    uint64_t VertexColorsPtr;
    uint64_t VertexUVsPtr;
    uint64_t VertexNormalsPtr;

    uint8_t Padding[0x90];

    uint64_t VertexWeightsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXModelSurface
{
    uint16_t Flags;

    uint16_t VertexCount;
    uint16_t FacesCount;

    uint8_t VertListCount;
    uint8_t PaddingCount;

    uint64_t Unknown1;

    uint64_t XStreamSurfacePtr;
    uint64_t UnknownPtr1;
    uint64_t RigidWeightsPtr;
    uint64_t UnknownPtr3;

    uint8_t Padding1[0x38];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint8_t Padding[0x40];

    uint64_t SurfsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXModel
{
    uint64_t AlternateNamePtr;

    uint16_t NumBones;
    uint16_t NumRootBones;

    uint8_t Padding1[0x4C];

    uint64_t BoneIDsPtr;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;

    WWIIXModelLod ModelLods[6];

    uint8_t NumLods;

    uint8_t Padding2[0x10F];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXModelBase
{
    uint64_t NamePtr;

    uint64_t XModelPtr;
    uint64_t MaterialHandlesPtr;
    uint64_t UnknownPtr;

    uint32_t Unknown1;
    uint32_t Unknown2;

    uint8_t Padding1[2];

    uint8_t XModelPartCount;

    uint8_t Padding2[5];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXAnim
{
    uint64_t NamePtr;

    uint8_t Padding[0x6];

    uint16_t NumFrames;
    uint16_t Flags;

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

    uint8_t Padding2[0x14];

    float Framerate;
    float Frequency;

    uint8_t Padding3[0x4];

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

    uint8_t Padding4[0x28];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct WWIIXAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma endregion
