#pragma once

#include <cstdint>

struct VGXAssetPoolData
{
    // The beginning of the pool
    uint64_t PoolPtr;

    // A pointer to the closest free header
    uint64_t PoolFreeHeadPtr;

    // The maximum pool size
    uint32_t PoolSize;

    // The size of the asset header
    uint32_t AssetSize;
};

struct VGSoundBankInfo
{
    uint64_t BankNamePointer;
    uint64_t StreamKey;
    uint8_t Padding[8];
    uint64_t BankFilePointer;
    uint64_t UnkPointer;
    uint32_t BankFileSize;
    uint32_t Unk;
};

struct VGSoundAlias
{
    uint64_t NamePtr;
    uint32_t NameHash;
    uint32_t Padding;
    uint64_t EntriesPtr;
    uint64_t EntriesCount;
};

struct VGSoundAliasEntry
{
    uint64_t FilePtr;
    uint32_t FileHash;
    uint32_t Unk;
    uint64_t NamingInfoPtr;
    uint64_t UnkPtr2;
};

// In the Season 5 patch the Name/Secondary pointers are no longer stored directly in the sound alias entry and are instead their own structure pointed to from the entry.
struct VGSoundAliasNamingInfo
{
    uint64_t NamePtr;
    uint64_t SecondaryPtr;
};

#pragma pack(push, 1)
struct VGXModelLod
{
    uint64_t MeshPtr;
    uint64_t SurfsPtr;

    float LodDistance;
    float LodDistanceAgain;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint8_t Padding[36];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXModel
{
    uint64_t NamePtr;
    uint16_t NumSurfaces;
    uint8_t NumLods;
    uint8_t MaxLods;

    uint8_t Padding[12];

    uint8_t NumBones;
    uint8_t NumRootBones;
    uint16_t UnkBoneCount;

    uint8_t Padding3[100];

    uint64_t BoneIDsPtr;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;
    uint64_t UnknownPtr;
    uint64_t UnknownPtr2;
    uint64_t MaterialHandlesPtr;

    uint64_t ModelLodsPtr;

    uint8_t Padding4[184];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXModelSurface
{
    uint16_t StatusFlag;
    uint16_t VertexCount;
    uint16_t FacesCount;
    uint16_t Padding6;
    uint8_t VertListCount;
    uint8_t Padding0[19];
    uint16_t WeightCounts[8];
    uint8_t Padding1[4];
    float NewScale;
    uint32_t Offsets[9];
    uint64_t MeshBufferPointer;
    uint64_t Padding3;
    uint64_t RigidWeightsPtr;
    uint64_t WeightsPtr;
    uint8_t Padding4[40];
    float XOffset;
    float YOffset;
    float ZOffset;
    float Scale;
    float Min;
    float Max;
    uint8_t Padding7[24];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXModelMesh
{
    uint64_t NamePtr;
    uint64_t SurfsPtr;
    uint64_t LODStreamKey;
    uint8_t Padding[8];
    uint64_t MeshBufferPointer;
    uint8_t Padding2[40];

};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXModelMeshBufferInfo // Same as the MW4
{
    uint64_t BufferPtr; // 0 if the model is not loaded, otherwise a pointer, even if streamed
    uint32_t BufferSize;
    uint32_t Streamed;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXAnim // Same as the MW4
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
    uint8_t PaddingNew[0x8];
    uint64_t DeltaPartsPtr;
    uint8_t Padding[0xC];

    float Framerate;

    uint8_t Padding2[14];

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

    uint8_t Padding3[27];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXAnimDeltaParts // Same as the MW4
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXMaterial
{
    uint64_t NamePtr;
    uint8_t Padding[20];
    uint8_t ImageCount;
    uint8_t Padding2[19];
    uint64_t TechsetPtr;
    uint64_t ImageTablePtr;
    uint8_t Padding3[64];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGXMaterialImage // Same as the MW4
{
    uint32_t Type;
    uint8_t Padding[4];
    uint64_t ImagePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct VGSoundBank
{
    uint64_t NamePtr;
    uint64_t BankNamePtr;
    uint64_t LanguagePtr;
    uint64_t TypePtr;
    uint64_t AliasCount;
    uint64_t AliasesPtr;
    uint8_t Padding[432];
    uint64_t SoundBankPtr;
    uint64_t StreamedSoundsPtr;
    uint32_t StreamedSoundCount;
    uint32_t Unk2;
};
#pragma pack(pop)