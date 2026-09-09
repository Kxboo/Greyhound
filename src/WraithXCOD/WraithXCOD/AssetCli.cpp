#include "stdafx.h"

#include "AssetCli.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "CoDAssets.h"
#include "FileSystems.h"
#include "SettingsManager.h"
#include "Strings.h"
#include "json.hpp"

namespace
{
    using json = nlohmann::json;

    enum class OutputMode
    {
        Human,
        Json,
        JsonLines,
    };

    struct AssetOptions
    {
        std::string Action;
        std::string ModelBatchRoot;
        OutputMode Output = OutputMode::Human;
        bool JsonRequested = false;
        bool JsonLinesRequested = false;
        std::set<std::string> Types;
        std::vector<std::string> Names;
        std::vector<std::string> Globs;
        bool All = false;
        bool DryRun = false;
        bool CWProbe = false;
        bool CWDeepProbe = false;
        bool CWMapData = false;
        bool CWRadiantBrushes = false;
        bool CWCaptureEntities = true;
        bool CWCapturePlacements = true;
        bool CWCaptureCollision = true;
        bool CWCaptureSplines = false;
        uint32_t Limit = 0;

        std::set<std::string> ModelFormats;
        std::set<std::string> AnimationFormats;
        std::string ImageFormat = "png";
        std::string SoundFormat = "wav";
        bool ModelFormatExplicit = false;
        bool AnimationFormatExplicit = false;
        bool ImageFormatExplicit = false;
        bool SoundFormatExplicit = false;

        bool AllLods = false;
        bool Hitbox = false;
        bool VertexColors = false;
        bool ModelImages = true;
        bool ImageNames = false;
        bool MaterialFolders = true;
        bool GlobalImages = false;
        bool PatchNormals = true;
        bool PatchColor = true;
        bool KeepSoundPath = true;
        bool SkipBlankAudio = false;
        bool Overwrite = false;
        bool ExportOptionsUsed = false;

    };

    struct FileState
    {
        uint64_t Size = 0;
        uint64_t Modified = 0;

        bool operator==(const FileState& Other) const
        {
            return Size == Other.Size && Modified == Other.Modified;
        }
    };

    using FileSnapshot = std::map<std::string, FileState>;

    std::ofstream CliLog;

    std::string Lower(std::string Value)
    {
        std::transform(Value.begin(), Value.end(), Value.begin(),
            [](unsigned char Character) { return (char)std::tolower(Character); });
        return Value;
    }

    bool WriteHandle(DWORD HandleId, const std::string& Text)
    {
        HANDLE Handle = GetStdHandle(HandleId);
        if (Handle == nullptr || Handle == INVALID_HANDLE_VALUE)
        {
            AttachConsole(ATTACH_PARENT_PROCESS);
            Handle = GetStdHandle(HandleId);
        }
        if (Handle == nullptr || Handle == INVALID_HANDLE_VALUE)
            return false;
        DWORD Written = 0;
        return WriteFile(Handle, Text.data(), (DWORD)Text.size(), &Written, nullptr) != FALSE;
    }

    void Stdout(const std::string& Text)
    {
        WriteHandle(STD_OUTPUT_HANDLE, Text);
    }

    void Diagnostic(const std::string& Text)
    {
        WriteHandle(STD_ERROR_HANDLE, Text + "\r\n");
        if (CliLog.is_open())
        {
            CliLog << Text << "\n";
            CliLog.flush();
        }
    }

    std::string TypeName(WraithAssetType Type)
    {
        switch (Type)
        {
        case WraithAssetType::Animation: return "animation";
        case WraithAssetType::Image: return "image";
        case WraithAssetType::Model: return "model";
        case WraithAssetType::Sound: return "sound";
        case WraithAssetType::Effect: return "effect";
        case WraithAssetType::RawFile: return "rawfile";
        case WraithAssetType::Material: return "material";
        case WraithAssetType::Terrain: return "terrain";
        case WraithAssetType::Custom: return "custom";
        default: return "unknown";
        }
    }

    bool IsExportable(WraithAssetType Type)
    {
        switch (Type)
        {
        case WraithAssetType::Animation:
        case WraithAssetType::Image:
        case WraithAssetType::Model:
        case WraithAssetType::Sound:
        case WraithAssetType::RawFile:
        case WraithAssetType::Material:
        case WraithAssetType::Terrain:
            return true;
        default:
            return false;
        }
    }

    std::string AssetStatusName(WraithAssetStatus Status)
    {
        switch (Status)
        {
        case WraithAssetStatus::Loaded: return "loaded";
        case WraithAssetStatus::Exported: return "exported";
        case WraithAssetStatus::NotLoaded: return "not_loaded";
        case WraithAssetStatus::Placeholder: return "placeholder";
        case WraithAssetStatus::Processing: return "processing";
        case WraithAssetStatus::Error: return "error";
        default: return "unknown";
        }
    }

