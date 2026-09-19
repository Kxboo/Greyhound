#pragma once
#include "json.hpp"
#include <string>
#include "CoDAssets.h"
#include "FileSystems.h"
#include "Strings.h"

// The placement export saves two dozen loose evidence files into one folder.
// tools/cold_war/capture/organize_cw_placements.py sorts that run into per-category
// folders with a checksum catalogue. It reads saved capture files only.
namespace CWPlacementOrganize
{
    using json = nlohmann::json;

    inline std::string Script() { return "cold_war/capture/organize_cw_placements.py"; }

    // Requires the focused capture the non-static stage writes; without it the
    // organizer has no catalogue to key the run on and would fail anyway.
    inline bool SourceReady(const std::string& Directory)
    {
        return FileSystems::FileExists(
            FileSystems::CombinePath(Directory, "fx_anm_catalog.json"));
    }

    // A missing interpreter leaves the flat export usable. The helper stages
    // and verifies the organized run before replacing the original directory.
    inline json Run(const std::string& Directory)
    {
        if (!SourceReady(Directory))
            return {{"organized", false}, {"reason", "no_focused_capture"},
                {"detail", "Enable non-static placements to produce fx_anm_catalog.json."}};
        const auto& Target = Directory;
        // Keep the inherited log handle outside the directory being renamed.
        const auto Logs = FileSystems::CombinePath(FileSystems::GetDirectoryName(Directory), "logs");
        FileSystems::CreateDirectory(Logs);
        const int Code = CoDAssets::RunCaptureScript(Script(), { Directory, "--in-place" }, Logs);
        if (Code == -1)
            return {{"organized", false}, {"reason", "python_unavailable"},
                {"detail", "Install Python or set SUPERTERRAIN_PYTHON, then re-run."}};
        if (Code != 0)
            return {{"organized", false}, {"reason", "organizer_failed"},
                {"exit_code", Code}, {"directory", Target}};
        return {{"organized", true}, {"directory", Target},
            {"catalog", "catalog.json"},
            {"source_evidence_preserved", true}, {"in_place", true}};
    }
}
