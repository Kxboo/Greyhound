#pragma once
#include "CWMapWorldCapture.h"

// Shader-reflected layouts verified on platinum and silver. No deformed meshes.
namespace CWSplineCapture
{
    inline void Capture(TerrainResearch::Capture& C, uint32_t Pool, const std::vector<uint8_t>& Header)
    {
        using namespace CWMapWorldCapture;
        if (Pool != 0x1B || Header.size() < 0x460) return;
        json Doc = {{"schema", "cw-model-splines-v1"}, {"source_pool", Pool},
            {"status", "incomplete"}, {"deformed_meshes_exported", false},
            {"segment_end_exclusive", true}, {"reference_index_field", "district reference +0x28"},
            {"validation", "Source layouts verified on two maps; mesh deformation remains experimental."}};
        std::vector<uint8_t> Data[2]; uint32_t Counts[2] = {};
        bool OK = true;
        const char* Names[] = {"instances", "segments"};
        const uint32_t Strides[] = {100,192}; const size_t Offsets[] = {0x448,0x458};
        for (int I=0; I<2; ++I)
        {
            const std::string Prefix = std::string("splines/") + Names[I];
            auto H = C.Span(RU64(Header.data()+Offsets[I]),56,Prefix+"_header.bin","Spline resource header",false,"structure");
            if (H.size()!=56) { OK=false; continue; }
            const auto Stride=RU32(H.data()+8), Count=RU32(H.data()+12);
            Doc[Names[I]]={{"stride",Stride},{"count",Count},{"file",Prefix+".bin"}};
            if (Stride!=Strides[I] || Count==0 || uint64_t(Count)*Stride>32ull*1024*1024)
            { Doc[Names[I]]["status"]="unsupported_layout"; OK=false; continue; }
            Counts[I]=Count;
            Data[I]=C.Span(RU64(H.data()),uint64_t(Count)*Stride,Prefix+".bin","Shader spline source records",false,"structure");
            const bool Stable=Data[I].size()==uint64_t(Count)*Stride && C.VerifySpan(RU64(H.data()),Data[I],Prefix+".bin");
            const bool HeaderStable=C.VerifySpan(RU64(Header.data()+Offsets[I]),H,Prefix+"_header.bin");
            Doc[Names[I]]["readback_unchanged"]=Stable && HeaderStable;
            OK=OK && Stable && HeaderStable;
        }
        if (OK)
        {
            for (int I=0;I<2;++I) for (size_t O=0;O<Data[I].size();O+=Strides[I])
                for (size_t F=0;F<Strides[I];F+=4)
                {
                    if (I==0 && F>=36 && F<=44) continue;
                    float V; memcpy(&V,Data[I].data()+O+F,4);
                    if (!std::isfinite(V)) OK=false;
                }
        }
        if (OK)
        {
            auto Floats=[](const uint8_t* P,size_t N) { json A=json::array(); for(size_t J=0;J<N;++J) { float V; memcpy(&V,P+J*4,4); A.push_back(V); } return A; };
            json Instances=json::array(), Segments=json::array(); uint32_t Invalid=0;
            for(uint32_t I=1;I<Counts[0];++I)
            {
                const auto* P=Data[0].data()+size_t(I)*100;
                const auto Begin=RU32(P+36),End=RU32(P+40);
                if(Begin>=End || End>Counts[1] || RU32(P+44)>5) ++Invalid;
                Instances.push_back({{"SplineInstanceIndex",I},{"modelXExtent",Floats(P,1)[0]},
                    {"instanceLength",Floats(P+4,1)[0]},{"modelSplineOrigin",Floats(P+8,3)},
                    {"distFromStartNode",Floats(P+20,1)[0]},{"modelScale",Floats(P+24,1)[0]},
                    {"upDownOffset",Floats(P+28,1)[0]},{"leftRightOffset",Floats(P+32,1)[0]},
                    {"segmentBegin",Begin},{"segmentEnd",End},{"spliningAxisType",RU32(P+44)},
                    {"prefabScale",Floats(P+48,1)[0]},{"prefabOrigin",Floats(P+52,3)},
                    {"prefabAxisRowMajor",Floats(P+64,9)}});
            }
            for(uint32_t I=0;I<Counts[1];++I)
            {
                const auto* P=Data[1].data()+size_t(I)*192;
                Segments.push_back({{"SegmentIndex",I},{"distFromStartNode",Floats(P,1)[0]},
                    {"length",Floats(P+4,1)[0]},{"bezierEval",Floats(P+8,12)},
                    {"entBezierDerEval",Floats(P+56,9)},{"entToAlignedRowMajor",Floats(P+92,9)},
                    {"modelToWldRowMajor",Floats(P+128,9)},{"modelToWld_origin",Floats(P+164,3)},
                    {"bankAngleBezierEval",Floats(P+176,4)}});
            }
            Doc["Instances"]=Instances; Doc["Segments"]=Segments;
            Doc["invalid_instance_ranges_or_axes"]=Invalid;
            OK=Invalid==0;
        }
        Doc["status"]=OK?"captured_source_data":"incomplete_or_unsupported";
        auto Text=Doc.dump(2);
        const bool Saved=C.Write("splined_models.json",reinterpret_cast<const uint8_t*>(Text.data()),Text.size());
        C.Report["model_splines"]={{"file","splined_models.json"},{"complete",OK && Saved}};
    }
}