    std::string GameName(SupportedGames Game)
    {
        switch (Game)
        {
        case SupportedGames::WorldAtWar: return "world_at_war";
        case SupportedGames::BlackOps: return "black_ops_1";
        case SupportedGames::BlackOps2: return "black_ops_2";
        case SupportedGames::BlackOps3: return "black_ops_3";
        case SupportedGames::BlackOps4: return "black_ops_4";
        case SupportedGames::BlackOpsCW: return "black_ops_cw";
        case SupportedGames::ModernWarfare: return "modern_warfare";
        case SupportedGames::ModernWarfare2: return "modern_warfare_2";
        case SupportedGames::ModernWarfare3: return "modern_warfare_3";
        case SupportedGames::ModernWarfare4: return "modern_warfare_4";
        case SupportedGames::ModernWarfare5: return "modern_warfare_5";
        case SupportedGames::ModernWarfare6: return "modern_warfare_6";
        case SupportedGames::QuantumSolace: return "quantum_of_solace";
        case SupportedGames::ModernWarfareRemastered: return "modern_warfare_remastered";
        case SupportedGames::ModernWarfare2Remastered: return "modern_warfare_2_remastered";
        case SupportedGames::Ghosts: return "ghosts";
        case SupportedGames::InfiniteWarfare: return "infinite_warfare";
        case SupportedGames::AdvancedWarfare: return "advanced_warfare";
        case SupportedGames::WorldWar2: return "world_war_2";
        case SupportedGames::Vanguard: return "vanguard";
        case SupportedGames::Parasyte: return "parasyte";
        default: return "none";
        }
    }

    bool WildcardMatch(const std::string& PatternValue, const std::string& TextValue)
    {
        const std::string Pattern = Lower(PatternValue);
        const std::string Text = Lower(TextValue);
        size_t PatternIndex = 0, TextIndex = 0;
        size_t Star = std::string::npos, Match = 0;
        while (TextIndex < Text.size())
        {
            if (PatternIndex < Pattern.size() &&
                (Pattern[PatternIndex] == '?' || Pattern[PatternIndex] == Text[TextIndex]))
            {
                PatternIndex++;
                TextIndex++;
            }
            else if (PatternIndex < Pattern.size() && Pattern[PatternIndex] == '*')
            {
                Star = PatternIndex++;
                Match = TextIndex;
            }
            else if (Star != std::string::npos)
            {
                PatternIndex = Star + 1;
                TextIndex = ++Match;
            }
            else
                return false;
        }
        while (PatternIndex < Pattern.size() && Pattern[PatternIndex] == '*')
            PatternIndex++;
        return PatternIndex == Pattern.size();
    }

    bool ValidType(const std::string& Value)
    {
        static const std::set<std::string> Types{
            "model", "animation", "image", "material", "sound", "rawfile",
            "terrain", "effect", "custom", "unknown" };
        return Types.find(Value) != Types.end();
    }

    bool ParseUnsigned(const char* Value, uint32_t& Result)
    {
        if (Value == nullptr || Value[0] == '\0' || Value[0] == '-')
            return false;
        char* End = nullptr;
        const unsigned long Parsed = strtoul(Value, &End, 10);
        if (End == Value || *End != '\0' || Parsed > UINT32_MAX)
            return false;
        Result = (uint32_t)Parsed;
        return true;
    }

    const char* NeedValue(int& Index, int argc, char** argv, std::string& Error)
    {
        if (Index + 1 >= argc)
        {
            Error = std::string(argv[Index]) + " requires a value";
            return nullptr;
        }
        return argv[++Index];
    }

