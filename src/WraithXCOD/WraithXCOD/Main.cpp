#include <conio.h>
#include <cstdarg>
#include <vector>
#include <stdio.h>
#include <memory>
#include <chrono>
#include <map>
#include <fstream>
#include <string>
#include <spdlog/async.h>
#include <spdlog/spdlog.h>
#include <spdlog/sinks/basic_file_sink.h>

// Wraith application and api (Must be included before additional includes)
#include "WraithApp.h"
#include "WraithWindow.h"
#include "WraithTheme.h"
#include "WraithX.h"
#include "Instance.h"
#include "WraithUpdate.h"

#include "MainWindow.h"

// The resource file
#include "resource.h"

// Settings manager
#include "SettingsManager.h"
#include "AssetCli.h"
#include "CoDAssets.h"
#include "GameBlackOpsCW.h"
#include "FileSystems.h"
#include "json.hpp"
#include <set>

// Debug Helper
#include <dbghelp.h>
#pragma comment(lib, "dbghelp.lib")

// Allow modern GUI controls
#pragma comment(linker,"/manifestdependency:\"type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")
// The WraithX App Instance
WraithApp WraithAppInstance;

// Handler for loading theme icons from resources
HICON LoadIconResource(WraithIconAssets AssetID)
{
    // Check the ID, if we have it, we can load it
    switch (AssetID)
    {
    case WraithIconAssets::ApplicationIcon:
        // Load the application icon
        return LoadIcon(GetModuleHandle(NULL), MAKEINTRESOURCE(IDI_MAINICON));
    case WraithIconAssets::ApplicationIconLarge:
        // Load the application icon large
        return (HICON)::LoadImage(GetModuleHandle(NULL), MAKEINTRESOURCE(IDI_MAINICON), IMAGE_ICON, 64, 64, LR_SHARED);
    case WraithIconAssets::CheckboxCheckedIcon:
        // Load the checkbox checked icon
        return LoadIcon(GetModuleHandle(NULL), MAKEINTRESOURCE(IDI_CHECKMARK));
    }
    // Failed
    return NULL;
}

// Handler for loading theme images from resources
Gdiplus::Bitmap* LoadImageResource(WraithImageAssets AssetID)
{
    // Check the ID, if we have it, we can load it
    CPngImage Image;
    // Temporary buffer for result
    CBitmap Result;

    // Check ID
    switch (AssetID)
    {
    case WraithImageAssets::SettingsNormalIcon:
        // Parse and load a PNG
        Image.Load(IDB_SETTINGSNORMAL, AfxGetInstanceHandle());
        // Converts the PNG object to a BITMAP
        Result.Attach(Image.Detach());
        // Return a GDI+ object
        return Gdiplus::Bitmap::FromHBITMAP((HBITMAP)Result, NULL);
    case WraithImageAssets::SettingsSelectedIcon:
        // Parse and load a PNG
        Image.Load(IDB_SETTINGSSELECT, AfxGetInstanceHandle());
        // Converts the PNG object to a BITMAP
        Result.Attach(Image.Detach());
        // Return a GDI+ object
        return Gdiplus::Bitmap::FromHBITMAP((HBITMAP)Result, NULL);
    case WraithImageAssets::SettingsHoverIcon:
        // Parse and load a PNG
        Image.Load(IDB_SETTINGSHOVER, AfxGetInstanceHandle());
        // Converts the PNG object to a BITMAP
        Result.Attach(Image.Detach());
        // Return a GDI+ object
        return Gdiplus::Bitmap::FromHBITMAP((HBITMAP)Result, NULL);
    }
    // Failed
    return nullptr;
}

