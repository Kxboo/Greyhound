#include "stdafx.h"

// The class we are implementing
#include "exporters/ExportJobs.h"

#include <fstream>
#include <limits>
#include <set>
#include "json.hpp"
#include "assets/CoDAssets.h"
#include "FileSystems.h"
#include "Strings.h"
#include "SettingsManager.h"
#include "Image.h"
#include "games/cold_war/reader/GameBlackOpsCW.h"
#include "games/black_ops_4/reader/GameBlackOps4.h"
#include "shared/CWRadiantExport.h"
#include "shared/RadiantExportResult.h"
#include "exporters/ModelBatchSelection.h"
#include "exporters/ModelBatchResume.h"
#include "exporters/ModelExportNaming.h"
#include "games/cold_war/placements/CWStaticPlacementFilter.h"
#include "exporters/ExportRun.h"

namespace
{
    JobResult Fail(const std::string& Status, const std::string& Path = std::string())
    {
        JobResult Result;
        Result.Status = Status;
        Result.Path = Path;
        return Result;
    }

    // GREYHOUND_BO4_WORLD_PROBE, when set, overrides the saved capture mode.
    bool Bo4ProbeOverride(std::string& Value)
    {
        char Override[2] = {};
        if (GetEnvironmentVariableA("GREYHOUND_BO4_WORLD_PROBE", Override, 2) != 1)
            return false;
        Value = Override;
        return true;
    }
}

std::string ExportJobs::CheckModelsFromJson()
{
    if (CoDAssets::GameID != SupportedGames::BlackOpsCW && CoDAssets::GameID != SupportedGames::BlackOps4)
        return "Models from JSON supports Cold War and BO4 CAST exports.";
    if (!CoDAssets::GameAssets)
        return "Load Game with XModels enabled first.";
    return {};
}

std::string ExportJobs::CheckSplineModels()
{
    if (CoDAssets::GameID != SupportedGames::BlackOpsCW || !CoDAssets::GameAssets)
        return "Load the matching Cold War map with XModels enabled first.";
    return {};
}

std::string ExportJobs::CheckRadiantBrushes()
{
    if (!CoDAssets::GameInstance ||
        (CoDAssets::GameID != SupportedGames::BlackOps4 && CoDAssets::GameID != SupportedGames::BlackOpsCW))
        return "Load a Black Ops 4 or Cold War map first.";
    return {};
}

std::string ExportJobs::CheckTerrainSource()
{
    if (!CoDAssets::GameAssets || !CoDAssets::GameInstance)
        return "Load a Cold War or Black Ops 4 map first.";
    std::string Override;
    if (CoDAssets::GameID == SupportedGames::BlackOps4 && Bo4ProbeOverride(Override) && Override != "0")
        return "GREYHOUND_BO4_WORLD_PROBE selects a diagnostic. Clear it or set it to 0 for raw terrain source.";
    for (const auto* Asset : CoDAssets::GameAssets->LoadedAssets)
        if (Asset->AssetType == WraithAssetType::Terrain)
            return {};
    return "Enable TerrainGfx in Terrain settings, then Load Game.";
}

std::string ExportJobs::CheckBo4Diagnostic(int& Mode)
{
    if (CoDAssets::GameID != SupportedGames::BlackOps4 || !CoDAssets::GameInstance)
        return "Load Game with a Black Ops 4 map open first.";
    auto Selected = SettingsManager::GetSetting("bo4capturemode", "0");
    Bo4ProbeOverride(Selected);
    Mode = Selected.size() == 1 ? Selected[0] - '0' : 0;
    if (Mode != 5 && (Mode < 1 || Mode > 7))
        return "Select a TerrainGfx row and Export Selected for terrain source data.";
    return {};
}

JobResult ExportJobs::ModelPlacements(JobSink& Sink)
{
    const auto Directory = ExportRun::Reserve("placements", "run");
    if (Directory.empty())
        return Fail("Could not create the placements export folder.");
    JobResult Result;
    Result.Path = Directory;
    try
    {
        const auto Progress = [&Sink](uint32_t P) { Sink.Progress(P); };
        Result.Status = CoDAssets::GameID == SupportedGames::BlackOps4
            ? GameBlackOps4::ExportModelPlacements(Directory, Progress)
            : GameBlackOpsCW::ExportModelPlacements(Directory, Progress);
        Result.Ok = true;
    }
    catch (const std::exception& E) { Result.Status = std::string("Placement export failed: ") + E.what(); }
    CoDAssets::LatestExportPath = Directory;
    return Result;
}