    bool ParseOptions(int argc, char** argv, AssetOptions& Options, std::string& Error)
    {
        if (argc < 3)
        {
            Options.Action = "help";
            return true;
        }
        Options.Action = Lower(argv[2]);
        if (Options.Action == "--help" || Options.Action == "-h" || Options.Action == "help")
        {
            Options.Action = "help";
            return true;
        }
        if (Options.Action != "capabilities" && Options.Action != "list" &&
            Options.Action != "export")
        {
            Error = "unknown assets action '" + Options.Action + "'";
            return false;
        }

        for (int Index = 3; Index < argc; Index++)
        {
            const std::string Argument = Lower(argv[Index]);
            const char* Value = nullptr;
            if (Argument == "--json") { Options.Output = OutputMode::Json; Options.JsonRequested = true; }
            else if (Argument == "--jsonl") { Options.Output = OutputMode::JsonLines; Options.JsonLinesRequested = true; }
            else if (Argument == "--help" || Argument == "-h") Options.Action = "help";
            else if (Argument == "--type")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                const std::string Type = Lower(Value);
                if (!ValidType(Type)) { Error = "unsupported asset type '" + Type + "'"; return false; }
                Options.Types.insert(Type);
            }
            else if (Argument == "--name")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.Names.push_back(Value);
            }
            else if (Argument == "--glob")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.Globs.push_back(Value);
            }
            else if (Argument == "--all") Options.All = true;
            else if (Argument == "--dry-run") Options.DryRun = true;
            else if (Argument == "--cw-probe") Options.CWProbe = true;
            else if (Argument == "--cw-deep-probe") Options.CWProbe = Options.CWDeepProbe = true;
            else if (Argument == "--cw-radiant-brushes") { Options.CWRadiantBrushes=true; Options.CWMapData=true; }
            else if (Argument == "--cw-map-data") Options.CWMapData = true;
            else if (Argument == "--cw-skip-entities") Options.CWCaptureEntities = false;
            else if (Argument == "--cw-skip-placements") Options.CWCapturePlacements = false;
            else if (Argument == "--cw-splines") Options.CWCaptureSplines = true;
            else if (Argument == "--cw-skip-collision") Options.CWCaptureCollision = false;
            else if (Argument == "--limit")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                if (!ParseUnsigned(Value, Options.Limit) || Options.Limit == 0)
                { Error = "--limit must be a positive integer"; return false; }
            }
            else if (Argument == "--model-batch-root")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.ModelBatchRoot = Value; Options.ExportOptionsUsed = true;
            }
            else if (Argument == "--model-format")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.ModelFormats.insert(Lower(Value));
                Options.ModelFormatExplicit = Options.ExportOptionsUsed = true;
            }
            else if (Argument == "--animation-format")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.AnimationFormats.insert(Lower(Value));
                Options.AnimationFormatExplicit = Options.ExportOptionsUsed = true;
            }
            else if (Argument == "--image-format")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.ImageFormat = Lower(Value);
                Options.ImageFormatExplicit = Options.ExportOptionsUsed = true;
            }
            else if (Argument == "--sound-format")
            {
                Value = NeedValue(Index, argc, argv, Error); if (!Value) return false;
                Options.SoundFormat = Lower(Value);
                Options.SoundFormatExplicit = Options.ExportOptionsUsed = true;
            }
            else if (Argument == "--all-lods") { Options.AllLods = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--largest-lod") { Options.AllLods = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--hitbox") { Options.Hitbox = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--no-hitbox") { Options.Hitbox = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--vertex-colors") { Options.VertexColors = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--no-vertex-colors") { Options.VertexColors = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--model-images") { Options.ModelImages = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--no-model-images") { Options.ModelImages = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--image-names") { Options.ImageNames = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--no-image-names") { Options.ImageNames = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--material-folders") { Options.MaterialFolders = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--flat-materials") { Options.MaterialFolders = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--global-images") { Options.GlobalImages = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--local-images") { Options.GlobalImages = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--patch-normals") { Options.PatchNormals = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--no-patch-normals") { Options.PatchNormals = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--patch-color") { Options.PatchColor = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--no-patch-color") { Options.PatchColor = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--keep-sound-path") { Options.KeepSoundPath = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--flat-sound-path") { Options.KeepSoundPath = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--skip-blank-audio") { Options.SkipBlankAudio = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--include-blank-audio") { Options.SkipBlankAudio = false; Options.ExportOptionsUsed = true; }
            else if (Argument == "--overwrite") { Options.Overwrite = true; Options.ExportOptionsUsed = true; }
            else if (Argument == "--skip-existing") { Options.Overwrite = false; Options.ExportOptionsUsed = true; }
            else
            {
                Error = "unrecognised argument '" + std::string(argv[Index]) + "'";
                return false;
            }
        }
        return true;
    }

    bool Validate(AssetOptions& Options, std::string& Error)
    {
        if (Options.JsonRequested && Options.JsonLinesRequested)
        {
            Error = "--json and --jsonl are mutually exclusive";
            return false;
        }
        if (Options.Action == "capabilities")
        {
            if (!Options.Types.empty() || !Options.Names.empty() || !Options.Globs.empty() ||
                Options.All || Options.DryRun || Options.Limit != 0 || Options.ExportOptionsUsed)
            {
                Error = "capabilities accepts only --json or --jsonl";
                return false;
            }
            return true;
        }
        if (Options.Action == "list" && (Options.DryRun || Options.ExportOptionsUsed))
        {
            Error = "list accepts selection filters, --limit, and output options only";
            return false;
        }
        if (Options.Action == "export")
        {
            if (Options.Types.empty())
            {
                Error = "export requires at least one --type";
                return false;
            }
            if (!Options.All && Options.Names.empty() && Options.Globs.empty())
            {
                Error = "export requires --name, --glob, or explicit --all";
                return false;
            }
            if (Options.All && (!Options.Names.empty() || !Options.Globs.empty()))
            {
                Error = "--all cannot be combined with --name or --glob";
                return false;
            }
        }

        static const std::set<std::string> ModelFormats{
            "semodel", "gltf", "glb", "obj", "smd", "ma", "xna",
            "xmodel-export", "xmodel-bin", "cast" };
        static const std::set<std::string> AnimationFormats{
            "seanim", "xanim-v17", "xanim-v19", "cast" };
        static const std::set<std::string> ImageFormats{ "png", "dds", "tga", "tiff" };
        static const std::set<std::string> SoundFormats{ "wav", "flac" };
        for (const auto& Format : Options.ModelFormats)
            if (ModelFormats.find(Format) == ModelFormats.end())
            { Error = "unsupported model format '" + Format + "'"; return false; }
        for (const auto& Format : Options.AnimationFormats)
            if (AnimationFormats.find(Format) == AnimationFormats.end())
            { Error = "unsupported animation format '" + Format + "'"; return false; }
        if (ImageFormats.find(Options.ImageFormat) == ImageFormats.end())
        { Error = "unsupported image format '" + Options.ImageFormat + "'"; return false; }
        if (SoundFormats.find(Options.SoundFormat) == SoundFormats.end())
        { Error = "unsupported sound format '" + Options.SoundFormat + "'"; return false; }
        if (Options.AnimationFormats.count("xanim-v17") && Options.AnimationFormats.count("xanim-v19"))
        { Error = "xanim-v17 and xanim-v19 cannot be exported in the same run"; return false; }
        if (Options.ModelFormatExplicit && !Options.Types.count("model"))
        { Error = "--model-format requires --type model"; return false; }
        if (!Options.ModelBatchRoot.empty() && (Options.Action != "export" || Options.Types.size()!=1 || !Options.Types.count("model")))
        { Error = "--model-batch-root requires assets export --type model"; return false; }
        if (!Options.ModelBatchRoot.empty())
        {
            if (Options.ModelFormatExplicit && (Options.ModelFormats.size()!=1 || !Options.ModelFormats.count("cast")))
            { Error = "--model-batch-root supports Cold War CAST only"; return false; }
            Options.ModelFormats = {"cast"};
        }
        if (Options.AnimationFormatExplicit && !Options.Types.count("animation"))
        { Error = "--animation-format requires --type animation"; return false; }
        if (Options.SoundFormatExplicit && !Options.Types.count("sound"))
        { Error = "--sound-format requires --type sound"; return false; }
        if (Options.ImageFormatExplicit && !Options.Types.count("image") &&
            !Options.Types.count("model") && !Options.Types.count("material"))
        { Error = "--image-format requires image, model, or material assets"; return false; }
        if (Options.ModelFormats.empty()) Options.ModelFormats.insert("semodel");
        if (Options.AnimationFormats.empty()) Options.AnimationFormats.insert("seanim");
        return true;
    }

    json Capabilities()
    {
        return {
            {"schema", "greyhound-cli-capabilities-v1"},
            {"commands", {"assets capabilities", "assets list", "assets export", "superterrain"}},
            {"output_modes", {"human", "json", "jsonl"}},
            {"source_research", {
                {"mode", "source_data_only"}, {"new_session_per_export", true}, {"preview_mesh", false},
                {"manifest", "_source/research_capture.report.json"},
                {"evidence", "_source/capture/research/evidence.json"}, {"memory_access", "read_only"},
                {"additional_evidence_budget_bytes", 7297ull * 1024 * 1024},
                {"evidence_schema", "superterrain-source-evidence-v2"},
                {"readable_range_preflight", true}, {"isolated_budget_lanes", true},
                {"raw_package_retention", true}, {"indexed_small_records", true},
                {"capture_and_hash_progress", true},
                {"authored_splines", "unresolved; candidate bytes retained"},
                {"live_snapshot", "non_atomic; addresses valid only for their original process"}
            }},
            {"asset_types", json::array({
                {{"name", "model"}, {"exportable", true}},
                {{"name", "animation"}, {"exportable", true}},
                {{"name", "image"}, {"exportable", true}},
                {{"name", "material"}, {"exportable", true}},
                {{"name", "sound"}, {"exportable", true}},
                {{"name", "rawfile"}, {"exportable", true}},
                {{"name", "terrain"}, {"exportable", true}},
                {{"name", "effect"}, {"exportable", false}},
                {{"name", "custom"}, {"exportable", false}},
                {{"name", "unknown"}, {"exportable", false}}
            })},
            {"formats", {
                {"model", {"semodel", "gltf", "glb", "obj", "smd", "ma", "xna", "xmodel-export", "xmodel-bin", "cast"}},
                {"animation", {"seanim", "xanim-v17", "xanim-v19", "cast"}},
                {"image", {"png", "dds", "tga", "tiff"}},
                {"sound", {"wav", "flac"}}
            }},
            {"options", {
                {"selection", {"--type", "--name", "--glob", "--all", "--limit", "--dry-run"}},
                {"existing_files", {"--skip-existing", "--overwrite"}},
                {"model", {"--all-lods", "--largest-lod", "--hitbox", "--no-hitbox",
                    "--vertex-colors", "--no-vertex-colors", "--model-images", "--no-model-images",
                    "--image-names", "--no-image-names", "--material-folders", "--flat-materials",
                    "--global-images", "--local-images"}},
                {"image", {"--patch-normals", "--no-patch-normals", "--patch-color", "--no-patch-color"}},
                {"sound", {"--keep-sound-path", "--flat-sound-path", "--skip-blank-audio", "--include-blank-audio"}},
                {"terrain", json::array()}
            }},
            {"stable_defaults", {
                {"model_format", {"semodel"}}, {"animation_format", {"seanim"}},
                {"image_format", "png"}, {"sound_format", "wav"},
                {"lod", "largest"}, {"model_images", true},
                {"material_folders", true}, {"global_images", false},
                {"patch_normals", true}, {"patch_color", true},
                {"existing_files", "skip"}, {"terrain_export", "source_data_only"}
            }},
            {"selection", {
                {"exact", "repeat --name"}, {"glob", "repeat --glob"},
                {"bulk", "explicit --all"}, {"bulk_controls", {"--dry-run", "--limit"}}
            }},
            {"exit_codes", {{"success", 0}, {"usage", 1}, {"attach_failed", 2},
                {"no_matches", 3}, {"export_failed", 4}, {"terrain_finalization_failed", 5}}}
        };
    }

    std::string HelpText()
    {
        return
            "Greyhound agent asset CLI\r\n\r\n"
            "  Greyhound-cli.exe assets capabilities [--json|--jsonl]\r\n"
            "  Greyhound-cli.exe assets list [--type TYPE] [--name EXACT] [--glob PATTERN] [--limit N] [--json|--jsonl]\r\n"
            "  Greyhound-cli.exe assets export --type TYPE (--name EXACT|--glob PATTERN|--all) [options]\r\n\r\n"
            "Formats (repeat model/animation options to emit more than one):\r\n"
            "  --model-format semodel|gltf|glb|obj|smd|ma|xna|xmodel-export|xmodel-bin|cast\r\n"
            "  --model-batch-root PATH (Cold War CAST only; flat models/materials/images)\r\n"
            "  --animation-format seanim|xanim-v17|xanim-v19|cast\r\n"
            "  --image-format png|dds|tga|tiff   --sound-format wav|flac\r\n\r\n"
            "Controls:\r\n"
            "  --dry-run --limit N --overwrite|--skip-existing --all-lods|--largest-lod\r\n"
            "  --cw-probe (one-hop prefixes) --cw-deep-probe (bounded two-hop evidence graph)\r\n"
            "  --cw-splines (capture spline inputs; no deformed meshes)\r\n"
            "  --cw-skip-entities | --cw-skip-placements | --cw-skip-collision (omit typed sections)\r\n"
            "  --cw-radiant-brushes (verified CW brush prefab .map + metadata; bundled runtime)\r\n"
            "  --cw-map-data (supported map records and collision payloads with readback)\r\n"
            "  --hitbox --vertex-colors --model-images|--no-model-images --image-names\r\n"
            "  --material-folders|--flat-materials --global-images|--local-images\r\n"
            "  --patch-normals|--no-patch-normals --patch-color|--no-patch-color\r\n"
            "  --keep-sound-path|--flat-sound-path --skip-blank-audio|--include-blank-audio\r\n\r\n"
            "Terrain exports always write a complete source capture. Reconstruction is external.\r\n";
    }

    json OptionsJson(const AssetOptions& Options)
    {
        return {
            {"types", Options.Types}, {"names", Options.Names}, {"globs", Options.Globs},
            {"all", Options.All}, {"dry_run", Options.DryRun},
            {"cw_probe", Options.CWProbe}, {"cw_deep_probe", Options.CWDeepProbe},
            {"cw_map_data", Options.CWMapData}, {"cw_radiant_brushes", Options.CWRadiantBrushes},
            {"cw_capture_entities", Options.CWCaptureEntities},
            {"cw_capture_placements", Options.CWCapturePlacements},
            {"cw_capture_collision", Options.CWCaptureCollision},
            {"limit", Options.Limit == 0 ? json(nullptr) : json(Options.Limit)},
            {"model_formats", Options.ModelFormats},
            {"animation_formats", Options.AnimationFormats},
            {"image_format", Options.ImageFormat}, {"sound_format", Options.SoundFormat},
            {"all_lods", Options.AllLods}, {"hitbox", Options.Hitbox},
            {"vertex_colors", Options.VertexColors}, {"model_images", Options.ModelImages},
            {"image_names", Options.ImageNames}, {"material_folders", Options.MaterialFolders},
            {"model_batch_root",Options.ModelBatchRoot},
            {"global_images", Options.GlobalImages}, {"patch_normals", Options.PatchNormals},
            {"patch_color", Options.PatchColor}, {"keep_sound_path", Options.KeepSoundPath},
            {"skip_blank_audio", Options.SkipBlankAudio},
            {"existing_files", Options.Overwrite ? "overwrite" : "skip"},
            {"terrain", {{"mode", "source_data_only"}}}
        };
    }

    json SelectorsJson(const AssetOptions& Options)
    {
        json Names = json::array();
        json Globs = json::array();
        for (const auto& Name : Options.Names) Names.push_back(Lower(Name));
        for (const auto& Glob : Options.Globs) Globs.push_back(Lower(Glob));
        return { {"types", Options.Types}, {"exact_names", Names}, {"globs", Globs},
            {"all", Options.All},
            {"limit", Options.Limit == 0 ? json(nullptr) : json(Options.Limit)} };
    }

    void SetBool(const char* Key, bool Value)
    {
        SettingsManager::SetSetting(Key, Value ? "true" : "false");
    }

    void EnableAllAssetDiscovery()
    {
        // Greyhound's GUI visibility preferences are consulted while loading
        // pools. A headless inventory must not inherit the historical defaults
        // that hide images, materials, sounds, effects, and raw files.
        const char* VisibilityKeys[] = { "showxmodel", "showxanim", "showximage",
            "showxmtl", "showxsounds", "showxrawfiles", "showefx", "showxterrain",
            "showcwcollision", "showcwworld", "showcwnav", "showcwfx",
            "showcwentities", "showcwtriggers", "showcwai" };
        for (const auto Key : VisibilityKeys)
            SetBool(Key, true);
    }

    bool ApplyExportSettings(AssetOptions& Options, std::string& Error)
    {
        const char* ModelKeys[] = { "export_semodel", "export_gltf", "export_glb",
            "export_obj", "export_smd", "export_ma", "export_xna", "export_xmexport",
            "export_xmbin", "export_castmdl" };
        for (const auto Key : ModelKeys) SetBool(Key, false);
        const std::map<std::string, const char*> ModelSettings{
            {"semodel", "export_semodel"}, {"gltf", "export_gltf"}, {"glb", "export_glb"},
            {"obj", "export_obj"}, {"smd", "export_smd"}, {"ma", "export_ma"},
            {"xna", "export_xna"}, {"xmodel-export", "export_xmexport"},
            {"xmodel-bin", "export_xmbin"}, {"cast", "export_castmdl"} };
        for (const auto& Format : Options.ModelFormats) SetBool(ModelSettings.at(Format), true);

        SetBool("export_seanim", Options.AnimationFormats.count("seanim") != 0);
        SetBool("export_castanim", Options.AnimationFormats.count("cast") != 0);
        const bool DirectX = Options.AnimationFormats.count("xanim-v17") ||
            Options.AnimationFormats.count("xanim-v19");
        SetBool("export_directxanim", DirectX);
        SettingsManager::SetSetting("directxanim_ver",
            Options.AnimationFormats.count("xanim-v19") ? "19" : "17");

        SettingsManager::SetSetting("exportimg", Lower(Options.ImageFormat) == "tiff" ?
            "TIFF" : (Lower(Options.ImageFormat) == "tga" ? "TGA" :
            (Lower(Options.ImageFormat) == "dds" ? "DDS" : "PNG")));
        SettingsManager::SetSetting("exportsnd", Options.SoundFormat == "flac" ? "FLAC" : "WAV");
        SetBool("exportalllods", Options.AllLods);
        SetBool("exporthitbox", Options.Hitbox);
        SetBool("exportvtxcolor", Options.VertexColors);
        SetBool("exportmodelimg", Options.ModelImages);
        SetBool("exportimgnames", Options.ImageNames);
        SetBool("mdlmtlfolders", Options.MaterialFolders);
        SetBool("global_images", Options.GlobalImages);
        SetBool("patchnormals", Options.PatchNormals);
        SetBool("patchcolor", Options.PatchColor);
        SetBool("keepsndpath", Options.KeepSoundPath);
        SetBool("skipblankaudio", Options.SkipBlankAudio);
        SetBool("skipprevmodel", !Options.Overwrite);
        SetBool("skipprevanim", !Options.Overwrite);
        SetBool("skipprevimg", !Options.Overwrite);
        SetBool("skipprevsound", !Options.Overwrite);
        SetBool("skipprevterrain", !Options.Overwrite);

        return true;
    }

    bool Matches(const CoDAsset_t* Asset, const AssetOptions& Options)
    {
        if (Asset == nullptr)
            return false;
        const std::string Type = TypeName(Asset->AssetType);
        if (!Options.Types.empty() && !Options.Types.count(Type))
            return false;
        if (Options.All || (Options.Names.empty() && Options.Globs.empty()))
            return true;
        const std::string Name = Lower(Asset->AssetName);
        for (const auto& Exact : Options.Names)
            if (Name == Lower(Exact)) return true;
        for (const auto& Glob : Options.Globs)
            if (WildcardMatch(Glob, Asset->AssetName)) return true;
        return false;
    }

    std::vector<CoDAsset_t*> SelectAssets(const AssetOptions& Options)
    {
        std::vector<CoDAsset_t*> Result;
        if (CoDAssets::GameAssets != nullptr)
        {
            for (auto Asset : CoDAssets::GameAssets->LoadedAssets)
                if (Matches(Asset, Options)) Result.push_back(Asset);
        }
        std::stable_sort(Result.begin(), Result.end(), [](const CoDAsset_t* Left, const CoDAsset_t* Right)
        {
            const std::string LeftType = TypeName(Left->AssetType);
            const std::string RightType = TypeName(Right->AssetType);
            if (LeftType != RightType) return LeftType < RightType;
            const std::string LeftName = Lower(Left->AssetName);
            const std::string RightName = Lower(Right->AssetName);
            if (LeftName != RightName) return LeftName < RightName;
            return Left->AssetPointer < Right->AssetPointer;
        });
        if (Options.Limit > 0 && Result.size() > Options.Limit)
            Result.resize(Options.Limit);
        return Result;
    }

    json AssetDescription(const CoDAsset_t* Asset)
    {
        const std::string Type = TypeName(Asset->AssetType);
        return {
            {"id", Type + ":" + Asset->AssetName}, {"type", Type},
            {"name", Asset->AssetName}, {"exportable", IsExportable(Asset->AssetType)},
            {"loaded_status", AssetStatusName(Asset->AssetStatus)},
            {"size", Asset->AssetSize < 0 ? json(nullptr) : json(Asset->AssetSize)},
            {"streamed", Asset->Streamed}
        };
    }

    uint64_t FileTimeValue(const FILETIME& Value)
    {
        ULARGE_INTEGER Result{};
        Result.LowPart = Value.dwLowDateTime;
        Result.HighPart = Value.dwHighDateTime;
        return Result.QuadPart;
    }

    void SnapshotDirectory(const std::string& Root, const std::string& Relative, FileSnapshot& Result)
    {
        const std::string Directory = Relative.empty() ? Root : FileSystems::CombinePath(Root, Relative);
        WIN32_FIND_DATAA Data{};
        HANDLE Search = FindFirstFileA(FileSystems::CombinePath(Directory, "*").c_str(), &Data);
        if (Search == INVALID_HANDLE_VALUE)
            return;
        do
        {
            const std::string Name = Data.cFileName;
            if (Name == "." || Name == "..") continue;
            const std::string Child = Relative.empty() ? Name : FileSystems::CombinePath(Relative, Name);
            if (Data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
                SnapshotDirectory(Root, Child, Result);
            else
            {
                ULARGE_INTEGER Size{};
                Size.LowPart = Data.nFileSizeLow;
                Size.HighPart = Data.nFileSizeHigh;
                Result[Child] = { Size.QuadPart, FileTimeValue(Data.ftLastWriteTime) };
            }
        } while (FindNextFileA(Search, &Data));
        FindClose(Search);
    }

    FileSnapshot Snapshot(const std::string& Root)
    {
        FileSnapshot Result;
        SnapshotDirectory(Root, "", Result);
        return Result;
    }

    json FilesJson(const FileSnapshot& Files)
    {
        json Result = json::array();
        for (const auto& Entry : Files)
            Result.push_back({ {"path", Entry.first}, {"size", Entry.second.Size} });
        return Result;
    }

    std::string RunId()
    {
        SYSTEMTIME Time{};
        GetSystemTime(&Time);
        return Strings::Format("%04u%02u%02uT%02u%02u%02u.%03uZ-%lu",
            Time.wYear, Time.wMonth, Time.wDay, Time.wHour, Time.wMinute,
            Time.wSecond, Time.wMilliseconds, GetCurrentProcessId());
    }

    std::string WriteManifest(const json& Result, const std::string& Id)
    {
        const auto Root = FileSystems::CombinePath(
            FileSystems::GetApplicationPath(), "exported_files\\_manifests");
        FileSystems::CreateDirectory(Root);
        const auto Path = FileSystems::CombinePath(Root, Id + ".json");
        std::ofstream Output(Path, std::ios::binary | std::ios::trunc);
        if (!Output) return "";
        Output << Result.dump(2) << "\n";
        return Path;
    }

    void Emit(const AssetOptions& Options, const json& Result)
    {
        if (Options.Output == OutputMode::Json)
            Stdout(Result.dump() + "\r\n");
        else if (Options.Output == OutputMode::JsonLines)
        {
            if (Result.contains("assets"))
            {
                json Start = Result;
                Start.erase("assets");
                Start["event"] = "start";
                Stdout(Start.dump() + "\r\n");
                for (const auto& Asset : Result["assets"])
                    Stdout(json({{"schema", "greyhound-cli-event-v1"}, {"event", "asset"}, {"asset", Asset}}).dump() + "\r\n");
                Stdout(json({{"schema", "greyhound-cli-event-v1"}, {"event", "summary"},
                    {"counts", Result.value("counts", json::object())},
                    {"manifest", Result.value("manifest", json(nullptr))},
                    {"exit_code", Result.value("exit_code", 0)}}).dump() + "\r\n");
            }
            else
                Stdout(Result.dump() + "\r\n");
        }
        else
        {
            if (Result.contains("assets"))
            {
                for (const auto& Asset : Result["assets"])
                {
                    Stdout(Asset.value("status", Asset.value("loaded_status", "loaded")) +
                        "  " + Asset.value("type", "unknown") + ":" + Asset.value("name", "") + "\r\n");
                }
                if (Result.contains("manifest") && !Result["manifest"].is_null())
                    Stdout("manifest  " + Result["manifest"].get<std::string>() + "\r\n");
            }
            else
                Stdout(Result.dump(2) + "\r\n");
        }
    }

    void EmitJsonLine(const json& Event)
    {
        Stdout(Event.dump() + "\r\n");
    }

    void AppendAssetResult(json& Result, const AssetOptions& Options, const json& Record)
    {
        Result["assets"].push_back(Record);
        if (Options.Output == OutputMode::JsonLines)
            EmitJsonLine({ {"schema", "greyhound-cli-event-v1"},
                {"event", "asset"}, {"asset", Record} });
    }

    int EmitError(const AssetOptions& Options, const std::string& Message, int ExitCode)
    {
        json Error = { {"schema", "greyhound-cli-error-v1"}, {"event", "error"},
            {"error", Message}, {"exit_code", ExitCode} };
        if (Options.Output == OutputMode::Human)
            WriteHandle(STD_ERROR_HANDLE, "error: " + Message + "\r\n");
        else
            Stdout(Error.dump() + "\r\n");
        return ExitCode;
    }
}

