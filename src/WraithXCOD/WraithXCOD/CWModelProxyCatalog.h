#pragma once
#include "json.hpp"
#include <cstdlib>
#include <functional>
#include <map>
#include <set>
#include <string>
#include "CoDAssets.h"
#include "CoDAssetType.h"
#include "CWModelProxyFilter.h"
#include "GameBlackOpsCW.h"
#include "ModelExportNaming.h"

// CWModelProxyFilter scores placements against per-model geometry it cannot
// read itself. This gathers that evidence from the models already loaded for
// this map and hands the filter the two tables it expects. A model that cannot
// be read is simply left out of the catalogue, which makes the filter keep its
// placements -- the conservative direction.
namespace CWModelProxyCatalog
{
    using json = nlohmann::json;

    // GameBlackOpsCW formats every techset as "xtechset_<hex>"; the filter
    // compares the raw hash. Anything else yields 0, which never matches the
    // baked-atlas signature.
    inline uint64_t TechniqueHash(const std::string& TechsetName)
    {
        constexpr char Prefix[] = "xtechset_";
        constexpr size_t PrefixLength = sizeof(Prefix) - 1;
        if (TechsetName.compare(0, PrefixLength, Prefix) != 0) return 0;
        return std::strtoull(TechsetName.c_str() + PrefixLength, nullptr, 16);
    }

    inline bool Describe(const XModel_t& Model, CWModelProxyFilter::Model& Out)
    {
        if (Model.ModelLods.empty()) return false;
        const auto& Base = Model.ModelLods.front();
        Out.Lods = static_cast<uint32_t>(Model.ModelLods.size());
        Out.Surfaces = static_cast<uint32_t>(Base.Submeshes.size());
        Out.Triangles = 0;
        for (const auto& Submesh : Base.Submeshes) Out.Triangles += Submesh.FaceCount;
        Out.Technique = Base.Materials.empty() ? 0 : TechniqueHash(Base.Materials.front().TechsetName);
        return true;
    }

    // Per-district extents come from the placements themselves. The pool stores
    // no district bounding box, and a union of member bounds is the same region
    // the filter compares a proxy against.
    inline std::map<uint32_t, CWModelProxyFilter::Box> DistrictBounds(const json& Rows)
    {
        std::map<uint32_t, CWModelProxyFilter::Box> Bounds;
        for (const auto& Row : Rows)
        {
            if (!Row.contains("BoundsMin") || !Row.contains("BoundsMax")) continue;
            const auto District = Row.at("District").get<uint32_t>();
            const auto Box = CWModelProxyFilter::Bounds(Row);
            if (!CWModelProxyFilter::Volume(Box)) continue;
            const auto Existing = Bounds.emplace(District, Box);
            if (Existing.second) continue;
            for (int K = 0; K < 3; ++K)
            {
                Existing.first->second[K] = (std::min)(Existing.first->second[K], Box[K]);
                Existing.first->second[K + 3] = (std::max)(Existing.first->second[K + 3], Box[K + 3]);
            }
        }
        return Bounds;
    }

    inline json Apply(json& Rows, json& Excluded,
        const std::function<void(uint32_t)>& Progress = nullptr)
    {
        if (!Rows.is_array() || Rows.empty())
            return {{"applied", false}, {"reason", "no_placements"}};
        if (!CoDAssets::GameAssets)
            return {{"applied", false}, {"reason", "models_not_loaded"},
                {"detail", "Load Game with XModels enabled to score proxy candidates."}};

        ModelExportNaming::SourceLookup Lookup;
        for (const auto* Asset : CoDAssets::GameAssets->LoadedAssets)
            if (Asset->AssetType == WraithAssetType::Model) Lookup.Add(Asset->AssetName);

        std::set<std::string> Names;
        for (const auto& Row : Rows)
        {
            const auto Name = Row.value("Name", std::string());
            if (!Name.empty()) Names.insert(Name);
        }

        std::map<std::string, CWModelProxyFilter::Model> Catalog;
        size_t Unreadable = 0, Index = 0;
        for (const auto& Name : Names)
        {
            ++Index;
            if (Progress && !Names.empty())
                Progress(static_cast<uint32_t>(Index * 100 / Names.size()));
            std::string Source;
            try { Source = Lookup.Resolve(Name, std::string()); }
            catch (const std::exception&) { ++Unreadable; continue; } // Ambiguous name.
            const CoDAsset_t* Found = nullptr;
            for (const auto* Asset : CoDAssets::GameAssets->LoadedAssets)
                if (Asset->AssetType == WraithAssetType::Model && Asset->AssetName == Source)
                {
                    const auto State = Asset->AssetStatus;
                    if (State == WraithAssetStatus::Placeholder ||
                        State == WraithAssetStatus::NotLoaded) continue;
                    Found = Asset; break;
                }
            if (!Found) { ++Unreadable; continue; }
            CWModelProxyFilter::Model Described;
            try
            {
                const auto Model = GameBlackOpsCW::ReadXModel(
                    reinterpret_cast<const CoDModel_t*>(Found));
                if (!Model || !Describe(*Model, Described)) { ++Unreadable; continue; }
            }
            catch (const std::exception&) { ++Unreadable; continue; }
            Catalog.emplace(Name, Described);
        }

        if (Catalog.empty())
            return {{"applied", false}, {"reason", "no_models_readable"},
                {"unreadable_models", Unreadable}};

        auto Summary = CWModelProxyFilter::Apply(Rows, Catalog, DistrictBounds(Rows), Excluded);
        Summary["applied"] = true;
        Summary["catalogued_models"] = Catalog.size();
        Summary["unreadable_models"] = Unreadable;
        Summary["unreadable_models_retained"] = true;
        return Summary;
    }
}
