#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>
#include <vector>
#include "json.hpp"

// Position math shared with the independently shader-validated offline baker.
// All arithmetic here is in game inches; normal model exporters own format scaling.
namespace CWSplineBake
{
    using json = nlohmann::json;
    using V = std::array<double,3>;
    inline V Add(V a,V b) { return {a[0]+b[0],a[1]+b[1],a[2]+b[2]}; }
    inline V Sub(V a,V b) { return {a[0]-b[0],a[1]-b[1],a[2]-b[2]}; }
    inline V Mul(V a,double s) { return {a[0]*s,a[1]*s,a[2]*s}; }
    inline double Dot(V a,V b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
    inline V Cross(V a,V b) { return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}; }
    inline bool Finite(V a) { return std::isfinite(a[0]) && std::isfinite(a[1]) && std::isfinite(a[2]); }
    inline V Unit(V a) {
        const auto n=std::sqrt(Dot(a,a));
        if (!Finite(a) || n<=1e-12) throw std::runtime_error("Invalid spline direction");
        return Mul(a,1/n);
    }
    inline V Vector(const double* f) { return {f[0],f[1],f[2]}; }
    inline V Row(V p,const double* m) {
        return {p[0]*m[0]+p[1]*m[3]+p[2]*m[6],p[0]*m[1]+p[1]*m[4]+p[2]*m[7],p[0]*m[2]+p[1]*m[5]+p[2]*m[8]};
    }
    struct Instance { std::array<double,25> f{}; uint32_t begin=0,end=0,axis=0; };
    struct Controls
    {
        std::map<uint32_t,Instance> instances;
        std::vector<std::array<double,48>> segments;
        static void Read(const json& j,const char* key,double* out,size_t count) {
            const auto& a=j.at(key);
            if (count>1 && (!a.is_array() || a.size()!=count)) throw std::runtime_error("Invalid spline field length");
            for(size_t i=0;i<count;++i) {
                out[i]=(count==1?a:a.at(i)).get<double>();
                if(!std::isfinite(out[i])) throw std::runtime_error("Nonfinite spline field");
            }
        }
        explicit Controls(const json& doc) {
            if(doc.at("status")!="captured_source_data" || !doc.at("instances").at("readback_unchanged").get<bool>() ||
                !doc.at("segments").at("readback_unchanged").get<bool>() || doc.at("instances").at("stride")!=100 ||
                doc.at("segments").at("stride")!=192) throw std::runtime_error("Spline capture is incomplete or unsupported");
            for(const auto& j:doc.at("Segments")) {
                if(j.at("SegmentIndex").get<size_t>()!=segments.size()) throw std::runtime_error("Out-of-order spline segments");
                std::array<double,48> g{};
                Read(j,"distFromStartNode",g.data(),1);Read(j,"length",g.data()+1,1);
                Read(j,"bezierEval",g.data()+2,12);Read(j,"entBezierDerEval",g.data()+14,9);
                Read(j,"entToAlignedRowMajor",g.data()+23,9);Read(j,"modelToWldRowMajor",g.data()+32,9);
                Read(j,"modelToWld_origin",g.data()+41,3);Read(j,"bankAngleBezierEval",g.data()+44,4);
                segments.push_back(g);
            }
            if(segments.empty() || segments.size()!=doc.at("segments").at("count").get<size_t>())
                throw std::runtime_error("Spline segment count mismatch");
            for(const auto& j:doc.at("Instances")) {
                Instance v;auto* f=v.f.data();
                Read(j,"modelXExtent",f,1);Read(j,"instanceLength",f+1,1);Read(j,"modelSplineOrigin",f+2,3);
                Read(j,"distFromStartNode",f+5,1);Read(j,"modelScale",f+6,1);
                Read(j,"upDownOffset",f+7,1);Read(j,"leftRightOffset",f+8,1);
                Read(j,"prefabScale",f+12,1);Read(j,"prefabOrigin",f+13,3);Read(j,"prefabAxisRowMajor",f+16,9);
                v.begin=j.at("segmentBegin");v.end=j.at("segmentEnd");v.axis=j.at("spliningAxisType");
                if(v.begin>=v.end || v.end>segments.size() || v.axis>5 || f[0]<=0 || f[1]<=0 || f[6]<=0 || f[12]<=0)
                    throw std::runtime_error("Invalid spline instance");
                for(auto s=v.begin;s<v.end;++s) {
                    if(segments[s][1]<=0) throw std::runtime_error("Invalid referenced spline segment length");
                    if(s>v.begin && segments[s][0]<=segments[s-1][0]) throw std::runtime_error("Unordered spline range");
                }
                const auto index=j.at("SplineInstanceIndex").get<uint32_t>();
                if(index>=doc.at("instances").at("count").get<uint32_t>() || !instances.emplace(index,v).second)
                    throw std::runtime_error("Invalid/duplicate spline index");
            }
            if(instances.empty()) throw std::runtime_error("No spline instances");
        }
        V Deform(V p,uint32_t index) const {
            const auto& v=instances.at(index);const auto* f=v.f.data();
            p=Add(Row(Mul(p,f[12]),f+16),Vector(f+13));
            uint64_t bits=0xBE6777A5C0000000ull;double eps;std::memcpy(&eps,&bits,8);
            bits=0x3E7777A5C0000000ull;double sinPi;std::memcpy(&sinPi,&bits,8);
            const double axes[6][9]={{1,0,0,0,1,0,0,0,1},{-1,sinPi,0,-sinPi,-1,0,0,0,1},
                {eps,-1,0,1,eps,0,0,0,1},{eps,1,0,-1,eps,0,0,0,1},
                {eps,0,-1,0,1,0,1,0,eps},{eps,0,1,0,1,0,-1,0,eps}};
            p=Sub(Mul(Row(p,axes[v.axis]),f[6]),Vector(f+2));p[1]+=f[8];p[2]+=f[7];
            const double distance=p[0]/f[0]*f[1]+f[5];
            auto selected=v.begin;
            for(auto s=v.begin+1;s<v.end && segments[s][0]<=distance;++s) selected=s;
            const auto* g=segments[selected].data();const double t=(distance-g[0])/g[1],u=t<1?t:1;
            const V tangent=Unit(Add(Add(Mul(Vector(g+14),u*u),Mul(Vector(g+17),u)),Vector(g+20)));
            V side={-tangent[1],tangent[0],0};
            if(std::hypot(tangent[0],tangent[1])<=double(float(.01))) side={tangent[2],0,-tangent[0]};
            side=Unit(side);V up=Row(Cross(tangent,side),g+23);side=Row(side,g+23);
            const double a=((g[47]*u+g[46])*u+g[45])*u+g[44];
            const V bankSide=Sub(Mul(side,std::cos(a)),Mul(up,std::sin(a)));
            const V bankUp=Add(Mul(side,std::sin(a)),Mul(up,std::cos(a)));
            V center=Add(Mul(Add(Mul(Add(Mul(Vector(g+11),t),Vector(g+8)),t),Vector(g+5)),t),Vector(g+2));
            if(t>1) center=Add(Add(Add(Vector(g+2),Vector(g+5)),Add(Vector(g+8),Vector(g+11))),Mul(Row(tangent,g+23),(t-1)*g[1]));
            const V result=Add(Row(Add(center,Add(Mul(bankSide,p[1]),Mul(bankUp,p[2]))),g+32),Vector(g+41));
            if(!Finite(result)) throw std::runtime_error("Nonfinite spline position");
            return result;
        }
        bool Normal(V p,V n,uint32_t index,V& result) const {
            V rows[3];
            for(size_t i=0;i<3;++i) { V step{};step[i]=1e-3;rows[i]=Mul(Sub(Deform(Add(p,step),index),Deform(Sub(p,step),index)),500); }
            const auto det=Dot(rows[0],Cross(rows[1],rows[2]));
            if(!std::isfinite(det) || det<=1e-10) return false;
            result=Unit(Mul(Add(Add(Mul(Cross(rows[1],rows[2]),n[0]),Mul(Cross(rows[2],rows[0]),n[1])),Mul(Cross(rows[0],rows[1]),n[2])),1/det));
            return true;
        }
    };
}
