#pragma once

#include <cstdint>

#pragma region Black Ops 3

#pragma pack(push, 1)
const struct BO3FxEffectDef
{
    uint64_t NamePtr;

    uint16_t Flags;
    uint16_t EFPriority;

    uint16_t ElemDefCountLooping;
    uint16_t ElemDefCountOneShot;
    uint16_t ElemDefCountEmission;

    uint16_t Padding;

    uint32_t TotalSize;
    uint32_t MSECLoopingLife;
    uint32_t MSECNonLoopingLife;

    uint64_t FxElementsPtr;

    float BoundingBoxDim[3];
    float BoundingCenter[3];

    float OcclusionQueryDepthBias;

    uint32_t OcclusionQueryFadeIn;
    uint32_t OcclusionQueryFadeOut;

    float OcclusionQueryScaleRange[2];

    uint8_t Unknown1[0x3C];    // Probably new BO3 values packed here...
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3GfxMip
{
    uint32_t Size;
    uint16_t Width;
    uint16_t Height;

    uint64_t HashID;

    uint8_t Padding[24];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3GfxImage
{
    BO3GfxMip MipLevels[4];

    uint8_t Padding2[31];

    uint8_t LoadedMipLevels;

    uint16_t LoadedMipWidth;
    uint16_t LoadedMipHeight;

    uint8_t Padding3[20];

    uint64_t LoadedMipPtr;
    uint64_t LoadedMipUnknown;
    uint64_t LoadedMipSize;

    uint8_t ImageFormat;

    uint8_t Padding4[7];

    uint64_t NamePtr;

    uint8_t Padding5[8];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XMaterialImage
{
    uint64_t ImagePtr;
    uint32_t SemanticHash;
    uint8_t Padding[0x14];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XMaterial
{
    uint64_t NamePtr;

    uint8_t Padding[616];

    uint8_t ImageCount;

    uint8_t Padding2[15];

    uint64_t ImageTablePtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XModelMeshInfo
{
    uint8_t StatusFlag;
    uint8_t Flag2;
    uint8_t Flag3;
    uint8_t Flag4;

    uint32_t VertexCount;
    uint32_t WeightCount;
    uint32_t FacesCount;

    uint64_t XModelMeshBufferPtr;
    uint32_t XModelMeshBufferSize;

    uint32_t VertexOffset;
    uint32_t UVOffset;
    uint32_t FacesOffset;
    uint32_t WeightsOffset;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XModelSurface
{
    uint8_t Flag1;
    uint8_t Flag2;
    uint8_t Flag3;
    uint8_t Flag4;

    uint16_t VertexCount;
    uint16_t FacesCount;

    uint32_t VerticiesIndex;
    uint32_t FacesIndex;

    uint8_t Padding[80];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XModelLod
{
    uint8_t Padding[60];

    uint8_t NumSurfs;
    uint8_t SurfacesIndex;

    uint16_t UnknownFlags;

    float LodMinDistance;
    float LodDistance;

    uint64_t LODStreamKey;

    uint8_t Padding2[24];

    uint64_t XSurfacePtr;
    uint64_t XModelMeshPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XModel
{
    uint64_t NamePtr;

    uint8_t NumBones;
    uint8_t NumRootBones;
    uint16_t NumCosmeticBones;

    uint8_t Padding[4];

    uint64_t BoneIDsPtr;
    uint64_t ParentListPtr;
    uint64_t RotationsPtr;
    uint64_t TranslationsPtr;
    uint64_t PartClassificationPtr;
    uint64_t BaseMatriciesPtr;

    uint8_t NumLods;

    uint8_t Padding2[71];

    uint64_t ModelLodPtrs[8];

    uint64_t MaterialHandlesPtr;

    uint8_t Padding3[0x18];

    uint64_t BoneInfoPtr;

    uint8_t Padding4[0x98];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XRawFile
{
    uint64_t NamePtr;

    uint64_t AssetSize;
    uint64_t RawDataPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XAnim
{
    uint64_t NamePtr;

    uint8_t Padding[0x18];

    uint16_t NumFrames;

    uint8_t Padding2[2];

    uint8_t LoopingFlag;
    uint8_t Flag2;
    uint8_t Flag3;
    uint8_t Flag4;

    uint8_t Padding3[8];

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

    uint8_t AssetType;

    uint8_t Padding4[0xB];

    float Framerate;
    float Frequency;

    uint8_t Padding5[0x10];

    uint64_t BoneIDsPtr;
    uint64_t DataBytePtr;
    uint64_t DataShortPtr;
    uint64_t DataIntPtr;
    uint64_t RandomDataShortPtr;
    uint64_t RandomDataBytePtr;
    uint64_t RandomDataIntPtr;
    uint64_t UnknownIndiciesPtr;

    uint8_t Padding6[0x18];

    uint64_t NotificationsPtr;
    uint32_t NotificationCount;

    uint8_t Padding7[0x24];

    uint64_t DeltaPartsPtr;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct BO3XAnimDeltaParts
{
    uint64_t DeltaTranslationsPtr;
    uint64_t Delta2DRotationsPtr;
    uint64_t Delta3DRotationsPtr;
};
#pragma pack(pop)

#pragma endregion
