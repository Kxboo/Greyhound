#include "../src/WraithXCOD/WraithXCOD/CWMapCandidateLayout.h"
#include <cassert>
#include <limits>
template<class T> void put(std::vector<uint8_t>& B,size_t O,T V){memcpy(B.data()+O,&V,sizeof(V));}
int main()
{
    using CWMapCandidateLayout::Check;
    std::vector<uint8_t>M(8),H(32),S(20);
    put<uint16_t>(M,4,1); put<uint16_t>(H,28,1);
    put<float>(H,12,2);put<float>(H,16,3);put<float>(H,20,4);
    put<float>(S,0,1);put<float>(S,16,2);
    auto R=Check(M,H,S);assert(R.Valid()&&R.ReferencedHulls==1&&R.ReferencedSlabs==1);
    put<uint16_t>(M,6,65535);assert(Check(M,H,S).BadModelRanges==1);put<uint16_t>(M,6,0);
    put<uint16_t>(H,30,65535);assert(Check(M,H,S).BadHullRanges==1);put<uint16_t>(H,30,0);
    put<float>(H,12,-1);assert(Check(M,H,S).BadBounds==1);put<float>(H,12,1);
    put<float>(S,16,-1);assert(Check(M,H,S).BadSlabs==1);put<float>(S,16,1);
    put<float>(S,0,2);assert(Check(M,H,S).BadSlabs==1);
    put<float>(S,0,std::numeric_limits<float>::quiet_NaN());assert(Check(M,H,S).BadSlabs==1);
    S.pop_back();assert(!Check(M,H,S).RecordSizesValid);
    assert(Check({}, {}, {}).Valid());
}
