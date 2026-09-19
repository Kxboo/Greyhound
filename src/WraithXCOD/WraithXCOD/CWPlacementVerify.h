#pragma once

#include <string>
#include <vector>
#include "CoDAssets.h"
#include "FileSystems.h"
#include "Strings.h"
#include "json.hpp"

// Runs the two post-export auditors against a finished Cold War placement run.
//
// Both scripts are assertion-based: they walk the exported JSON back to the raw
// captured bytes and write their summary only when every check passes. So a
// non-zero exit is a real discrepancy, not a missing optional file -- and the
// reason exists only in the traceback, which is why the run gets a log folder.
//
// Verification never rewrites or deletes the export. A failure means the saved
// files disagree with the bytes they came from, which the user has to see; it
// does not make the already-written capture any less of a capture.
namespace CWPlacementVerify
{
    using json = nlohmann::json;

    inline std::string CatalogScript() { return "cold_war/capture/verify_cw_placement_catalog.py"; }
    inline std::string FxAnmScript() { return "cold_war/capture/verify_cw_fx_anm.py"; }

    // Both auditors read the non-static stage's output: the catalogue for
    // FX/animation joins, the report for entity-class partitions.
    inline bool SourceReady(const std::string& Directory)
    {
        return FileSystems::FileExists(
                   FileSystems::CombinePath(Directory, "fx_anm_catalog.json")) &&
               FileSystems::FileExists(
                   FileSystems::CombinePath(Directory, "non_static_report.json"));
    }

    inline json Run(const std::string& Directory)
    {
        if (!SourceReady(Directory))
            return {{"verified", false}, {"reason", "no_focused_capture"},
                {"detail", "Enable non-static placements to produce the files the auditors read."}};

        const auto Logs = FileSystems::CombinePath(Directory, "logs");
        if (!FileSystems::DirectoryExists(Logs))
            FileSystems::CreateDirectory(Logs);

        json Checks = json::array();
        std::vector<std::string> Failed;
        bool Unavailable = false;

        const auto Audit = [&](const std::string& Script, const std::string& Name,
            const std::vector<std::string>& Arguments, const std::string& Report)
        {
            const int Code = CoDAssets::RunCaptureScript(Script, Arguments, Logs);
            json Entry = {{"script", Name}, {"passed", Code == 0}};
            if (Code == -1) { Entry["reason"] = "python_unavailable"; Unavailable = true; }
            else if (Code != 0) { Entry["exit_code"] = Code; Failed.push_back(Name); }
            else Entry["report"] = Report;
            Checks.push_back(Entry);
        };

        Audit(CatalogScript(), "verify_cw_placement_catalog",
            { Directory, "--output", FileSystems::CombinePath(Directory, "validation.json") },
            "validation.json");
        Audit(FxAnmScript(), "verify_cw_fx_anm", { Directory }, "fx_anm_validation.json");

        json Result = {{"checks", Checks}, {"export_unchanged", true}};
        if (Unavailable)
        {
            Result["verified"] = false;
            Result["reason"] = "python_unavailable";
            Result["detail"] = "Install Python or set SUPERTERRAIN_PYTHON, then re-run.";
            return Result;
        }
        Result["verified"] = Failed.empty();
        if (!Failed.empty())
        {
            Result["failed"] = Failed;
            Result["log"] = "logs/terrain_pipeline.log";
        }
        return Result;
    }

    // One line for the export summary. A discrepancy is stated plainly rather
    // than folded into the same "skipped" wording as a missing interpreter.
    inline std::string Describe(const json& Result)
    {
        if (Result.value("verified", false))
            return " Verified against captured bytes: validation.json, fx_anm_validation.json.";
        const auto Reason = Result.value("reason", std::string());
        if (Reason == "python_unavailable")
            return " Verification skipped (Python not available); this export is unaffected.";
        if (Reason == "no_focused_capture")
            return " Verification skipped (needs non-static placements); this export is unaffected.";
        std::string Names;
        for (const auto& Name : Result.value("failed", std::vector<std::string>()))
            Names += (Names.empty() ? "" : ", ") + Name;
        return " VERIFICATION FAILED (" + (Names.empty() ? std::string("unknown") : Names) +
            "). The saved files disagree with the captured bytes; see logs/terrain_pipeline.log.";
    }
}
