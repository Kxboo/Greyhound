#pragma once
#include "json.hpp"
#include <array>
#include <cmath>
#include <map>
#include <set>
#include <string>
#include <algorithm>

namespace CWModelProxyFilter
{
    using json = nlohmann::json;
    // Observed baked-atlas technique, shared by the independently inspected
    // combined building proxies. This is a shader signature, not a model/map ID.
    constexpr uint64_t BakedAtlasTechnique = 0x7efaea280fc7b24aull;
    struct Model { uint32_t Lods = 0, Surfaces = 0; uint64_t Triangles = 0, Technique = 0; };
    using Box = std::array<double, 6>;
    inline double Volume(const Box& B)
    {
        double V = 1;
        for (int K=0; K<3; ++K)
        { if (!std::isfinite(B[K]) || !std::isfinite(B[K+3]) || B[K+3]<=B[K]) return 0; V*=B[K+3]-B[K]; }
        return V;
    }
    inline double Intersection(const Box& A, const Box& B)
    {
        double V=1;
        for(int K=0;K<3;++K) V*=std::max(0.0,std::min(A[K+3],B[K+3])-std::max(A[K],B[K]));
        return V;
    }
    inline Box Bounds(const json& Row)
    {
        Box B{}; int K=0;
        for (const char* Field : {"BoundsMin", "BoundsMax"})
            for (const char* Axis : {"X","Y","Z"}) B[K++]=Row.at(Field).at(Axis).get<double>();
        return B;
    }
    inline bool Signature(const Model& M)
    { return M.Lods==1 && M.Surfaces==1 && M.Triangles && M.Technique==BakedAtlasTechnique; }

    // A conservative reconstruction filter, not a decode of renderer visibility.
    // Require the baked-proxy signature AND a validated spatially corresponding
    // district containing substantially more non-proxy geometry. Keep ambiguous
    // cases. Removed source rows remain available in excluded_proxies.json.
    inline json Apply(json& Rows, const std::map<std::string, Model>& Catalog,
        const std::map<uint32_t, Box>& DistrictBounds, json& Excluded)
    {
        std::map<uint32_t, std::vector<size_t>> Groups;
        for (size_t I=0;I<Rows.size();++I) Groups[Rows[I].at("District").get<uint32_t>()].push_back(I);
        // Score the same geometry used as replacement evidence. District-wide
        // bounds can include long spline-deformation ranges that are expressly
        // excluded from the detail test below; those must not dilute overlap.
        std::map<uint32_t, Box> DetailBounds;
        for(const auto& G:Groups) for(auto I:G.second)
        {
            const auto& R=Rows[I]; const auto M=Catalog.find(R.at("Name").get<std::string>());
            if(M==Catalog.end() || Signature(M->second) || R.value("RequiresSplineDeformation",false) ||
                !R.contains("BoundsMin") || !R.contains("BoundsMax")) continue;
            const auto B=Bounds(R); if(!Volume(B))continue;
            auto P=DetailBounds.emplace(G.first,B);
            if(!P.second)for(int K=0;K<3;++K)
            {P.first->second[K]=std::min(P.first->second[K],B[K]);P.first->second[K+3]=std::max(P.first->second[K+3],B[K+3]);}
        }
        std::set<size_t> Remove; json Decisions=json::array(); uint32_t Candidates=0;
        for(size_t I=0;I<Rows.size();++I)
        {
            const auto& R=Rows[I]; const auto M=Catalog.find(R.at("Name").get<std::string>());
            if(M==Catalog.end() || !Signature(M->second) || !R.contains("BoundsMin") || !R.contains("BoundsMax") ||
                R.value("RequiresSplineDeformation",false)) continue;
            ++Candidates; const auto B=Bounds(R); const auto V=Volume(B); if(!V) continue;
            double Best=0; json Match;
            for(const auto& D:DistrictBounds)
            {
                if(D.first==R.at("District").get<uint32_t>()) continue;
                const auto G=Groups.find(D.first); if(G==Groups.end()) continue;
                const auto DB=DetailBounds.find(D.first); if(DB==DetailBounds.end())continue;
                const double RawIV=Intersection(B,D.second),RawDV=Volume(D.second);
                if(RawDV<=0 || RawIV<=0)continue;
                const double IV=Intersection(B,DB->second), DV=Volume(DB->second);
                const double IoU=DV>0 ? IV/(V+DV-IV) : 0;
                if(IoU<0.25 || IoU<=Best) continue;
                uint64_t Triangles=0; size_t Count=0; std::set<std::string> Names;
                for(auto J:G->second)
                {
                    const auto& A=Rows[J]; const auto N=A.at("Name").get<std::string>(); const auto F=Catalog.find(N);
                    if(F==Catalog.end() || Signature(F->second) || !A.contains("BoundsMin") || !A.contains("BoundsMax") ||
                        A.value("RequiresSplineDeformation",false)) continue;
                    const auto AB=Bounds(A); const auto AV=Volume(AB);
                    if(AV<=0 || Intersection(B,AB)/AV<0.5) continue;
                    Triangles+=F->second.Triangles; ++Count; Names.insert(N);
                }
                if(Count<4 || Names.size()<3 || Triangles<4*M->second.Triangles) continue;
                Best=IoU;
                Match={{"detail_district",D.first},{"bounds_iou",IoU},{"overlapping_detail_placements",Count},
                    {"overlapping_detail_models",Names.size()},{"detail_triangles",Triangles},
                    {"bounds_basis","non_spline_non_proxy_placement_bounds"},{"detail_bounds",DB->second},
                    {"raw_district_bounds_iou",RawIV/(V+RawDV-RawIV)}};
            }
            if(Best>0)
            {
                Remove.insert(I); auto E=R; E["ProxyFilterEvidence"]=Match; Excluded.push_back(E);
                Match["Name"]=R["Name"]; Match["District"]=R["District"]; Match["ReferenceIndex"]=R["ReferenceIndex"];
                Decisions.push_back(Match);
            }
        }
        const auto SourceCount=Rows.size(); json Kept=json::array();
        for(size_t I=0;I<Rows.size();++I) if(!Remove.count(I)) Kept.push_back(std::move(Rows[I]));
        Rows=std::move(Kept);
        return {{"method","baked_atlas_signature_with_validated_detail_district"},
            {"source_placements",SourceCount},{"exported_placements",Rows.size()},
            {"candidate_placements",Candidates},{"excluded_placements",Remove.size()},
            {"unmatched_candidates_retained",Candidates-Remove.size()},{"decisions",Decisions},
            {"classification","conservative reconstruction heuristic; renderer replacement ownership is not decoded"}};
    }
}
