#pragma once
#include "CWProbeBounds.h"

// CW build measured 2026-09-13. Native evidence and authored comparisons:
// C:\SuperTerrain\research\cw-light-settings\README.md
// BO3 RGB equivalence describes compiled parameters, not renderer equivalence.
namespace CWLightSettings
{
    using namespace CWProbeBounds;
    inline double SRGB(double Linear)
    {return Linear<=0.0031308?12.92*Linear:1.055*std::pow(Linear,1.0/2.4)-0.055;}
    inline bool Nonnegative(double N){return std::isfinite(N)&&N>=0;}
    inline json Decode(const uint8_t* P,size_t Size)
    {
        if(Size!=688)return {{"SettingsDecoded",false},{"Error","expected 688-byte light record"}};
        const V3 RGB=V(P,0xC8);
        const double Peak=std::max(RGB[0],std::max(RGB[1],RGB[2]));
        const double Range=F(P,0xE8),Cos=F(P,0xDC),StoredFov=F(P,0x278),Boost=F(P,0x1F0);
        const bool RGBValid=Nonnegative(RGB[0])&&Nonnegative(RGB[1])&&Nonnegative(RGB[2]);
        const bool CosValid=std::isfinite(Cos)&&Cos>=-1&&Cos<=1;
        const double Degrees=180/3.14159265358979323846;
        const double Fov=CosValid?2*std::acos(Cos)*Degrees:0;
        const bool FovAgrees=CosValid&&std::isfinite(StoredFov)&&StoredFov>=0&&StoredFov<=360&&
            std::abs(std::cos(StoredFov/Degrees/2)-Cos)<2e-6;
        json Source={{"CompiledLinearRGB",RGB},{"CompiledRGBBackupMatches",std::memcmp(P+0xC8,P+0x284,12)==0},
            {"TypeRaw",U32(P,0x40)},{"BoxBoundsEnabledRaw",P[0x44]},{"SpotEnabledRaw",P[0x45]},
            {"OuterHalfAngleCosine",Cos},{"EffectiveOuterFovDegrees",CosValid?json(Fov):json(nullptr)},
            {"StoredOuterFovDegrees",StoredFov},{"StoredFovMatchesRuntimeCosine",FovAgrees},
            {"SpotFeather",F(P,0xE0)},{"EffectiveRangeInches",Range},
            {"ScriptRadiusLimitInches",F(P,0x208)},
            {"BoundsMin",V(P,0x218)},{"BoundsMax",V(P,0x224)},
            {"ShadowProjectionNearDistanceInches",F(P,0x13C)},
            {"VolumetricEnabledRaw",P[0x1E4]},{"VolumetricModeRaw",P[0x1E5]},
            {"VolumetricSampleCount",U32(P,0x1E8)&0x7F},{"VolumetricAlternateSampleCount",U32(P,0x1EC)&0x7F},
            {"VolumetricIntensityBoostLinear",Boost},
            {"LODFadeStartInches",F(P,0x204)},{"LODFadeRangeInches",F(P,0x200)},
            {"RendererColorScale",F(P,0x260)},
            {"UnmappedRaw",{{"0xD4_float",F(P,0xD4)},{"0xD8_u32",U32(P,0xD8)},
                {"0xE4_float",F(P,0xE4)},{"0xEC_float",F(P,0xEC)},
                {"0xF8_float",F(P,0xF8)},{"0xFC_float",F(P,0xFC)},
                {"0x130_u32",U32(P,0x130)},{"0x134_byte",P[0x134]},{"0x135_byte",P[0x135]},
                {"0x136_byte",P[0x136]},{"0x138_float",F(P,0x138)},
                {"0x150_float",F(P,0x150)},{"0x154_float",F(P,0x154)},{"0x158_float",F(P,0x158)},
                {"0x15C_u32",U32(P,0x15C)},{"0x160_byte",P[0x160]},
                {"0x1E6_byte",P[0x1E6]},{"0x1F4_float",F(P,0x1F4)},{"0x1F8_float",F(P,0x1F8)},
                {"0x1FC_u32",U32(P,0x1FC)},{"0x270_float",F(P,0x270)}}}};
        json BO3=json::object(),Pending=json::array();
        // Exact authored fx_light_update_id matches at +0x268, including three
        // distinct names and absent/zero cases. It is a link, not a spawn flag.
        uint64_t UpdateId=0;std::memcpy(&UpdateId,P+0x268,8);
        std::ostringstream UpdateHash;UpdateHash<<"0x"<<std::hex<<UpdateId;
        Source["FXLightUpdateIdHash"]=UpdateHash.str();
        Source["PlacementSource"]="compiled_world_primary_light";
        Source["UpdateLinkMeaning"]="authored fx_light_update_id; does not establish spawn method or current activity";
        if(RGBValid)
        {
            V3 Normalized={1,1,1},Color={0,0,0};
            // BO3 clamps stops to -32. Retain sub-threshold energy in color.
            const double Stops=Peak>0?std::max(-32.0,std::log2(Peak)):0;
            for(int K=0;K<3;++K){if(Peak>0)Normalized[K]=RGB[K]/Peak;Color[K]=SRGB(RGB[K]/std::pow(2.0,Stops));}
            Source["RuntimeIntensityMaxChannel"]=Peak;Source["RuntimeNormalizedColor"]=Normalized;
            BO3["stops"]=Stops;BO3["_color"]=Color;
        }
        else Pending.push_back("Invalid/non-finite compiled RGB; color and stops omitted");
        // Type 2 has both spot and omni authored matches. Never map the raw enum
        // to BO3's enum (where 2 means spot and 4 means omni).
        const bool Ordinary=U32(P,0x40)==2&&P[0x44]==0&&P[0x45]<=1&&FovAgrees&&
            ((P[0x45]==0&&Cos==-1)||(P[0x45]==1&&Fov>0&&Fov<=180));
        if(Ordinary)
        {
            BO3["PRIMARY_TYPE"]=P[0x45]?"PRIMARY_SPOT":"PRIMARY_OMNI";
            if(P[0x45])BO3["fov_outer"]=StoredFov;
            if(Nonnegative(Range))BO3["radius"]=Range;
            else Pending.push_back("Invalid effective range; radius omitted");
        }
        else Pending.push_back("Box/other source shape or cone inconsistency; PRIMARY_TYPE, fov_outer and radius omitted");
        if(P[0x1E4]<=1)BO3["volumetric"]=P[0x1E4];
        else Pending.push_back("Unrecognized volumetric enable byte");
        const auto Samples=U32(P,0x1E8)&0x7F,Alternate=U32(P,0x1EC)&0x7F;
        if(Samples==Alternate&&Samples>=1&&Samples<=24)BO3["volumetricSampleCount"]=Samples;
        else Pending.push_back("Volumetric sample variants differ or exceed BO3 range 1..24");
        if(std::isfinite(Boost)&&Boost>0){Source["VolumetricIntensityBoostStops"]=std::log2(Boost);BO3["volumetricIntensityBoost"]=std::log2(Boost);}
        else Pending.push_back("Volumetric boost cannot be represented as finite stops");
        std::string Texture;bool Terminated=false,ASCII=true;
        for(size_t O=0x184;O<0x1C4;++O){if(!P[O]){Terminated=true;break;}if(P[O]<32||P[O]>126)ASCII=false;Texture+=char(P[O]);}
        if(Terminated&&ASCII)
        {
            Source["CookieTexture"]=Texture;
            Source["CookieTransform"]={{"RotationRadiansAtTimeZero",F(P,0x1C4)},
                {"RotationRatePerRuntimeTimeUnit",F(P,0x1C8)},
                {"TileScale",{F(P,0x1CC),F(P,0x1D0)}},
                {"ScrollRatePerRuntimeTimeUnit",{F(P,0x1D4),F(P,0x1D8)}},
                {"Offset",{F(P,0x1DC),F(P,0x1E0)}}};
            if(!Texture.empty())Pending.push_back("Cookie texture requires a BO3 LightDef asset and verified transform/time mapping");
        }
        else Pending.push_back("Cookie string is not terminated printable ASCII");
        if(P[0x1E5])Pending.push_back("Non-default CW volumetric mode has no verified BO3 equivalent");
        Pending.push_back("Attenuation, feather profile, emitter dimensions, shadow policy/softness, lighting-state bits and LOD conversion remain unverified");
        BO3["status"]="decoded parameter subset; compiled RGB equivalence, not full visual equivalence; see UnmappedSettings";
        json Result={{"SettingsSchema","cw-light-settings-v1"},{"SettingsDecoded",true},
            {"BO3CoreSettingsValidated",Ordinary&&RGBValid&&Nonnegative(Range)},{"FullBO3Accuracy",false},
            {"SourceSettings",Source},{"BO3",BO3},{"UnmappedSettings",Pending}};
        if(!Ordinary&&RGBValid)
        {
            auto Fallback=BO3;
            // Explicit preview approximation requested by the user. Never mix
            // these into the confirmed core-settings prefab automatically.
            const bool Spot=P[0x45]==1;
            Fallback["PRIMARY_TYPE"]=Spot?"PRIMARY_SPOT":"PRIMARY_OMNI";
            Fallback["radius"]=Nonnegative(Range)&&Range>0?Range:256.0;
            if(Spot)Fallback["fov_outer"]=CosValid&&Fov>0&&Fov<=180?Fov:90.0;
            Fallback["status"]="PREVIEW FALLBACK: basic omni/spot substituted for unresolved source shape; range may only enclose original coverage";
            Result["BO3Fallback"]=Fallback;
        }
        return Result;
    }
}
