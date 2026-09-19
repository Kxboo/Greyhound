#pragma once
#include "CWNonStaticPlacements.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <vector>

// Bounded, process-independent decoding. Offsets are substantiated by the CW
// consumers at RVA 8B6B174 and BE9696C, plus authored probe property matches.
namespace CWProbeBounds
{
    using json = nlohmann::json;
    using V3 = std::array<double,3>;
    constexpr size_t Stride=604;
    inline float F(const uint8_t* P,size_t O) {float V;std::memcpy(&V,P+O,4);return V;}
    inline uint32_t U32(const uint8_t* P,size_t O) {uint32_t V;std::memcpy(&V,P+O,4);return V;}
    inline uint16_t U16(const uint8_t* P,size_t O) {uint16_t V;std::memcpy(&V,P+O,2);return V;}
    inline V3 V(const uint8_t* P,size_t O) {return {F(P,O),F(P,O+4),F(P,O+8)};}
    inline double Dot(const V3& A,const V3& B) {return A[0]*B[0]+A[1]*B[1]+A[2]*B[2];}
    inline bool Finite(const V3& A) {for(double X:A)if(!std::isfinite(X)||std::abs(X)>1e7)return false;return true;}
    inline V3 World(const V3& P,const std::array<V3,3>& A,const V3& X)
    {V3 R=P;for(int J=0;J<3;++J)for(int K=0;K<3;++K)R[J]+=X[K]*A[K][J];return R;}
    inline json Box(const V3& P,const std::array<V3,3>& A,const V3& Minus,const V3& Plus)
    {
        json Corners=json::array(); V3 Lo={1e30,1e30,1e30},Hi={-1e30,-1e30,-1e30};
        for(int Mask=0;Mask<8;++Mask)
        {
            V3 X;for(int K=0;K<3;++K)X[K]=(Mask&(1<<K))?Plus[K]:-Minus[K];
            auto W=World(P,A,X);Corners.push_back(W);
            for(int K=0;K<3;++K){Lo[K]=std::min(Lo[K],W[K]);Hi[K]=std::max(Hi[K],W[K]);}
        }
        return {{"WorldCorners",Corners},{"WorldAABBMin",Lo},{"WorldAABBMax",Hi}};
    }
    inline json Decode(const uint8_t* P,size_t Size)
    {
        if(Size!=Stride)return {{"StructuralValidation",false},{"Error","expected exactly 604 bytes"}};
        const V3 Origin=V(P,0),Minus=V(P,0x30),Plus=V(P,0x3C),BlendMin=V(P,0x48),BlendMax=V(P,0x54),StoredCenter=V(P,0x244);
        const std::array<V3,3> Axes={V(P,0xC),V(P,0x18),V(P,0x24)};
        const auto PlaneCount=U32(P,0x60);const auto Role=P[0x258];
        bool Valid=Finite(Origin)&&Finite(Minus)&&Finite(Plus)&&Finite(BlendMin)&&Finite(BlendMax)&&Finite(StoredCenter)&&PlaneCount<=30&&Role<=1;
        // Inner extents may be signed: BO3 permits the capture point outside its box.
        for(int K=0;K<3;++K)if(Minus[K]+Plus[K]<0||BlendMin[K]<0||BlendMax[K]<0)Valid=false;
        for(int J=0;J<3;++J)for(int K=0;K<3;++K)
            if(!Finite(Axes[J])||std::abs(Dot(Axes[J],Axes[K])-(J==K?1.0:0.0))>0.002)Valid=false;
        const V3 Cross={Axes[0][1]*Axes[1][2]-Axes[0][2]*Axes[1][1],Axes[0][2]*Axes[1][0]-Axes[0][0]*Axes[1][2],Axes[0][0]*Axes[1][1]-Axes[0][1]*Axes[1][0]};
        if(std::abs(Dot(Cross,Axes[2])-1)>0.002)Valid=false;
        V3 OuterMin,OuterMax,CenterLocal;
        for(int K=0;K<3;++K){OuterMin[K]=Minus[K]+BlendMin[K];OuterMax[K]=Plus[K]+BlendMax[K];CenterLocal[K]=(OuterMax[K]-OuterMin[K])/2;}
        const auto Center=World(Origin,Axes,CenterLocal);double CenterError=0;
        for(int K=0;K<3;++K)CenterError=std::max(CenterError,std::abs(Center[K]-StoredCenter[K]));
        if(CenterError>0.05)Valid=false;
        json Planes=json::array();
        for(uint32_t I=0;I<std::min(PlaneCount,30u);++I)
        {
            const V3 N=V(P,0x64+I*16);const double D=F(P,0x70+I*16);
            if(!Finite(N)||!std::isfinite(D)||Dot(N,N)<1e-12)Valid=false;
            const auto W=World({0,0,0},Axes,N);
            Planes.push_back({{"LocalNormal",N},{"LocalD",D},{"WorldNormal",W},{"WorldD",D-Dot(W,Origin)}});
        }
        // Invert Rz(yaw)*Ry(pitch)*Rx(roll). Axis rows are world-space local
        // basis vectors, i.e. columns of the conventional rotation matrix.
        const double XY=std::hypot(Axes[0][0],Axes[0][1]);
        const V3 Angles={std::atan2(-Axes[0][2],XY)*180/3.14159265358979323846,
            (XY>1e-6?std::atan2(Axes[0][1],Axes[0][0]):std::atan2(-Axes[1][0],Axes[1][1]))*180/3.14159265358979323846,
            (XY>1e-6?std::atan2(Axes[1][2],Axes[2][2]):0)*180/3.14159265358979323846};
        json Result={{"StructuralValidation",Valid},{"VolumeOrigin",Origin},{"Axes",Axes},{"AnglesPitchYawRoll",Valid?json(Angles):json(nullptr)},
            {"InnerExtentMin",Minus},{"InnerExtentMax",Plus},{"BlendMin",BlendMin},{"BlendMax",BlendMax},
            {"OuterExtentMin",OuterMin},{"OuterExtentMax",OuterMax},{"StoredOuterCenter",StoredCenter},{"OuterCenterError",CenterError},
            {"PlaneCount",PlaneCount},{"InfluencePlanes",Planes},{"PlaneEquation","dot(normal, point) + D <= 0; local point = transpose(basis) * (world - volume origin)"},
            {"Shape",PlaneCount?"convex_planes":"box"},{"SubtractRaw",Role},{"Unknown250",U32(P,0x250)},{"Unknown254",U32(P,0x254)},
            {"BO3",{{"classname","reflection_probe"},{"origin",Valid?json(Origin):json(nullptr)},{"angles",Valid?json(Angles):json(nullptr)},
                {"box",PlaneCount?0:1},{"size_min",Valid?json(Minus):json(nullptr)},{"size_max",Valid?json(Plus):json(nullptr)},
                {"blend_mins",Valid?json(BlendMin):json(nullptr)},{"blend_maxs",Valid?json(BlendMax):json(nullptr)},
                {"subtract",Role<=1?json(Role):json(nullptr)},
                {"status",PlaneCount?"multiface geometry reference; BO3 facePlane/faceBlend authoring conversion still requires verification":"box bounds keys; associate with source parent probe before authoring; rebake cubemap and GI"},
                {"capture_origin","use parent probe Position, not this volume origin; child volumes share the parent cubemap"}}}};
        if(Valid){Result["InnerBox"]=Box(Origin,Axes,Minus,Plus);Result["OuterBox"]=Box(Origin,Axes,OuterMin,OuterMax);}
        else {Result["InnerBox"]=nullptr;Result["OuterBox"]=nullptr;}
        return Result;
    }
    // The explicit uint16 start/count ranges must own every descriptor volume
    // exactly once. Failure retains raw records but prevents a guessed join.
    inline bool Owners(const std::vector<uint8_t>& Probes,uint32_t Count,std::vector<int>& Out)
    {
        if(Probes.size()%376||Count>200000)return false;
        Out.assign(Count,-1);
        for(size_t I=0;I<Probes.size()/376;++I)
        {
            const auto P=Probes.data()+I*376;const uint32_t First=U16(P,0x58),N=U16(P,0x5A);
            if(First>Count||N>Count-First)return false;
            for(uint32_t J=First;J<First+N;++J){if(Out[J]!=-1)return false;Out[J]=int(I);}
        }
        return std::find(Out.begin(),Out.end(),-1)==Out.end();
    }
}
