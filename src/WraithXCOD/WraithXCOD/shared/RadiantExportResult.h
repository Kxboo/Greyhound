#pragma once
#include <fstream>
#include <string>
#include "json.hpp"

// A progress/status string is not a completion result. Require both the
// producer's explicit success and its final verification report.
namespace RadiantExportResult
{
    inline bool Complete(bool ProducerSucceeded, bool BO4, const nlohmann::json& Report)
    {
        if (!ProducerSucceeded) return false;
        try
        {
            if (!Report.is_object()) return false;
            return BO4
                ? Report.value("status", std::string()) == "exported_with_review" && Report.value("prefab_geometry_verified", false)
                : Report.value("status", std::string()) == "exported" && Report.value("all_placed_brushes_present", false);
        }
        catch (const nlohmann::json::exception&) { return false; }
    }

    inline bool Read(bool ProducerSucceeded, bool BO4, const std::string& Output)
    {
        if (!ProducerSucceeded || Output.empty()) return false;
        try
        {
            std::ifstream Input(Output + "/metadata/export_report.json");
            nlohmann::json Report; Input >> Report;
            return Complete(ProducerSucceeded, BO4, Report);
        }
        catch (const std::exception&) { return false; }
    }
}
