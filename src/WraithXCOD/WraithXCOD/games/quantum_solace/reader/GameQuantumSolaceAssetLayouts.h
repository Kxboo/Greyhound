#pragma once

#include <cstdint>

#pragma region Quantum Solace
#pragma pack(push, 1)
struct QSXModelLod
{
    float LodDistance;

    uint16_t NumSurfs;
    uint16_t SurfacesIndex;

    uint32_t PartBits[6];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct QSXModel
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

    QSXModelLod ModelLods[4];

    uint8_t Padding[44];

    uint16_t NumLods;

    uint8_t Padding3[26];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct QSXModelSurface
{
    int8_t TileMode;
    int8_t Deformed;

    uint16_t VertexCount;
    uint16_t FacesCount;
    uint16_t Padding1;
    uint32_t FacesPtr;

    uint16_t WeightCounts[4];
    uint32_t WeightsPtr;

    uint32_t Padding2;


    uint32_t VerticiesPtr;


    uint8_t Padding3[12];


    uint32_t VertListCount;
    uint32_t RigidWeightsPtr;
    uint32_t UnkPtr;
    uint32_t PartBits[6];
};
#pragma pack(pop)

#pragma pack(push, 1)
struct QSXAnim
{
    uint32_t NamePtr;

    uint8_t Padding[14];

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
#pragma endregion
