#pragma once
#include <cstdint>
#include <cstring>
#include <cmath>
#include <vector>

// Layout hypotheses are separate from live reads so corrupt/truncated input is testable.
namespace CWMapCandidateLayout
{
    inline uint16_t U16(const uint8_t* P) { uint16_t V; memcpy(&V,P,2); return V; }
    inline uint32_t U32(const uint8_t* P) { uint32_t V; memcpy(&V,P,4); return V; }
    inline float F32(const uint8_t* P) { float V; memcpy(&V,P,4); return V; }
    struct GeometryCheck
    {
        bool RecordSizesValid = false;
        uint32_t BadModelRanges = 0, BadHullRanges = 0, BadBounds = 0, BadSlabs = 0;
        uint32_t ReferencedHulls = 0, ReferencedSlabs = 0;
        bool Valid() const { return RecordSizesValid && !BadModelRanges && !BadHullRanges && !BadBounds && !BadSlabs; }
    };
    inline GeometryCheck Check(const std::vector<uint8_t>& Models,
        const std::vector<uint8_t>& Hulls, const std::vector<uint8_t>& Slabs)
    {
        GeometryCheck R;
        if (Models.size()%8 || Hulls.size()%32 || Slabs.size()%20) return R;
        R.RecordSizesValid = true;
        std::vector<bool> H(Hulls.size()/32), S(Slabs.size()/20);
        for(size_t I=0; I<Models.size(); I+=8)
        {
            const uint32_t N=U16(Models.data()+I+4), First=U16(Models.data()+I+6);
            if (uint64_t(First)+N > H.size()) ++R.BadModelRanges;
            else for(uint32_t J=0; J<N; ++J) H[First+J]=true;
        }
        for(size_t I=0; I<Hulls.size(); I+=32)
        {
            const auto P=Hulls.data()+I;
            const uint32_t N=U16(P+28), First=U16(P+30);
            if(uint64_t(First)+N>S.size()) ++R.BadHullRanges;
            else for(uint32_t J=0; J<N; ++J) S[First+J]=true;
            bool Bad=false;
            for(size_t J=0; J<6; ++J) if(!std::isfinite(F32(P+J*4)) || (J>=3 && F32(P+J*4)<0)) Bad=true;
            if(Bad) ++R.BadBounds;
        }
        for(size_t I=0; I<Slabs.size(); I+=20)
        {
            const auto P=Slabs.data()+I; bool Bad=false;
            double Norm=0;
            for(size_t J=0; J<5; ++J) {const auto V=F32(P+J*4); if(!std::isfinite(V)) Bad=true; if(J<3) Norm+=double(V)*V;}
            if(F32(P+16)<0 || std::abs(Norm-1.0)>0.001) Bad=true;
            if(Bad) ++R.BadSlabs;
        }
        for(const bool V:H) if(V) ++R.ReferencedHulls;
        for(const bool V:S) if(V) ++R.ReferencedSlabs;
        return R;
    }
}