// Cleanup old patch files before launch...
static void CleanupFilesystem()
{
    // Attempt to clean up the existing old files and folders
    auto CurrentPath = FileSystems::GetApplicationPath();

    // Attempt to delete the file
    FileSystems::DeleteFile(FileSystems::CombinePath(CurrentPath, "exhalelib.dll"));
    FileSystems::DeleteFile(FileSystems::CombinePath(CurrentPath, "latest_log.txt"));
    FileSystems::DeleteFile(FileSystems::CombinePath(CurrentPath, "settings.dat"));
    FileSystems::DeleteFile(FileSystems::CombinePath(CurrentPath, "Wraith.exe"));

    // Attempt to delete old cache
    FileSystems::DeleteDirectory(FileSystems::CombinePath(CurrentPath, "data"));
    // Attempt to delete old update cache
    FileSystems::DeleteDirectory(FileSystems::CombinePath(CurrentPath, "Temp"));
}

LONG WINAPI MyUnhandledExceptionFilter(EXCEPTION_POINTERS* ExceptionInfo)
{
    MessageBoxA(NULL, "Greyhound has encountered a fatal error and must close.\n\nA dump file will be written to where Greyhound's exe is located, please provide this and as much information as you can when reporting this crash.", "Greyhound", MB_OK | MB_ICONERROR);
    
    HANDLE hFile = CreateFile(
        L"crash_dump.dmp",
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_DELETE | FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    MINIDUMP_EXCEPTION_INFORMATION mei{};
    mei.ThreadId = GetCurrentThreadId();
    mei.ClientPointers = TRUE;
    mei.ExceptionPointers = ExceptionInfo;
    MiniDumpWriteDump(
        GetCurrentProcess(),
        GetCurrentProcessId(),
        hFile,
        MiniDumpWithFullMemory,
        &mei,
        NULL,
        NULL);

    return EXCEPTION_EXECUTE_HANDLER;
}

// ---------------------------------------------------------------------------
// Headless SuperTerrain research export.
//
//     Greyhound.exe superterrain --list
//     Greyhound.exe superterrain --name <substring>
//     Greyhound.exe superterrain --all
//
// Attaches to the running game exactly like the GUI does, exports the matching
// TerrainGfx assets through the same CoDAssets::ExportAsset path, and exits.
// Progress goes to the attached console and to superterrain_cli.log beside the
// exe, because a Windows-subsystem process cannot rely on inherited stdout.
// ---------------------------------------------------------------------------
namespace
{
    FILE* CliLogFile = nullptr;

    void CliPrint(const char* Format, ...)
    {
        char Buffer[2048]{};
        va_list Arguments;
        va_start(Arguments, Format);
        vsnprintf(Buffer, sizeof(Buffer), Format, Arguments);
        va_end(Arguments);

        printf("%s\n", Buffer);
        fflush(stdout);

        if (CliLogFile != nullptr)
        {
            fprintf(CliLogFile, "%s\n", Buffer);
            fflush(CliLogFile);
        }
    }

    const char* FindGameResultText(FindGameResult Result)
    {
        switch (Result)
        {
        case FindGameResult::Success: return "success";
        case FindGameResult::NoGamesRunning: return "no supported game is running";
        case FindGameResult::FailedToLocateInfo: return "found the process but not its asset pools";
        default: return "unknown error";
        }
    }

    int RunSuperTerrainCli(int argc, char** argv)
    {
        if (AttachConsole(ATTACH_PARENT_PROCESS) == FALSE)
            AllocConsole();
        FILE* Redirected = nullptr;
        freopen_s(&Redirected, "CONOUT$", "w", stdout);

        auto LogPath = FileSystems::CombinePath(
            FileSystems::GetApplicationPath(), "superterrain_cli.log");
        fopen_s(&CliLogFile, LogPath.c_str(), "w");

        std::string Match;
        bool ListOnly = false;
        bool ListPools = false;
        uint32_t PoolLimit = 0xDC;
        std::vector<uint32_t> DumpPools;
        bool SweepPools = false;
        std::vector<uint64_t> PeekAddresses;
        uint32_t PeekBytes = 512;
        bool ExportAll = false;

        for (int i = 2; i < argc; i++)
        {
            if (strcmp(argv[i], "--list") == 0)
                ListOnly = true;
            else if (strcmp(argv[i], "--list-pools") == 0)
                ListPools = true;
            else if (strcmp(argv[i], "--pool-limit") == 0 && i + 1 < argc)
                PoolLimit = (uint32_t)strtoul(argv[++i], nullptr, 0);
            else if (strcmp(argv[i], "--peek") == 0 && i + 1 < argc)
                PeekAddresses.push_back(strtoull(argv[++i], nullptr, 0));
            else if (strcmp(argv[i], "--peek-bytes") == 0 && i + 1 < argc)
                PeekBytes = (uint32_t)strtoul(argv[++i], nullptr, 0);
            else if (strcmp(argv[i], "--sweep-pools") == 0)
                SweepPools = true;
            else if (strcmp(argv[i], "--dump-pool") == 0 && i + 1 < argc)
                DumpPools.push_back((uint32_t)strtoul(argv[++i], nullptr, 0));
            else if (strcmp(argv[i], "--all") == 0)
                ExportAll = true;
            else if (strcmp(argv[i], "--name") == 0 && i + 1 < argc)
                Match = argv[++i];
            else
            {
                CliPrint("unrecognised argument '%s'", argv[i]);
                return 1;
            }
        }

        // There is one terrain export mode: a complete source capture.
        CliPrint("mode: full source data only; reconstruction is external");

        if (PoolLimit > 0xDC || PeekBytes == 0 || PeekBytes > 16u * 1024u * 1024u ||
            std::any_of(DumpPools.begin(), DumpPools.end(), [](uint32_t P) { return P > 0xDC; }))
        {
            CliPrint("Research bounds: pools 0..0xDC; peeks 1..16777216 bytes.");
            return 1;
        }
        CliPrint("attaching to the game...");
        const auto Found = CoDAssets::BeginGameMode();
        if (Found != FindGameResult::Success)
        {
            CliPrint("attach failed: %s", FindGameResultText(Found));
            return 2;
        }

        std::vector<CoDAsset_t*> Terrains;
        if (CoDAssets::GameAssets != nullptr)
        {
            for (auto& Asset : CoDAssets::GameAssets->LoadedAssets)
            {
                if (Asset != nullptr && Asset->AssetType == WraithAssetType::Terrain)
                    Terrains.push_back(Asset);
            }
        }

        CliPrint("attached; %zu loaded assets, %zu terraingfx",
            CoDAssets::GameAssets != nullptr ? CoDAssets::GameAssets->LoadedAssets.size() : 0,
            Terrains.size());
        for (size_t i = 0; i < Terrains.size(); i++)
            CliPrint("  [%zu] %s", i, Terrains[i]->AssetName.c_str());

        std::string ResearchPath;
        nlohmann::json ResearchSession;
        const auto SaveResearchSession = [&]() {
            std::ofstream Out(FileSystems::CombinePath(ResearchPath, "session.json"), std::ios::binary);
            Out << ResearchSession.dump(2);
            return Out.good();
        };
        if (!PeekAddresses.empty() || SweepPools || !DumpPools.empty() || ListPools)
        {
            if (CoDAssets::GameID != SupportedGames::BlackOpsCW)
            {
                CliPrint("These memory research commands support Black Ops Cold War only.");
                CoDAssets::CleanUpGame(); return 2;
            }
            auto Root = FileSystems::CombinePath(FileSystems::GetApplicationPath(), "exported_files\\_research_sessions");
            FileSystems::CreateDirectory(Root);
            SYSTEMTIME T{}; GetSystemTime(&T);
            ResearchPath = FileSystems::CombinePath(Root, Strings::Format(
                "%04u%02u%02uT%02u%02u%02u_%03uZ_%lu_%llu", T.wYear, T.wMonth,
                T.wDay, T.wHour, T.wMinute, T.wSecond, T.wMilliseconds, GetCurrentProcessId(), GetTickCount64()));
            if (!CreateDirectoryA(ResearchPath.c_str(), nullptr))
            {
                CliPrint("Cannot create a NEW research session.");
                CoDAssets::CleanUpGame(); return 4;
            }
            ResearchSession = {{"schema", "superterrain-memory-session-v1"}, {"read_only", true},
                {"process_id", GetProcessId(CoDAssets::GameInstance->GetCurrentProcess())},
                {"module_base", Strings::Format("0x%llX", CoDAssets::GameInstance->GetMainModuleAddress())},
                {"process_path", CoDAssets::GameInstance->GetProcessPath()}, {"results", nlohmann::json::array()},
                {"scope", "bounded diagnostic reads; legacy pool sweeps are prefixes, not complete captures"}};
            SaveResearchSession();
            CliPrint("research session -> %s", ResearchPath.c_str());
        }
        if (!PeekAddresses.empty())
        {
            bool AllOk = true;
            std::set<uint64_t> Seen;
            for (const uint64_t Address : PeekAddresses)
            {
                if (!Seen.insert(Address).second) continue;
                const std::string Path = FileSystems::CombinePath(
                    ResearchPath,
                    Strings::Format("peek_%011llX.bin", Address));
                const bool Ok = GameBlackOpsCW::PeekMemory(Address, PeekBytes, Path);
                AllOk = AllOk && Ok;
                ResearchSession["results"].push_back({{"address", Strings::Format("0x%llX", Address)},
                    {"requested_bytes", PeekBytes}, {"file", Path}, {"complete", Ok}});
                // The first qword of an asset header is its name hash, and the
                // in-process dictionary covers far more names than any sampled
                // dump, so resolve it here rather than offline.
                const std::string Name = Ok
                    ? GameBlackOpsCW::ResolveNameHash(Address) : std::string();
                CliPrint("  peek 0x%llX -> %s %s", Address,
                    Ok ? Path.c_str() : "unreadable", Name.c_str());
            }
            AllOk = SaveResearchSession() && AllOk;
            CoDAssets::CleanUpGame();
            return AllOk ? 0 : 4;
        }

        if (SweepPools)
        {
            const std::string Sweep = GameBlackOpsCW::DumpAllPools(
                PoolLimit, ResearchPath);
            const std::string Path = FileSystems::CombinePath(
                ResearchPath, "pool_sweep.txt");
            std::ofstream Out(Path, std::ios::binary | std::ios::trunc);
            Out << Sweep;
            Out.close();
            ResearchSession["results"].push_back({{"operation", "sweep_pools"}, {"pool_limit", PoolLimit},
                {"file", Path}, {"report_written", Out.good()}, {"complete_pool_contents", false}});
            const bool Ok = SaveResearchSession() && Out.good();
            CliPrint("swept pools -> %s", Path.c_str());
            CoDAssets::CleanUpGame();
            return Ok ? 0 : 4;
        }

        if (!DumpPools.empty())
        {
            bool AllOk = true;
            std::set<uint32_t> Seen;
            for (const uint32_t PoolIndex : DumpPools)
            {
                if (!Seen.insert(PoolIndex).second) continue;
                const std::string DumpPath = FileSystems::CombinePath(
                    ResearchPath,
                    Strings::Format("pool_%03X.bin", PoolIndex));
                const bool Ok = GameBlackOpsCW::DumpAssetPool(
                    PoolIndex, DumpPath, 4096);
                AllOk = AllOk && Ok;
                ResearchSession["results"].push_back({{"operation", "dump_pool"}, {"pool", PoolIndex},
                    {"file", DumpPath}, {"legacy_header_limit", 4096}, {"export_call_succeeded", Ok}});
                CliPrint("  pool 0x%X -> %s", PoolIndex,
                    Ok ? DumpPath.c_str() : "unavailable");
                const std::string Arrays = GameBlackOpsCW::DumpAssetArrays(
                    PoolIndex, ResearchPath);
                if (!Arrays.empty())
                    CliPrint("%s", Arrays.c_str());
            }
            AllOk = SaveResearchSession() && AllOk;
            CoDAssets::CleanUpGame();
            return AllOk ? 0 : 4;
        }

        if (ListPools)
        {
            // Decals are composited over the terrain layers and carry the road
            // markings, but they are not part of the TerrainGfx asset and their
            // pool index is unknown.  Dump the whole pool directory so the
            // candidate pools can be identified by shape and name hash.
            const std::string Report =
                GameBlackOpsCW::DescribeAssetPools(PoolLimit);
            const std::string ReportPath = FileSystems::CombinePath(
                ResearchPath, "asset_pools.csv");
            std::ofstream Output(ReportPath, std::ios::binary | std::ios::trunc);
            Output << Report;
            Output.close();
            ResearchSession["results"].push_back({{"operation", "list_pools"}, {"pool_limit", PoolLimit},
                {"file", ReportPath}, {"report_written", Output.good()}});
            const bool Ok = SaveResearchSession() && Output.good();
            CliPrint("%s", Report.c_str());
            CliPrint("wrote %s", ReportPath.c_str());
            CoDAssets::CleanUpGame();
            return Ok ? 0 : 4;
        }

        if (ListOnly)
        {
            CoDAssets::CleanUpGame();
            return Terrains.empty() ? 3 : 0;
        }

        std::vector<CoDAsset_t*> Selected;
        for (auto& Terrain : Terrains)
        {
            if (ExportAll || (!Match.empty() && Terrain->AssetName.find(Match) != std::string::npos))
                Selected.push_back(Terrain);
        }

        if (Selected.empty())
        {
            CliPrint("nothing selected; pass --all or --name <substring>");
            CoDAssets::CleanUpGame();
            return 3;
        }

        int Failures = 0;
        bool TerrainFinalizationFailed = false;
        for (auto& Asset : Selected)
        {
            CliPrint("exporting %s ...", Asset->AssetName.c_str());
            const auto Started = std::chrono::steady_clock::now();
            const auto Result = CoDAssets::ExportAsset(Asset);
            const auto Seconds = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now() - Started).count();

            if (Result == ExportGameResult::Success)
            {
                CliPrint("  exported in %llds -> %s",
                    static_cast<long long>(Seconds), CoDAssets::LatestExportPath.c_str());
                CliPrint("  source capture organized and sealed");
            }
            else
            {
                Failures++;
                if (CoDAssets::LatestTerrainFinalizationFailed)
                    TerrainFinalizationFailed = true;
                CliPrint("  failed after %llds (%s)", static_cast<long long>(Seconds),
                    Result == ExportGameResult::Placeholder ? "placeholder" : "error");
            }
        }

        CoDAssets::CleanUpGame();
        CliPrint("done; %d terrain exports failed", Failures);
        if (TerrainFinalizationFailed)
            return 5;
        return Failures == 0 ? 0 : 4;
    }
}

