#pragma once
#include "games/cold_war/placements/CWSplineBake.h"
#include "WraithModel.h"
#include <algorithm>

namespace CWSplineBake
{
    inline V ToV(const Vector3& p) {return {p.X,p.Y,p.Z};}
    inline Vector3 ToVector(V p) {return Vector3(float(p[0]),float(p[1]),float(p[2]));}
    inline void BakeModel(WraithModel& model,const Controls& controls,uint32_t index,
        V& origin,bool& hasOrigin,std::vector<size_t>& fallbackMeshes)
    {
        if(model.Bones.empty() || !model.BlendShapes.empty() || model.Submeshes.empty())
            throw std::runtime_error("Spline baking requires a static model without blend shapes");
        // Extra bind bones are flattened, without applying their offsets a
        // second time to the model-space vertices. No animated pose is captured.
        for(const auto& bone:model.Bones) {
            const auto& l=bone.LocalRotation;const auto& g=bone.GlobalRotation;
            if(!StaticBindTransform(ToV(bone.LocalPosition),ToV(bone.GlobalPosition),
                {l.X,l.Y,l.Z,l.W},{g.X,g.Y,g.Z,g.W},ToV(bone.BoneScale),&bone==&model.Bones.front()))
                throw std::runtime_error("Unsupported spline model bind transform");
        }
        std::vector<std::vector<V>> positions,normals;
        V lo={INFINITY,INFINITY,INFINITY},hi={-INFINITY,-INFINITY,-INFINITY};
        for(const auto& mesh:model.Submeshes) {
            if(mesh.Verticies.empty() || mesh.Faces.empty()) throw std::runtime_error("Empty spline mesh");
            std::vector<V> p,n;bool folded=false;
            for(const auto& vertex:mesh.Verticies) {
                for(const auto& w:vertex.Weights)
                    if(w.BoneIndex>=model.Bones.size() || !std::isfinite(w.Weight) || w.Weight<0)
                        throw std::runtime_error("Invalid spline skin weight");
                const auto v=controls.Deform(ToV(vertex.Position),index);p.push_back(v);
                V normal{};if(!controls.Normal(ToV(vertex.Position),ToV(vertex.Normal),index,normal)) folded=true;
                n.push_back(normal);
                for(size_t a=0;a<3;++a) {lo[a]=(std::min)(lo[a],v[a]);hi[a]=(std::max)(hi[a],v[a]);}
            }
            for(const auto& face:mesh.Faces)
                if(face.Index1>=p.size() || face.Index2>=p.size() || face.Index3>=p.size()) throw std::runtime_error("Invalid spline face");
            if(folded) {
                fallbackMeshes.push_back(positions.size());n.assign(p.size(),V{});
                std::vector<V> largest(p.size());std::vector<double> area(p.size(),0);
                for(const auto& face:mesh.Faces) {
                    // Match CAST's (Index3, Index2, Index1) topology orientation.
                    const auto normal=Cross(Sub(p[face.Index2],p[face.Index3]),Sub(p[face.Index1],p[face.Index3]));
                    for(auto i:{face.Index1,face.Index2,face.Index3}) {
                        n[i]=Add(n[i],normal);const auto size=Dot(normal,normal);
                        if(size>area[i]) {area[i]=size;largest[i]=normal;}
                    }
                }
                for(size_t i=0;i<n.size();++i) {
                    if(Dot(n[i],n[i])<=1e-24) n[i]=area[i]>1e-24?largest[i]:ToV(mesh.Verticies[i].Normal);
                    n[i]=Unit(n[i]);
                }
            }
            positions.push_back(std::move(p));normals.push_back(std::move(n));
        }
        // All selected LODs share the first exported LOD's origin.
        if(!hasOrigin) {origin=Mul(Add(lo,hi),.5);hasOrigin=true;}
        for(size_t m=0;m<model.Submeshes.size();++m)
            for(size_t v=0;v<model.Submeshes[m].Verticies.size();++v) {
                auto& vertex=model.Submeshes[m].Verticies[v];
                vertex.Position=ToVector(Sub(positions[m][v],origin));vertex.Normal=ToVector(normals[m][v]);
                vertex.Weights.clear();vertex.Weights.emplace_back(0,1.0f);
            }
        model.Bones.resize(1);model.Bones.front().BoneParent=-1;
    }
}
