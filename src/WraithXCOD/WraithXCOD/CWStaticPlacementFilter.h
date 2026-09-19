#pragma once
#include "json.hpp"
#include <map>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>

// A placement requiring deformation is not equivalent to a rigid XModel at
// the same origin. Preserve it as evidence until spline controls are supported.
namespace CWStaticPlacementFilter
{
    using json = nlohmann::json;
    inline bool RequiresSpline(const json& Row)
    {
        if (Row.value("RequiresSplineDeformation", false)) return true;
        const auto It = Row.find("SplineInstanceIndex");
        if (It == Row.end() || It->is_null() || !It->is_number_integer()) return false;
        const auto Index = It->get<int64_t>();
        return Index >= 0 && Index != 0xFFFFFFFFll;
    }

    inline json Separate(json& Rows, json& Deferred)
    {
        if (!Rows.is_array()) throw std::runtime_error("StaticModels must be an array");
        const auto Captured = Rows.size();
        json Static = json::array(); Deferred = json::array();
        std::map<std::string, size_t> Uses, Skipped;
        size_t Unresolved = 0;
        for (auto& Row : Rows)
        {
            const auto Name = Row.at("Name").get<std::string>();
            if (RequiresSpline(Row)) { ++Skipped[Name]; Deferred.push_back(std::move(Row)); }
            else
            {
                ++Uses[Name];
                if (!Row.value("NameResolved", Name.rfind("xmodel_", 0) != 0)) ++Unresolved;
                Static.push_back(std::move(Row));
            }
        }
        Rows = std::move(Static);
        return {{"export_scope", "rigid_static_placements_only"},
            {"captured_instances", Captured}, {"exported_instances", Rows.size()},
            {"exported_unique_models", Uses.size()}, {"exported_unresolved_model_names", Unresolved},
            {"deferred_spline_instances", Deferred.size()}, {"deferred_spline_unique_models", Skipped.size()},
            {"deferred_spline_models", Skipped}, {"remaining_row_fields_unchanged", true}};
    }
}