JobResult ExportJobs::RadiantBrushes(JobSink& Sink)
{
    const auto Problem = CheckRadiantBrushes();
    if (!Problem.empty()) return Fail(Problem);
    JobResult Result;
    try
    {
        const auto Notify = [&Sink](uint32_t P, const std::string& Stage) { Sink.Progress(P); Sink.Status(Stage); };
        CoDAssets::LatestExportPath.clear();
        bool Succeeded = false;
        Result.Status = CoDAssets::GameID == SupportedGames::BlackOps4
            ? GameBlackOps4::ExportRadiantBrushes(Notify, &Succeeded)
            : GameBlackOpsCW::ExportRadiantBrushes(Notify, &Succeeded);
        Result.Path = CoDAssets::LatestExportPath;
        Result.Ok = RadiantExportResult::Read(Succeeded, CoDAssets::GameID == SupportedGames::BlackOps4, Result.Path);
        if (Succeeded && !Result.Ok)
            Result.Status = "Brush export did not produce a verified completion report. Open the export folder for diagnostics.";
    }
    catch (const std::exception& E) { Result.Status = std::string("Brush export failed: ") + E.what(); }
    return Result;
}

JobResult ExportJobs::ModelsFromJson(const std::string& File, JobSink& Sink)
{
    using json = nlohmann::json;
    Sink.Status("Reading placements...");
    std::set<std::string> Names;
    json PlacementRows;
    json PlacementSelection = json::object();
    json DeferredPlacementRows = json::array();
    ModelExportNaming::SourceLookup Lookup;
    for (const auto* Asset : CoDAssets::GameAssets->LoadedAssets)
        if (Asset->AssetType == WraithAssetType::Model)
            Lookup.Add(Asset->AssetName, Strings::Format("xmodel_%llx", CoDAssets::GameInstance->Read<uint64_t>(Asset->AssetPointer) & 0xFFFFFFFFFFFFFFF));
    try
    {
        std::ifstream Input(File); json Doc; Input >> Doc;
        const auto& Rows = Doc.is_array() ? Doc : Doc.at("StaticModels");
        if (!Rows.is_array()) throw std::runtime_error("StaticModels must be an array");
        PlacementRows = Rows;
        if (CoDAssets::GameID == SupportedGames::BlackOpsCW)
            PlacementSelection = CWStaticPlacementFilter::Separate(PlacementRows, DeferredPlacementRows);
        for (const auto& Row : PlacementRows)
        {
            const auto Name = Row.at("Name").get<std::string>();
            if (!Name.empty()) Names.insert(Lookup.Resolve(Name, Row.value("SourceName", std::string())));
        }
        if (Names.empty()) throw std::runtime_error("No supported rigid model placements found; spline placements are excluded.");
        for (auto& Row : PlacementRows)
        {
            Row["SourceName"] = Lookup.Resolve(Row.at("Name").get<std::string>(), Row.value("SourceName", std::string()));
            ModelExportNaming::PublishPlacementName(Row);
        }
    }
    catch (const std::exception& E)
    {
        return Fail(std::string("Select a model placement array (static_models.json, non_static_models.json or a per-class model file).\n") + E.what());
    }

    struct ModelRequest
    {
        std::string Name;
        std::vector<CoDAsset_t*> Candidates;
        size_t Selected;
    };
    std::vector<ModelRequest> Queue;
    size_t DuplicateNames = 0;
    for (const auto& Name : Names)
    {
        ModelRequest Request{ Name, {}, (std::numeric_limits<size_t>::max)() };
        std::vector<ModelBatchSelection::Candidate> Selection;
        for (auto* Asset : CoDAssets::GameAssets->LoadedAssets)
            if (Asset->AssetType == WraithAssetType::Model && Asset->AssetName == Name)
            {
                const auto State = Asset->AssetStatus;
                const bool Usable = State != WraithAssetStatus::Placeholder &&
                    State != WraithAssetStatus::NotLoaded && State != WraithAssetStatus::Processing;
                Selection.push_back({ Asset->AssetPointer, Request.Candidates.size(), Usable,
                    State == WraithAssetStatus::Exported, State == WraithAssetStatus::Loaded });
                Request.Candidates.push_back(Asset);
            }
        Request.Selected = ModelBatchSelection::Select(Selection);
        if (Request.Candidates.size() > 1) ++DuplicateNames;
        Queue.push_back(std::move(Request));
    }
    json Options = json::object();
    for (const auto* Key : { "exportalllods","match_game_lod_index","exportmodelimg","exportimg","exportimgnames","exportvtxcolor","exporthitbox","patchcolor","patchnormals" })
        Options[Key] = SettingsManager::GetSetting(Key);
    Options["layout"] = "per_model_images_mat_info";
    Options["exportmodelimg"] = "true"; Options["exportimgnames"] = "true";
    std::string BatchRoot;
    bool Resume = false;
    auto ExistingRoot = FileSystems::GetDirectoryName(File);
    if (!ModelBatchResume::PerModelBatch(ExistingRoot))
        ExistingRoot = ModelBatchResume::FindExisting(CoDAssets::BuildMapExportPath("models_from_json"), Names, Options);
    if (FileSystems::FileExists(FileSystems::CombinePath(ExistingRoot, "model_identities.json")) &&
        ModelBatchResume::PerModelBatch(ExistingRoot))
    {
        const auto Prompt = "Matching model export found:\n" + ExistingRoot +
            "\n\nResume here?\nYes: keep completed models and retry unfinished ones.\nNo: create a new export.\nCancel: do nothing.";
        const auto Choice = Sink.Ask("Resume models from JSON", Prompt);
        if (Choice == IDCANCEL)
        {
            JobResult Result;
            Result.Cancelled = true;
            Result.Status = "Nothing exported.";
            return Result;
        }
        Resume = Choice == IDYES;
        if (Resume) BatchRoot = ExistingRoot;
    }
    // Only reserve a new run once resuming has been ruled out, so declining or
    // cancelling never leaves an empty run folder behind.
    if (!Resume)
    {
        BatchRoot = ExportRun::Reserve("models_from_json", "run");
        if (BatchRoot.empty())
            return Fail("Could not create the models_from_json export folder.");
    }
    // Preserve rejected source rows before refreshing a resumed batch whose
    // own placement file may have been selected as input.
    if (!DeferredPlacementRows.empty())
    {
        std::ofstream DeferredOutput(FileSystems::CombinePath(BatchRoot, "deferred_spline_placements.json"), std::ios::binary);
        DeferredOutput << DeferredPlacementRows.dump(2); DeferredOutput.close();
        if (!DeferredOutput) return Fail("Could not preserve deferred spline placements.", BatchRoot);
    }
    // Refresh CW resumes only; BO4's existing resume behavior is unchanged.
    if (!Resume || CoDAssets::GameID == SupportedGames::BlackOpsCW)
    {
        std::ofstream PlacementOutput(FileSystems::CombinePath(BatchRoot, "static_models.json"), std::ios::binary);
        PlacementOutput << PlacementRows.dump(2); PlacementOutput.close();
        if (!PlacementOutput) return Fail("Could not create JSON batch output.", BatchRoot);
    }
    if (!PlacementSelection.empty())
    {
        std::ofstream SelectionOutput(FileSystems::CombinePath(BatchRoot, "placement_selection_report.json"), std::ios::binary);
        SelectionOutput << PlacementSelection.dump(2);
        SelectionOutput.close();
        if (!SelectionOutput) return Fail("Could not save placement selection report.", BatchRoot);
    }
    json Identities = json::object(), CompletedModels = json::object();
    const auto CheckpointPath = FileSystems::CombinePath(BatchRoot, "model_export_checkpoint.json");
    bool LegacySingleLod = Resume && !FileSystems::FileExists(CheckpointPath) &&
        Options["exportalllods"] != "true" && Options["match_game_lod_index"] != "true";
    try
    {
        if (Resume)
        {
            std::ifstream IdFile(FileSystems::CombinePath(BatchRoot, "model_identities.json")); IdFile >> Identities;
            if (FileSystems::FileExists(CheckpointPath))
            {
                json Checkpoint; std::ifstream Input(CheckpointPath); Input >> Checkpoint;
                if (Checkpoint.at("options") == Options)
                {
                    CompletedModels = Checkpoint.at("completed_models");
                    LegacySingleLod = Checkpoint.value("legacy_single_lod", false);
                }
            }
        }
    }
    catch (const std::exception& E) { return Fail(std::string("Could not read resume metadata: ") + E.what(), BatchRoot); }

    CoDAssets::CanExportContinue = true;
    json Results = json::array(); size_t Done = 0, Success = 0, Failed = 0, Missing = 0, Unavailable = 0, Kept = 0;
    bool CheckpointFailed = false;
    Sink.Status("Waiting for model package cache...");
    if (CoDAssets::GamePackageCache) CoDAssets::GamePackageCache->WaitForPackageCacheLoad();
    Image::SetupConversionThread();
    for (const auto& Item : Queue)
    {
        if (!CoDAssets::CanExportContinue) break;
        Sink.Status("Completed " + std::to_string(Done) + " / " + std::to_string(Queue.size()) + " unique models | " + ModelExportNaming::FileStem(Item.Name));
        std::string Status, Error;
        json Candidates = json::array();
        for (size_t Index = 0; Index < Item.Candidates.size(); ++Index)
        {
            const auto* Candidate = Item.Candidates[Index];
            Candidates.push_back({ {"asset_pointer",Strings::Format("0x%llx",Candidate->AssetPointer)},
                {"loaded_index",Candidate->AssetLoadedIndex}, {"status_before",int(Candidate->AssetStatus)},
                {"selected",Index == Item.Selected} });
        }
        bool Keep = false;
        try { Keep = Resume && ModelBatchResume::Completed(BatchRoot, Item.Name, Identities, CompletedModels, LegacySingleLod); }
        catch (const std::exception&) { Keep = false; }
        if (Keep) { Status = "kept_existing"; ++Kept; }
        else if (Item.Candidates.empty()) { Status = "missing"; ++Missing; }
        else if (Item.Selected == (std::numeric_limits<size_t>::max)()) { Status = "unavailable"; ++Unavailable; }
        else
        {
            try { auto R = CoDAssets::ExportJsonBatchModel(static_cast<const CoDModel_t*>(Item.Candidates[Item.Selected]), BatchRoot); Status = R == ExportGameResult::Success ? "exported" : "failed"; }
            catch (const std::exception& E) { Status = "failed"; Error = E.what(); }
            if (Status == "exported") ++Success; else ++Failed;
        }
        Results.push_back({ {"Name",ModelExportNaming::FileStem(Item.Name)},{"SourceName",Item.Name},
            {"output_directory",ModelBatchResume::Directory(BatchRoot,Item.Name)},
            {"status",Status},{"error",Error},
            {"candidate_count",Item.Candidates.size()},{"candidates",Candidates},
            {"selection_policy","prefer previously exported, then loaded, then other usable; address order breaks ties"},
            {"candidate_geometry_equivalence_verified",false} });
        if (Status == "exported" || Status == "kept_existing")
        {
            try
            {
                auto Files = json::array();
                if (Status == "kept_existing" && CompletedModels.contains(Item.Name)) Files = CompletedModels.at(Item.Name);
                else if (Status == "kept_existing" && LegacySingleLod)
                {
                    const auto FileName = ModelExportNaming::FileStem(Item.Name) + ".cast";
                    Files.push_back({ {"file",FileName},{"bytes",ModelBatchResume::FileSize(ModelBatchResume::Directory(BatchRoot,Item.Name) + "/" + FileName)} });
                }
                else Files = ModelBatchResume::Files(BatchRoot, Item.Name);
                if (!Files.empty()) CompletedModels[Item.Name] = std::move(Files);
            }
            catch (const std::exception&) { CompletedModels.erase(Item.Name); }
        }
        // Persist after every model; replacement is atomic so a crash cannot
        // destroy the last usable checkpoint. The final report remains separate.
        try
        {
            std::ofstream Output(CheckpointPath + ".tmp", std::ios::binary);
            Output << json({ {"schema","greyhound-model-resume-v1"},{"options",Options},{"legacy_single_lod",LegacySingleLod},{"completed_models",CompletedModels} }).dump(2);
            Output.close();
            if (!Output || !MoveFileExA((CheckpointPath + ".tmp").c_str(), CheckpointPath.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) CheckpointFailed = true;
        }
        catch (const std::exception&) { CheckpointFailed = true; }
        ++Done; Sink.Progress(uint32_t(100ull * Done / Queue.size()));
    }
    Image::DisableConversionThread();
    CoDAssets::LatestExportPath = BatchRoot;
    json Report = { {"schema","greyhound-models-from-json-v4"},{"source",File},{"output_directory",BatchRoot},{"layout","per_model_images_mat_info"},{"model_format","cast"},{"unique_models",Queue.size()},
        {"completed",Done},{"exported",Success},{"kept_existing",Kept},{"resumed",Resume},{"checkpoint_write_failed",CheckpointFailed},{"failed",Failed},{"missing",Missing},{"unavailable",Unavailable},
        {"duplicate_names",DuplicateNames},{"cancelled",Done < Queue.size()},{"models",Results} };
    std::string ReportPath = FileSystems::CombinePath(BatchRoot, "model_export_report.json"); std::ofstream Output(ReportPath); Output << Report.dump(2); Output.close();
    std::string Summary = (Done < Queue.size() ? "Cancelled: " : "Finished: ") + std::to_string(Done) + " / " + std::to_string(Queue.size()) + "; kept " + std::to_string(Kept) + ", exported " + std::to_string(Success) + ", failed " + std::to_string(Failed) + ", missing " + std::to_string(Missing) + ", unavailable " + std::to_string(Unavailable) + ", duplicate names " + std::to_string(DuplicateNames);
    if (CheckpointFailed) Summary += "; checkpoint could not be saved";
    if (!Output) Summary += "; report could not be saved";
    Summary += " | Output: " + BatchRoot;

    JobResult Result;
    Result.Ok = Done == Queue.size() && Failed == 0 && !CheckpointFailed && Output.good();
    Result.Status = Summary;
    Result.Path = BatchRoot;
    return Result;
}

JobResult ExportJobs::SplineModels(const std::string& Placements, const std::string& Controls, JobSink& Sink)
{
    const auto Root = ExportRun::Reserve("spline_models", "run");
    if (Root.empty())
        return Fail("Spline export failed: Could not create spline export folder");
    JobResult Result;
    Result.Path = Root;
    try
    {
        const auto Notify = [&Sink](uint32_t P, const std::string& Stage) { Sink.Progress(P); Sink.Status(Stage); };
        Result.Ok = CoDAssets::ExportSplineModels(Placements, Controls, Root, Notify);
        Result.Status = (Result.Ok ? "Spline models exported: " : "Spline export incomplete; check spline_export_report.json: ") + Root;
    }
    catch (const std::exception& E) { Result.Status = std::string("Spline export failed: ") + E.what(); }
    return Result;
}

JobResult ExportJobs::TerrainSource(JobSink& Sink)
{
    std::vector<const CoDAsset_t*> Terrains;
    for (auto* Asset : CoDAssets::GameAssets->LoadedAssets)
        if (Asset->AssetType == WraithAssetType::Terrain) Terrains.push_back(Asset);
    const auto Previous = SettingsManager::GetSetting("bo4capturemode", "0");
    SettingsManager::SetSetting("bo4capturemode", "0");
    bool Okay = true;
    uint32_t Done = 0;
    for (auto* Terrain : Terrains)
    {
        Sink.Status("Capturing " + Terrain->AssetName + "...");
        if (CoDAssets::ExportAsset(Terrain, nullptr, 0, 100, true) != ExportGameResult::Success) Okay = false;
        Sink.Progress(uint32_t(100ull * ++Done / Terrains.size()));
    }
    SettingsManager::SetSetting("bo4capturemode", Previous);
    JobResult Result;
    Result.Ok = Okay;
    Result.Path = CoDAssets::LatestExportPath;
    Result.Status = std::string(Okay ? "Terrain source saved: " : "Terrain capture incomplete; inspect the logs: ") + CoDAssets::LatestExportPath;
    return Result;
}

JobResult ExportJobs::Bo4Diagnostic(int Mode, JobSink& Sink)
{
    const auto Directory = ExportRun::Reserve("diagnostics", "bo4_mode_" + std::to_string(Mode));
    JobResult Result;
    Result.Path = Directory;
    try
    {
        Result.Ok = !Directory.empty() && GameBlackOps4::ExportDiagnostic(Mode, Directory);
        if (!Directory.empty()) CoDAssets::LatestExportPath = Directory;
        Result.Status = (Result.Ok ? "Diagnostic capture saved: " : "Diagnostic capture incomplete; inspect the report: ") + Directory;
    }
    catch (const std::exception& E) { Result.Status = std::string("Diagnostic capture failed: ") + E.what(); }
    return Result;
}

JobResult ExportJobs::VerifyRuntime(const std::string& Report, JobSink& Sink)
{
    const bool Saved = !Report.empty();
    const auto Directory = ExportRun::Reserve("diagnostics", Saved ? "saved_export_check" : "runtime_check");
    JobResult Result;
    Result.Path = Directory;
    try
    {
        Result.Ok = !Directory.empty() && CWRadiantExport::VerifyRuntime(Directory, Report);
        if (!Directory.empty()) CoDAssets::LatestExportPath = Directory;
        if (Saved)
            Result.Status = (Result.Ok ? "Saved file integrity passed. Report: " : "Saved export check failed. Report: ") + Directory;
        else
            Result.Status = (Result.Ok ? "Runtime checks passed. Report: " : "Runtime checks failed. Check tools and the report: ") + Directory;
    }
    catch (const std::exception& E)
    {
        Result.Status = std::string(Saved ? "Saved export check failed: " : "Runtime check failed: ") + E.what();
    }
    return Result;
}