// Main entry point of app
#ifdef _DEBUG
int main(int argc, char** argv)
#else
int APIENTRY WinMain(_In_ HINSTANCE hInstance, _In_opt_ HINSTANCE hPrevInstance, _In_ LPSTR lpCmdLine, _In_ int nCmdShow)
#endif
{
    // Assign filter before anything
    SetUnhandledExceptionFilter(MyUnhandledExceptionFilter);

    // Hook theme callbacks
    WraithTheme::OnLoadIconResource = LoadIconResource;
    WraithTheme::OnLoadImageResource = LoadImageResource;

    // Create Logger
    CoDAssets::Log = spdlog::basic_logger_mt<spdlog::async_factory>("HoundLogger", FileSystems::CombinePath(FileSystems::GetApplicationPath(), "TheHoundsLog.txt"));
    spdlog::flush_every(std::chrono::seconds(3));

    // Start the instance (We must provide the main window title, never include versions from now on)
    // auto CanContinue = Instance::BeginSingleInstance("Greyhound");

    // Only resume if we can
    // if (CanContinue)
    {
#ifndef _DEBUG
        int argc = __argc;
        char** argv = __argv;
#endif
        const bool HeadlessCommand = argc > 1 &&
            (strcmp(argv[1], "superterrain") == 0 || strcmp(argv[1], "assets") == 0);
        const std::map<std::string, std::string> DefaultSettings = {
            { "exportimg", "PNG" },
            { "exportsnd", "WAV" },
            { "keepsndpath", "true" },
            { "skipblankaudio", "false" },
            { "usesabindexbo4", "false" },
            { "sortbydetails", "false" },
            { "createxassetlog", "false" },
            { "exportmodelimg", "true" },
            { "exportalllods", "false" },
            { "exporthitbox", "false" },
            { "exportvtxcolor", "false" },
            { "exportimgnames", "false"},
            { "mdlmtlfolders", "true"},
            { "skipprevmodel", "true"},
            { "skipprevimg", "true"},
            { "skipprevsound", "true"},
            { "skipprevanim", "true"},
            { "export_ma", "false" },
            { "export_obj", "false" },
            { "export_xna", "false" },
            { "export_smd", "false" },
            { "export_xmexport", "false" },
            { "export_xmbin", "false" },
            { "export_seanim", "true" },
            { "export_semodel", "true" },
            { "export_castanim", "false" },
            { "export_castmdl", "false" },
            // { "export_fbx", "false" },
            { "export_gltf", "false" },
            { "export_glb", "false" },
            { "export_directxanim", "false" },
            { "directxanim_ver", "17" },
            { "global_images", "false" },
            { "patchnormals", "true" },
            { "patchcolor", "true" },
            { "showxanim", "true" },
            { "showxmodel", "true" },
            { "showximage", "false" },
            { "showefx", "false" },
            { "showxrawfiles", "false" },
            { "showxsounds", "false" },
            { "showxmtl", "false" },
            { "exportgdt_bo3", "true" },
            { "exportgdt_waw", "false" },
            { "cleargdt_exit", "true" },
            { "overwrite_gdt", "true" },
            { "cdn_downloader", "true" },
            { "match_game_lod_index", "false" },
            { "remove_mdl_basename", "false" }
        };
        if (HeadlessCommand)
            SettingsManager::LoadTransientSettings(DefaultSettings);
        else
            SettingsManager::LoadSettings("greyhound", DefaultSettings);

        // Handle CLI 
        for (int i = 0; i < argc; i++)
        {
            if (strcmp(argv[i], "verifiedhashes") == 0)
            {
                CoDAssets::VerifiedHashes = true;
            }
        }

        // Headless research export: no window, no update check, no message pump.
        if (argc > 1 && strcmp(argv[1], "superterrain") == 0)
        {
            if (!WraithX::InitializeAPI(true))
            {
                CliPrint("a fatal error occured while initializing Greyhound");
                return -1;
            }
            const int CliResult = RunSuperTerrainCli(argc, argv);
            WraithX::ShutdownAPI(true);
            return CliResult;
        }

        // General headless asset interface used by scripts and agentic tools.
        if (argc > 1 && strcmp(argv[1], "assets") == 0)
        {
            if (!WraithX::InitializeAPI(true))
                return 1;
            const int CliResult = AssetCli::Run(argc, argv);
            WraithX::ShutdownAPI(true);
            return CliResult;
        }

        // Clean up files
        CleanupFilesystem();
        // Check for updates
        WraithUpdate::CheckForUpdates("Scobalula", "Greyhound", "Greyhound", "greyhound.exe");

        // Initialize the API (This must be done BEFORE running a WraithApp)
        if (!WraithX::InitializeAPI(true))
        {
            // Failed to initialize
            MessageBoxA(NULL, "A fatal error occured while initializing Greyhound", "Greyhound", MB_OK | MB_ICONEXCLAMATION);
            // Failed
            return -1;
        }

        // Show the main window instance
        WraithAppInstance.RunApplication(MainWindow());

        // Tell the asset cache to clean up (Prevents crash on async cache loading)
        CoDAssets::CleanUpGame();

        // Shutdown the API, we're done
        WraithX::ShutdownAPI(true);

        // Stop the instance
        Instance::EndSingleInstance();
    }

    // We're done here
    return 0;
}