int AssetCli::Run(int argc, char** argv)
{
    AssetOptions Options;
    // Determine the requested output channel before parsing so usage errors are
    // machine-readable even when the bad argument appears before --json.
    for (int Index = 2; Index < argc; Index++)
    {
        if (_stricmp(argv[Index], "--json") == 0)
        { Options.Output = OutputMode::Json; Options.JsonRequested = true; }
        if (_stricmp(argv[Index], "--jsonl") == 0)
        { Options.Output = OutputMode::JsonLines; Options.JsonLinesRequested = true; }
    }

    const auto LogPath = FileSystems::CombinePath(
        FileSystems::GetApplicationPath(), "assets_cli.log");
    CliLog.open(LogPath, std::ios::out | std::ios::trunc);

    std::string Error;
    if (!ParseOptions(argc, argv, Options, Error) || !Validate(Options, Error))
        return EmitError(Options, Error, 1);
    if (Options.Action == "help")
    {
        Stdout(HelpText());
        return 0;
    }
    if (Options.Action == "capabilities")
    {
        const json Result = Capabilities();
        if (Options.Output == OutputMode::Human)
            Stdout(Result.dump(2) + "\r\n");
        else
            Stdout(Result.dump() + "\r\n");
        return 0;
    }
    if (Options.Action == "export" && !ApplyExportSettings(Options, Error))
        return EmitError(Options, Error, 1);

    EnableAllAssetDiscovery();
    SetBool("cwprobepayloads", Options.CWProbe);
    SetBool("cwdeepProbe", Options.CWDeepProbe);
    SetBool("cwmapdata", Options.CWMapData);
    SetBool("cwradiantbrushes", Options.CWRadiantBrushes);
    SetBool("cwcaptureentities", Options.CWCaptureEntities);
    SetBool("cwcaptureplacements", Options.CWCapturePlacements);
    SetBool("cwcapturecollision", Options.CWCaptureCollision);
    SetBool("cwcapturesplines", Options.CWCaptureSplines);

    Diagnostic("attaching to a supported game");
    const auto Found = CoDAssets::BeginGameMode();
    if (Found != FindGameResult::Success)
        return EmitError(Options, "could not attach to a supported running game", 2);

    const std::string Id = RunId();
    json Result = {
        {"schema", "greyhound-cli-result-v1"}, {"run_id", Id},
        {"command", "assets " + Options.Action}, {"game", GameName(CoDAssets::GameID)},
        {"selectors", SelectorsJson(Options)},
        {"effective_options", OptionsJson(Options)}, {"assets", json::array()}
    };
    auto Selected = SelectAssets(Options);
    if (Selected.empty())
    {
        CoDAssets::CleanUpGame();
        return EmitError(Options, "no loaded assets matched the selection", 3);
    }

    if (Options.Output == OutputMode::JsonLines)
    {
        json Start = Result;
        Start.erase("assets");
        Start["schema"] = "greyhound-cli-event-v1";
        Start["event"] = "start";
        Start["matched"] = Selected.size();
        EmitJsonLine(Start);
    }

    int Exported = 0, Planned = 0, Skipped = 0, Failed = 0, Unsupported = 0;
    bool TerrainPostProcessFailed = false;
    for (auto Asset : Selected)
    {
        json Record = AssetDescription(Asset);
        if (Options.Action == "list")
        {
            Record["status"] = IsExportable(Asset->AssetType) ? "loaded" : "unsupported";
            AppendAssetResult(Result, Options, Record);
            continue;
        }

        const std::string OutputPath = Options.ModelBatchRoot.empty() ? CoDAssets::GetExportPath(Asset) : Options.ModelBatchRoot;
        Record["output_directory"] = OutputPath;
        if (!IsExportable(Asset->AssetType))
        {
            Record["status"] = "unsupported";
            Record["error"] = "Greyhound has no exporter for this asset type";
            Unsupported++;
            AppendAssetResult(Result, Options, Record);
            continue;
        }
        if (Options.DryRun)
        {
            Record["status"] = "planned";
            Record["generated_files"] = json::array();
            Planned++;
            AppendAssetResult(Result, Options, Record);
            continue;
        }

        Diagnostic("exporting " + TypeName(Asset->AssetType) + ":" + Asset->AssetName);
        const auto Before = Snapshot(OutputPath);
        const auto Started = std::chrono::steady_clock::now();
        auto ExportResult = ExportGameResult::UnknownError;
        try
        {
            ExportResult = Options.ModelBatchRoot.empty() ? CoDAssets::ExportAsset(Asset) :
                CoDAssets::ExportJsonBatchModel(static_cast<const CoDModel_t*>(Asset), Options.ModelBatchRoot);
        }
        catch (const std::exception& E) { Record["error"] = E.what(); Diagnostic(E.what()); }
        const auto Milliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - Started).count();
        const auto ActualPath = CoDAssets::LatestExportPath.empty() ? OutputPath : CoDAssets::LatestExportPath;
        Record["output_directory"] = ActualPath;
        const auto After = Snapshot(ActualPath);
        Record["duration_ms"] = Milliseconds;
        Record["generated_files"] = FilesJson(After);
        if (ExportResult == ExportGameResult::Success)
        {
            if (!Options.Overwrite && ActualPath == OutputPath && !After.empty() && Before == After)
            {
                Record["status"] = "skipped";
                Skipped++;
            }
            else
            {
                Record["status"] = "exported";
                Exported++;
            }
        }
        else
        {
            Record["status"] = "failed";
            if (!Record.contains("error")) Record["error"] = ExportResult == ExportGameResult::Placeholder ?
                "asset is a placeholder" : "asset exporter returned an error";
            Failed++;
            if (Asset->AssetType == WraithAssetType::Terrain &&
                CoDAssets::LatestTerrainFinalizationFailed)
                TerrainPostProcessFailed = true;
        }
        AppendAssetResult(Result, Options, Record);
    }

    CoDAssets::CleanUpGame();
    Result["counts"] = { {"matched", Selected.size()}, {"exported", Exported},
        {"planned", Planned}, {"skipped", Skipped}, {"failed", Failed},
        {"unsupported", Unsupported} };
    int ExitCode = 0;
    if (TerrainPostProcessFailed) ExitCode = 5;
    else if (Failed > 0 || Unsupported > 0) ExitCode = 4;
    Result["exit_code"] = ExitCode;
    Result["manifest"] = nullptr;
    const std::string Manifest = WriteManifest(Result, Id);
    if (!Manifest.empty())
    {
        Result["manifest"] = Manifest;
        // Rewrite once so the file contains its own final location.
        WriteManifest(Result, Id);
    }
    if (Options.Output == OutputMode::JsonLines)
    {
        EmitJsonLine({ {"schema", "greyhound-cli-event-v1"}, {"event", "summary"},
            {"counts", Result["counts"]}, {"manifest", Result["manifest"]},
            {"exit_code", ExitCode} });
    }
    else
        Emit(Options, Result);
    return ExitCode;
}
