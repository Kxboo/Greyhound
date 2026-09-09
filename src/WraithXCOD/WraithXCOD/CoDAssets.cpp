#include "stdafx.h"
#include "FlatMaterialExport.h"
#include "spdlog/spdlog.h"

// The class we are implementing
#include "CoDAssets.h"
#include "ModelBatchResume.h"

#include <cstring>
#include <fstream>
#include <functional>

// We need the following classes
#include "ProcessReader.h"
#include "Systems.h"
#include "FileSystems.h"
#include "Strings.h"
#include "Image.h"
#include "DirectXTex.h"
#include "Sound.h"
#include "BinaryReader.h"
#include "BinaryWriter.h"
#include "TextWriter.h"
#include "json.hpp"
#include "ModelExportNaming.h"

// Clean compiled-map names at the filesystem boundary, never in the asset pool.
static std::string ModelFileName(const std::string& Name)
{
    return ModelExportNaming::FileStem(Name);
}

// DirectX shader reflection is used by the TerrainGfx research exporter to
// recover the renderer resource layout that is otherwise absent from the
// serialized TerrainGfx object.
#include <wrl/client.h>
#include <d3d12.h>
#include <d3d12shader.h>
#include "dxc/Support/dxcapi.use.h"
#include "dxc/DxilContainer/DxilContainer.h"

// Owned and initialized by GameBlackOpsCW.cpp.
extern dxc::DxcDllSupport DXCDLLSupport;

// We need the CDN Downloaders
#include "CoDCDNDownloader.h"
#include "CoDCDNDownloaderV0.h"
#include "CoDCDNDownloaderV1.h"
#include "CoDCDNDownloaderV2.h"

// We need the main window for callbacks
#include "MainWindow.h"

// We need settings
#include "SettingsManager.h"

// We need the CoDTranslators
#include "CoDXAnimTranslator.h"
#include "CoDXModelTranslator.h"
#include "CoDRawfileTranslator.h"
#include "CoDXConverter.h"

// We need the game support functions
#include "GameWorldAtWar.h"
#include "GameBlackOps.h"
#include "GameBlackOps2.h"
#include "GameBlackOps3.h"
#include "GameBlackOps4.h"
#include "GameBlackOpsCW.h"
#include "GameModernWarfare.h"
#include "GameModernWarfare2.h"
#include "GameModernWarfare3.h"
#include "GameModernWarfare4.h"
#include "GameModernWarfare5.h"
#include "GameModernWarfare6.h"
#include "GameGhosts.h"
#include "GameAdvancedWarfare.h"
#include "GameModernWarfareRM.h"
#include "GameModernWarfare2RM.h"
#include "TerrainLayout.h"
#include "GameInfiniteWarfare.h"
#include "GameWorldWar2.h"
#include "GameQuantumSolace.h"
#include "GameVanguard.h"

namespace
{
    std::string QuoteTerrainArgument(const std::string& Value)
    {
        std::string Result = "\"";
        for (const char Character : Value)
            Result += Character == '\"' ? "\\\"" : std::string(1, Character);
        return Result + "\"";
    }

    int RunTerrainProcess(const std::vector<std::string>& Arguments,
        const std::string& ProgressFile,
        const std::function<void(uint32_t)>& ReportProgress)
    {
        if (Arguments.empty())
            return -1;

        std::string CommandLine;
        for (const auto& Argument : Arguments)
        {
            if (!CommandLine.empty())
                CommandLine += " ";
            CommandLine += QuoteTerrainArgument(Argument);
        }
        std::vector<char> MutableCommand(CommandLine.begin(), CommandLine.end());
        MutableCommand.push_back('\0');

        STARTUPINFOA Startup{};
        Startup.cb = sizeof(Startup);
        HANDLE OutputLog = INVALID_HANDLE_VALUE;
        if (!ProgressFile.empty())
        {
            SECURITY_ATTRIBUTES Security{};
            Security.nLength = sizeof(Security);
            Security.bInheritHandle = TRUE;
            const auto LogPath = FileSystems::CombinePath(
                FileSystems::GetDirectoryName(ProgressFile), "terrain_pipeline.log");
            OutputLog = CreateFileA(LogPath.c_str(), FILE_APPEND_DATA,
                FILE_SHARE_READ | FILE_SHARE_WRITE, &Security, OPEN_ALWAYS,
                FILE_ATTRIBUTE_NORMAL, nullptr);
            if (OutputLog != INVALID_HANDLE_VALUE)
            {
                SetFilePointer(OutputLog, 0, nullptr, FILE_END);
                Startup.dwFlags |= STARTF_USESTDHANDLES;
                Startup.hStdOutput = OutputLog;
                Startup.hStdError = OutputLog;
                Startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
            }
        }
        PROCESS_INFORMATION Process{};
        const auto WorkingDirectory = FileSystems::GetApplicationPath();
        const BOOL Started = CreateProcessA(nullptr, MutableCommand.data(),
            nullptr, nullptr, TRUE, CREATE_NO_WINDOW, nullptr,
            WorkingDirectory.c_str(), &Startup, &Process);
        if (OutputLog != INVALID_HANDLE_VALUE)
            CloseHandle(OutputLog);
        if (Started == FALSE)
            return -1;

        DWORD WaitResult = WAIT_TIMEOUT;
        while (WaitResult == WAIT_TIMEOUT)
        {
            WaitResult = WaitForSingleObject(Process.hProcess, 200);
            if (!ProgressFile.empty() && ReportProgress)
            {
                // Share delete access as well as read and write. The pipeline
                // publishes each tick by renaming a temporary file over this
                // one, and Windows refuses that rename while any handle is
                // open without FILE_SHARE_DELETE -- which is exactly what a
                // plain ifstream gives. That collision failed whole exports.
                const HANDLE Progress = CreateFileA(ProgressFile.c_str(),
                    GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
                if (Progress != INVALID_HANDLE_VALUE)
                {
                    char Buffer[16]{};
                    DWORD Read = 0;
                    if (ReadFile(Progress, Buffer, sizeof(Buffer) - 1, &Read, nullptr)
                        && Read > 0)
                    {
                        uint32_t Value = 0;
                        bool Digits = false;
                        for (DWORD i = 0; i < Read && Buffer[i] >= 0x30
                            && Buffer[i] <= 0x39; ++i)
                        {
                            Value = Value * 10 + (Buffer[i] - 0x30);
                            Digits = true;
                        }
                        if (Digits)
                            ReportProgress(std::min<uint32_t>(Value, 99));
                    }
                    CloseHandle(Progress);
                }
            }
        }
        DWORD ExitCode = 1;
        GetExitCodeProcess(Process.hProcess, &ExitCode);
        CloseHandle(Process.hThread);
        CloseHandle(Process.hProcess);
        return static_cast<int>(ExitCode);
    }

    int RunTerrainPython(const std::string& ScriptName,
        const std::vector<std::string>& ScriptArguments,
        const std::string& ProgressFile = std::string(),
        const std::function<void(uint32_t)>& ReportProgress = nullptr)
    {
        const auto ApplicationPath = FileSystems::GetApplicationPath();
        const auto Script = FileSystems::CombinePath(
            ApplicationPath, "tools\\" + ScriptName);
        if (!FileSystems::FileExists(Script))
            return -1;

        std::vector<std::string> PythonCandidates;
        char EnvironmentPython[32768]{};
        const DWORD EnvironmentLength = GetEnvironmentVariableA(
            "SUPERTERRAIN_PYTHON", EnvironmentPython, sizeof(EnvironmentPython));
        if (EnvironmentLength > 0 && EnvironmentLength < sizeof(EnvironmentPython))
            PythonCandidates.emplace_back(EnvironmentPython);

        const auto RuntimeFile = FileSystems::CombinePath(
            ApplicationPath, "terrain-python.txt");
        if (FileSystems::FileExists(RuntimeFile))
        {
            std::ifstream Runtime(RuntimeFile);
            std::string Python;
            std::getline(Runtime, Python);
            if (!Python.empty())
                PythonCandidates.push_back(Python);
        }
        PythonCandidates.push_back("python.exe");

        for (const auto& Python : PythonCandidates)
        {
            std::vector<std::string> Arguments{ Python, Script };
            Arguments.insert(Arguments.end(), ScriptArguments.begin(),
                ScriptArguments.end());
            const int Result = RunTerrainProcess(
                Arguments, ProgressFile, ReportProgress);
            if (Result != -1)
                return Result;
        }

        std::vector<std::string> Arguments{ "py.exe", "-3", Script };
        Arguments.insert(Arguments.end(), ScriptArguments.begin(),
            ScriptArguments.end());
        return RunTerrainProcess(Arguments, ProgressFile, ReportProgress);
    }

    bool FinishTerrainExport(const std::string& SourcePath,
        const std::string& LogPath,
        const std::function<void(uint32_t)>& ReportProgress)
    {
        if (ReportProgress)
            ReportProgress(35);

        // Greyhound owns source acquisition only. Put the native files beneath
        // capture/ without interpreting or rebuilding them; the independent
        // reconstruction tool consumes this directory after Greyhound exits.
        if (RunTerrainPython("organize_export.py", { SourcePath }) != 0)
        {
            CoDAssets::Log->error("Could not organize the terrain capture at {0}", SourcePath);
            return false;
        }
        if (GameBlackOpsCW::ExportTerrainDecals(SourcePath).empty())
            CoDAssets::Log->warn("No terrain decal placement array was found");
        if (ReportProgress)
            ReportProgress(42);

        const auto Progress = FileSystems::CombinePath(LogPath, "source_capture.progress");
        return RunTerrainPython("capture/finalize_research_capture.py",
            { SourcePath, "--progress-file", Progress }, Progress, ReportProgress) == 0;
    }
}

// We need the game cache functions
// TODO: Reorganise how packages are handled, merge into a "reader" class that handles
// everything rather than duplicated code and seperate code for Load File/Caches
#include "IWDCache.h"
#include "IPAKCache.h"
#include "PAKCache.h"
#include "XPAKCache.h"
#include "SABCache.h"
#include "XPTOCCache.h"
#include "XSUBCache.h"
#include "XSUBCacheV2.h"
#include "XSUBCacheV3.h"
#include "VGXPAKCache.h"

// We need the game support functions
#include "PAKSupport.h"
#include "XPAKSupport.h"
#include "IPAKSupport.h"
#include "IWDSupport.h"
#include "SABSupport.h"

// We need the export formats
#include "SEAnimExport.h"
#include "SEModelExport.h"
#include "MayaExport.h"
#include "XMEExport.h"
#include "XNALaraExport.h"
#include "ValveSMDExport.h"
#include "OBJExport.h"
#include "XAnimRawExport.h"
#include "FBXExport.h"
#include "XMBExport.h"
#include "GLTFExport.h"
#include "CastExport.h"

// TODO: Use image usage/semantic hashes to determine image types instead when reading from XMaterials

// -- Setup global variables

WraithNameIndex CoDAssets::AssetNameCache;
WraithNameIndex CoDAssets::StringCache;


// Set the default game instant pointer
std::unique_ptr<ProcessReader> CoDAssets::GameInstance = nullptr;
// Set the default logger pointer
std::unique_ptr<TextWriter> CoDAssets::XAssetLogWriter = nullptr;
// The main runtime log
std::shared_ptr<spdlog::logger> CoDAssets::Log = nullptr;

// Set the default game id
SupportedGames CoDAssets::GameID = SupportedGames::None;
// Set the default flags
SupportedGameFlags CoDAssets::GameFlags = SupportedGameFlags::None;
// Set the default verification
bool CoDAssets::VerifiedHashes = false;

// Set game offsets
std::vector<uint64_t> CoDAssets::GameOffsetInfos = std::vector<uint64_t>();
// Set game sizes
std::vector<uint32_t> CoDAssets::GamePoolSizes = std::vector<uint32_t>();

// Set loaded assets
std::unique_ptr<AssetPool> CoDAssets::GameAssets = nullptr;
// Set cache
std::unique_ptr<CoDPackageCache> CoDAssets::GamePackageCache = nullptr;
// Set cache
std::unique_ptr<CoDPackageCache> CoDAssets::OnDemandCache = nullptr;
// Set downloader
std::unique_ptr<CoDCDNDownloader> CoDAssets::CDNDownloader = nullptr;

// Set the image read handler
LoadXImageHandler CoDAssets::GameXImageHandler = nullptr;
// Set the string read handler
LoadStringHandler CoDAssets::GameStringHandler = nullptr;

// Setup the cod mutex
std::mutex CoDAssets::CodMutex;

// Setup counts
std::atomic<uint32_t> CoDAssets::ExportedAssetsCount;
std::atomic<uint32_t> CoDAssets::AssetsToExportCount;
std::atomic<bool> CoDAssets::CanExportContinue;

// Setup export callbacks
ExportProgressHandler CoDAssets::OnExportProgress = nullptr;
ExportStatusHandler CoDAssets::OnExportStatus = nullptr;

// Set last path
std::string CoDAssets::LatestExportPath = "";
bool CoDAssets::LatestTerrainFinalizationFailed = false;

// Set game directory
std::string CoDAssets::GameDirectory = "";

// Image Hashes from Black Ops 3's Techsets
std::map<uint32_t, std::string> SemanticHashes =
{
    { 0xA0AB1041, "colorMap" },
    { 0xB34B914B, "minimapMask" },
    { 0x369DEAC4, "colorMapSampler1" },
    { 0x12B6046F, "aberrationMask" },
    { 0xD90F4DC7, "gridTexture" },
    { 0x120E7A31, "uvOffsetTexture" },
    { 0x738502A8, "warpMap" },
    { 0x9E7BA008, "maskMap" },
    { 0x961141F1, "offsetMap" },
    { 0x4C094D3E, "irisTexture" },
    { 0x8FAE02B , "warpTexture" },
    { 0x1055275D, "lookupTexture" },
    { 0x7EF460A8, "blockNoiseTexture" },
    { 0x34D849D5, "revealMap" },
    { 0x264F0732, "diffuseMap" },
    { 0xE3C58D6C, "highlightMap" },
    { 0x56FF7ACA, "vignetteMap" },
    { 0x59D30D0F, "normalMap" },
    { 0xD78EC38E, "hexagonMap" },
    { 0x996BD23D, "irisMap" },
    { 0x2177C7B4, "lensFlareMap" },
    { 0x5A9A5201, "blurMaskMap" },
    { 0xDE799F3C, "warpMaskMap" },
    { 0xA6F70E30, "durdenMap" },
    { 0xF12B5F40, "pulseTexture" },
    { 0xE8515E3F, "distortionMask" },
    { 0xB1B4E3D7, "distortionMap" },
    { 0x665A1B6D, "scanlineMap" },
    { 0x29B553E1, "widgetMap1" },
    { 0x29B553E2, "widgetMap2" },
    { 0x29B553E3, "widgetMap3" },
    { 0x29B553E4, "widgetMap4" },
    { 0x29B553E5, "widgetMap5" },
    { 0x973D1967, "staticTexture" },
    { 0xA6DBAABD, "blurMask" },
    { 0x892E3B8B, "maskTexture" },
    { 0x50DA1DE9, "specHighlightMap" },
    { 0xCB13F18C, "normalTexture" },
    { 0xD5058185, "octogonMask" },
    { 0x6663034A, "noDamage" },
    { 0x4B87DB55, "lightDamage" },
    { 0xA9714557, "blockNoise" },
    { 0x7EAF2270, "lookup2" },
    { 0x69D4E61B, "spaceTexture" },
    { 0x75CD4B2 , "spaceAnusTexture" },
    { 0x9294363B, "pantherVagTexture" },
    { 0x6FB3CFCF, "lightningTexture" },
    { 0x7C86392D, "sparkleTexture" },
    { 0x3E013F6F, "faceTexture1" },
    { 0x3E013F6C, "faceTexture2" },
    { 0x369DEAC7, "colorMapSampler2" },
    { 0x369DEAC6, "colorMapSampler3" },
    { 0x9CD45BE1, "extraCamSampler" },
    { 0xFE195021, "noiseTexture" },
    { 0x3C19872 , "washTexture" },
    { 0x439044D6, "revealTexture" },
    { 0xEC84E459, "scubaTexture" },
    { 0xCDF5594E, "rivuletWarpTexture" },
    { 0x4E22BBB3, "rivuletRevealTexture" },
    { 0xF92FE655, "uvRevealTexture" },
    { 0x3FA0721A, "twinkleMap" },
    { 0x817A829B, "wormMap" },
    { 0x5BDF2D54, "distortionTexture" },
    { 0xB60D18E9, "colorMask" },
    { 0x77B50536, "bloodMotesMap" },
    { 0x389DD40F, "thermalHeatmap" },
    { 0x7176BF2 , "aoMap" },
    { 0x6D0A6C98, "glossMap" },
    { 0xE9817F0D, "glossMap" },
    { 0xEC443804, "specColorMap" },
    { 0x9A97E4B1, "customizeMask" },
    { 0xEB529B4D, "detailMap" },
    { 0x34614347, "emissiveMap" },
    { 0x95DF2A73, "detailNormal1" },
    { 0x95DF2A70, "detailNormal2" },
    { 0x95DF2A71, "detailNormal3" },
    { 0x95DF2A76, "detailNormal4" },
    { 0xD4A24996, "detailNormalMask" },
    { 0x53A3FCE2, "flickerLookupMap" },
    { 0xC089ABAF, "emissiveMask" },
    { 0x199A03D3, "tintMask" },
    { 0x2335512A, "thicknessMap" },
    { 0x55A604DC, "detailMap1" },
    { 0x55A604DF, "detailMap2" },
    { 0x80951342, "colorMapDetail2" },
    { 0x4429A80 , "mixMap" },
    { 0x4CDA7E01, "tintMask2" },
    { 0x56B697BB, "glossMapDetail2" },
    { 0x4ED66430, "specularMapDetail2" },
    { 0x338272BC, "alphaMaskMap" },
    { 0x6592A6E , "flowMap" },
    { 0x73502222, "noiseMap" },
    { 0xF79C1C0E, "rippleMap" },
    { 0x511B2AE1, "transitionDiffuse" },
    { 0x864EA29C, "transitionNormal" },
    { 0xF5276B0B, "transitionGloss" },
    { 0x5265433E, "sparkleDataMap" },
    { 0xA301628 , "alphaMap" },
    { 0xFB28D077, "image0" },
    { 0xFB28D076, "image1" },
    { 0xFB28D075, "image2" },
    { 0xFB28D074, "image3" },
    { 0xB598DFF4, "revealTextureB" },
    { 0x1CD5B065, "randomTextureA" },
    { 0x1CD5B066, "randomTextureB" },
    { 0x1CD5B067, "randomTextureC" },
    { 0x49F0DA7F, "distortMap" },
    { 0xFAF906C6, "gridTextureA" },
    { 0xFAF906C5, "gridTextureB" },
    { 0xFAF906C4, "gridTextureC" },
    { 0xFAF906C3, "gridTextureD" },
    { 0x1436343A, "heatLookup" },
    { 0xBE8B269C, "sceneLookup" },
    { 0xA60FE460, "uvOffsetDetailTexture" },
    { 0xB7A07713, "colorDetailTexture" },
    { 0xE625304 , "fireMap" },
    { 0xED590D65, "hudMap" },
    { 0x1EFD70AA, "colorRemapMap" },
    { 0xC67D666E, "shadowMaskMap" },
    { 0x81054C3A, "ditherMap" },
    { 0x5C800242, "smaaMap" },
    { 0x6FB66F22, "velveteenMask" },
    { 0xF7C2DB12, "tintBlendMask" },
    { 0x77151208, "camoMaskMap" },
    { 0xC0F0BF5F, "normalBodyMap" },
    { 0x1B768248, "glossBodyMap" },
    { 0xE86F76D9, "specColorMapThick" },
    { 0x6C246337, "underFfuseMap" },
    { 0xE57FFAA , "glossMap2" },
    { 0x1DE8CDAC, "cavityMap" },
    { 0xA41C9B9F, "styleMaskMap" },
    { 0xC80B7D0A, "colorSwatch1Map" },
    { 0xC807C8E9, "colorSwatch2Map" },
    { 0xBAEAD204, "normalSwatch1Map" },
    { 0xBAE92E67, "normalSwatch2Map" },
    { 0x656DD3F2, "specSwatch1Map" },
    { 0x656E3ED1, "specSwatch2Map" },
    { 0xE55690F3, "glossSwatch1Map" },
    { 0xE5583490, "glossSwatch2Map" },
    { 0xC089AC16, "emissiveMap1" },
    { 0xC089AC15, "emissiveMap2" },
    { 0xC089AC14, "emissiveMap3" },
    { 0x77B02241, "colorMap00" },
    { 0x4C596633, "flagRippleDetailMap" },
    { 0xD8BD9CD3, "decalMap" },
    { 0xA96FDB44, "crackMap" },
    { 0x39EC02D7, "crackNormalMap" },
    { 0x2BE9AF4 , "baseColorMap" },
    { 0x4CDA7E02, "tintMask1" },
    { 0x46FE0E6E, "baseTintMap" },
    { 0x55A604DE, "detailMap3" },
    { 0x80951343, "colorMapDetail3" },
    { 0x4E82BD61, "rColorRamp" },
    { 0xCCF4C850, "foamBase" },
    { 0xAE5C4C5 , "treadHeightMap" },
    { 0x50108D4D, "camoDetailMap" },
    { 0x8C22E816, "coneLUTMap" },
    { 0xFC80F332, "bentNormalMap" },
    { 0xA52C26B4, "specOcclusionMap" },
    { 0xC408965C, "stretchNormal" },
    { 0x6DFCC8D5, "compressNormal" },
    { 0x8F9CAD22, "cloudLayer0" },
    { 0xE566B555, "cloudMask0" },
    { 0x8F9CAD23, "cloudLayer1" },
    { 0xE566B554, "cloudMask1" },
    { 0x56B697BA, "glossMapDetail3" },
    { 0x4ED66431, "specularMapDetail3" },
    { 0x8C95EAB1, "mixMap1" },
    { 0xEE97A158, "clearcoatGlossMap" },
    { 0x8AD0A39B, "metalFlakeNormalMap" },
    { 0x2563EA9C, "metalFlakeMaskMap" },
    { 0x9783E4CD, "wobbleMap" },
    { 0xD6B59E75, "emissiveFlowMap" },
    { 0xCBF21CFB, "extracamTexture1" },
    { 0xCBF21CF8, "extracamTexture2" },
    { 0xCBF21CF9, "extracamTexture3" },
    { 0xCBF21CFE, "extracamTexture4" },
    { 0x8875EE6 , "breakUpMap" },
    { 0x74589F70, "diamondMask" },
    { 0x797F4F5C, "outlineMap" },
    { 0x5032DBE0, "alphaMask" },
    { 0x273482B9, "edgeFadeMap" },
    { 0xD28662DB, "specularMask" },
    { 0x64343DB8, "characterColorMap" },
    { 0xA7527356, "characterNormalMap" },
    { 0xE007460C, "characterRevealMap" },
    { 0x70DE0F82, "edgeColorMap" },
    { 0xDE36D64 , "edgeEmissiveMap" },
    { 0xC1EF31A8, "veinMap" },
    { 0x5E5425B9, "FutureMap" },
    { 0xA1712D0D, "ui3dSampler_C1_P0" },
    { 0xD2EEEEB8, "FontTextutre" },
    { 0x2A6C8C86, "OverlayMap" },
    { 0x85511979, "resolvedScene_C4_P0" },
    { 0x6F691B32, "codeTexture0_C3_P0" },
    { 0x6F645F19, "codeTexture0_C8_P0" },
    { 0x6F666E95, "codeTexture0_C4_P0" },
    { 0xCFED92EA, "Reveal_Map" },
    { 0xF039EC2D, "Diffuse_Map" },
    { 0xE98A255D, "AddMap" },
    { 0xB17777AC, "CompassMap" },
    { 0x3D4F14  , "Mask" },
    { 0x48FF11AE, "Diffuse" },
    { 0xF4E39943, "resolvedPostSun_C11_P0" },
    { 0x32F87F8 , "floatZSampler_C63_P0" },
    { 0x740FE37F, "fontCache" },
    { 0x1BB49   , "EKG" },
    { 0x8B4B7DF2, "resolvedPostSun_C1_P0" },
    { 0xBC83639B, "LightDamange" },
    { 0xF12FF2CE, "DpadTexture" },
    { 0x5F77D83E, "Noise_Texture" },
    { 0xF452E202, "Lookup" },
    { 0xE2AA34C0, "DayMap" },
    { 0x3D3E13  , "Mesh" },
    { 0x6519A44A, "heatmapSampler_C9_P0" },
    { 0x77F67259, "Overlay_Map" },
    { 0xAD1D0190, "Grain_Map" },
    { 0xFABDFA1A, "FadeMap" },
    { 0x6520EB80, "heatmapSampler_C3_P0" },
    { 0x9E2B786E, "C004_File" },
    { 0xAE7C5C1A, "HexagonPattern" },
    { 0xD657AB6E, "PlusTile" },
    { 0x44341ED2, "ScrollTexture" },
    { 0x3CEA479A, "sonarColorSampler_C1_P0" },
    { 0x589C508E, "ScrollTextureMap" },
    { 0x9D55EDBB, "GridTextureMap" },
    { 0x83F6B06F, "floatZSampler_C2_P0" },
    { 0x4969081A, "Static_Noise_Map" },
    { 0x8C128212, "LineMap" },
    { 0x855022BF, "resolvedScene_C2_P0" },
    { 0x7CF86BE , "Noise" },
    { 0xAC16CC94, "Wireframe" },
    { 0x79C6367 , "Image" },
    { 0xDF1738FD, "BackgroundGlow" },
    { 0x1E0097C9, "postEffect1_C4_P0" },
    { 0x1D23D48C, "postEffect0_C0_P0" },
    { 0x813B3FF , "Smoke" },
    { 0x942CBFF0, "Normal_Map" },
    { 0x55A04772, "Detail_Map" },
    { 0x8389EAF0, "PieChart" },
    { 0xE700765E, "LookupMap" },
    { 0xF5095EA4, "resolvedPostSun_C34_P0" },
    { 0x1D21496F, "postEffect0_C3_P0" },
    { 0xDE89DA4B, "TickMarkMaterial" },
    { 0x3E2C14  , "Tile" },
    { 0xA172C0E8, "ui3dSampler_C4_P0" },
    { 0x721D7116, "Vignette" },
    { 0x51CF2F85, "BlurredTexture" },
    { 0xC6CAE542, "ColorTexture" },
    { 0x82A61F22, "YUV_Image" },
    { 0x6F634657, "codeTexture0_C6_P0" },
    { 0x4E07583B, "transColorMap" },
    { 0xAB07D475, "transNormalMap" },
    { 0x9A8739AF, "transRevealMap" },
    { 0x1782DE2 , "transGlossMap" },
    { 0x95B48AE5, "meltRevealMap" },
    { 0x1DCB003F, "meltNormalMap" },
    { 0xB607C0FE, "Color_Map" },
    { 0x34ECCCB3, "specularMap" },
    { 0x6001F931, "occlusionMap" }
};

// -- Find game information

const std::vector<CoDGameProcess> CoDAssets::GameProcessInfo =
{
    // World at War
    { "codwaw.exe", SupportedGames::WorldAtWar, SupportedGameFlags::SP },
    { "codwawmp.exe", SupportedGames::WorldAtWar, SupportedGameFlags::MP },
    // Black Ops
    { "blackops.exe", SupportedGames::BlackOps, SupportedGameFlags::SP },
    { "blackopsmp.exe", SupportedGames::BlackOps, SupportedGameFlags::MP },
    // Black Ops 2
    { "t6zm.exe", SupportedGames::BlackOps2, SupportedGameFlags::ZM },
    { "t6mp.exe", SupportedGames::BlackOps2, SupportedGameFlags::MP },
    { "t6sp.exe", SupportedGames::BlackOps2, SupportedGameFlags::SP },
    // Black Ops 3
    { "blackops3.exe", SupportedGames::BlackOps3, SupportedGameFlags::SP },
    // Black Ops 4
    { "blackops4.exe", SupportedGames::BlackOps4, SupportedGameFlags::SP },
    // Black Ops CW
    { "blackopscoldwar.exe", SupportedGames::BlackOpsCW, SupportedGameFlags::SP },
    // Modern Warfare
    { "iw3sp.exe", SupportedGames::ModernWarfare, SupportedGameFlags::SP },
    { "iw3mp.exe", SupportedGames::ModernWarfare, SupportedGameFlags::MP },
    // Modern Warfare 2
    { "iw4sp.exe", SupportedGames::ModernWarfare2, SupportedGameFlags::SP },
    { "iw4mp.exe", SupportedGames::ModernWarfare2, SupportedGameFlags::MP },
    // Modern Warfare 3
    { "iw5sp.exe", SupportedGames::ModernWarfare3, SupportedGameFlags::SP },
    { "iw5mp.exe", SupportedGames::ModernWarfare3, SupportedGameFlags::MP },
    // Ghosts
    { "iw6sp64_ship.exe", SupportedGames::Ghosts, SupportedGameFlags::SP },
    { "iw6mp64_ship.exe", SupportedGames::Ghosts, SupportedGameFlags::MP },
    // Advanced Warfare
    { "s1_sp64_ship.exe", SupportedGames::AdvancedWarfare, SupportedGameFlags::SP },
    { "s1_mp64_ship.exe", SupportedGames::AdvancedWarfare, SupportedGameFlags::MP },
    // Modern Warfare Remastered
    { "h1_sp64_ship.exe", SupportedGames::ModernWarfareRemastered, SupportedGameFlags::SP },
    { "h1_mp64_ship.exe", SupportedGames::ModernWarfareRemastered, SupportedGameFlags::MP },
    // Infinite Warfare
    { "iw7_ship.exe", SupportedGames::InfiniteWarfare, SupportedGameFlags::SP },
    // World War II
    { "s2_sp64_ship.exe", SupportedGames::WorldWar2, SupportedGameFlags::SP },
    { "s2_mp64_ship.exe", SupportedGames::WorldWar2, SupportedGameFlags::MP },
    // Cordycep
    { "Cordycep.CLI.exe", SupportedGames::Parasyte, SupportedGameFlags::SP },
    // Modern Warfare 2 Remastered
    { "mw2cr.exe", SupportedGames::ModernWarfare2Remastered, SupportedGameFlags::SP },
    // 007 Quantum Solace
    { "jb_liveengine_s.exe", SupportedGames::QuantumSolace, SupportedGameFlags::SP },
};

// -- End find game database

FindGameResult CoDAssets::BeginGameMode()
{
    // Aquire a lock
    std::lock_guard<std::mutex> Lock(CodMutex);

    // Result
    auto Result = FindGameResult::Success;

    // Check if we have a game
    if (ps::state != nullptr || GameInstance == nullptr || !GameInstance->IsRunning())
    {
        // Load the game
        Result = FindGame();
    }

    // If success, load assets
    if (Result == FindGameResult::Success)
    {
        // Load assets, check for Parasyte
        if (ps::state != nullptr)
            LoadGamePS();
        else
            LoadGame();
    }
    else if (GameInstance != nullptr)
    {
        // Close out the game (Failed somehow)
        GameInstance.reset();
    }

    // Success unless failed
    return Result;
}

LoadGameFileResult CoDAssets::BeginGameFileMode(const std::string& FilePath)
{
    // Force clean up first, so we don't store redundant assets
    CoDAssets::CleanUpGame();

    // Aquire a lock
    std::lock_guard<std::mutex> Lock(CodMutex);

    // Result from load file
    return LoadFile(FilePath);
}

FindGameResult CoDAssets::FindGame()
{
    // Attempt to locate one of the supported games
    auto Processes = Systems::GetProcesses();
    // Clear Parasyte
    ps::state = nullptr;
    // Reset it
    GameInstance.reset();
    // Clear out existing offsets
    GameOffsetInfos.clear();
    // Clear out existing sizes
    GamePoolSizes.clear();

    // Loop and check
    for (auto& Process : Processes)
    {
        // Loop over game process info
        for (auto& GameInfo : GameProcessInfo)
        {
            // Compare name
            if (_stricmp(Process.ProcessName.c_str(), GameInfo.ProcessName) == 0)
            {
                // Make a new game instance
                GameInstance = std::make_unique<ProcessReader>();
                // Attempt to load
                if (GameInstance->Attach(Process.ProcessID))
                {
                    // Loaded set it up
                    GameID = GameInfo.GameID;
                    GameFlags = GameInfo.GameFlags;
                    // Attempt to locate game offsets
                    if (LocateGameInfo())
                    {
                        // Success
                        return FindGameResult::Success;
                    }
                    else
                    {
                        // Failed to locate
                        return FindGameResult::FailedToLocateInfo;
                    }
                }
            }
        }
    }

    // Reset
    if (GameInstance != nullptr)
    {
        // Clean up
        GameInstance.reset();
    }

    // Failed
    return FindGameResult::NoGamesRunning;
}

LoadGameResult CoDAssets::LoadGame()
{
    // Make sure the process is running
    if (GameInstance->IsRunning())
    {
        // Setup the assets
        GameAssets.reset(new AssetPool());
        // Whether or not we loaded assets
        bool Success = false;

        // Create log, if desired
        if (SettingsManager::GetSetting("createxassetlog", "false") == "true")
        {
            XAssetLogWriter = std::make_unique<TextWriter>();
            XAssetLogWriter->Open(FileSystems::CombinePath(FileSystems::GetApplicationPath(), "AssetLog.txt"));
        }

        // Load assets from the game
        switch (GameID)
        {
        case SupportedGames::QuantumSolace: Success = GameQuantumSolace::LoadAssets(); break;
        case SupportedGames::WorldAtWar: Success = GameWorldAtWar::LoadAssets(); break;
        case SupportedGames::BlackOps: Success = GameBlackOps::LoadAssets(); break;
        case SupportedGames::BlackOps2: Success = GameBlackOps2::LoadAssets(); break;
        case SupportedGames::BlackOps3: Success = GameBlackOps3::LoadAssets(); break;
        case SupportedGames::BlackOps4:
            // Allocate a new XPAK Mega Cache (Must reload CASC as the game can affect it if rerunning, etc. and result in corrupt exports)
            // TODO: Find a better solution to this, a good trigger for it to occur is relaunching the game, moving to different parts or Blizzard editing the CASC while
            // we have a handle, then try export an image, it'll probably come out black
            CleanupPackageCache();
            GamePackageCache = std::make_unique<XPAKCache>();
            // Set the XPAK path
            GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
            // Load as normally
            Success = GameBlackOps4::LoadAssets(); break;
        case SupportedGames::BlackOpsCW:
            // Allocate a new XPAK Mega Cache (Must reload CASC as the game can affect it if rerunning, etc. and result in corrupt exports)
            // TODO: Find a better solution to this, a good trigger for it to occur is relaunching the game, moving to different parts or Blizzard editing the CASC while
            // we have a handle, then try export an image, it'll probably come out black
            CleanupPackageCache();
            GamePackageCache = std::make_unique<XSUBCache>();
            // Set the XPAK path
            GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
            // Load as normally
            Success = GameBlackOpsCW::LoadAssets(); break;
        case SupportedGames::ModernWarfare: Success = GameModernWarfare::LoadAssets(); break;
        case SupportedGames::ModernWarfare2: Success = GameModernWarfare2::LoadAssets(); break;
        case SupportedGames::ModernWarfare3: Success = GameModernWarfare3::LoadAssets(); break;
        case SupportedGames::Ghosts: Success = GameGhosts::LoadAssets(); break;
        case SupportedGames::AdvancedWarfare: Success = GameAdvancedWarfare::LoadAssets(); break;
        case SupportedGames::ModernWarfareRemastered: Success = GameModernWarfareRM::LoadAssets(); break;
        case SupportedGames::ModernWarfare2Remastered: Success = GameModernWarfare2RM::LoadAssets(); break;
        case SupportedGames::InfiniteWarfare: Success = GameInfiniteWarfare::LoadAssets(); break;
        case SupportedGames::WorldWar2: Success = GameWorldWar2::LoadAssets(); break;
        }

        // Done with logger
        XAssetLogWriter = nullptr;

        // Result check
        if (Success)
        {
            // Sort the assets, for now we only support 2 modes, but this can be extended in the future.
            auto sortMethod = AssetCompareMethodHelper::CalculateCompareMethod(SettingsManager::GetSetting("assetsortmethod", "Name"));

            if (sortMethod != AssetCompareMethod::None)
            {
                std::stable_sort(GameAssets->LoadedAssets.begin(), GameAssets->LoadedAssets.end(), [sortMethod](const CoDAsset_t* lhs, const CoDAsset_t* rhs)
                {
                    return lhs->Compare(rhs, sortMethod);
                });
            }

            // Success
            return LoadGameResult::Success;
        }
        else
        {
            // Failed to load
            return LoadGameResult::NoAssetsFound;
        }
    }

    // Reset
    if (GameAssets != nullptr)
    {
        // Clean up
        GameAssets.reset();
    }

    // Failed
    return LoadGameResult::ProcessNotRunning;
}

LoadGameResult CoDAssets::LoadGamePS()
{
    // Make sure the process is running
    if (GameInstance->IsRunning())
    {
        // Setup the assets
        GameAssets.reset(new AssetPool());
        // Whether or not we loaded assets
        bool Success = false;

        // Create log, if desired
        if (SettingsManager::GetSetting("createxassetlog", "false") == "true")
        {
            XAssetLogWriter = std::make_unique<TextWriter>();
            XAssetLogWriter->Open(FileSystems::CombinePath(FileSystems::GetApplicationPath(), "AssetLog.txt"));
        }

        // Check for CDN support.
        const bool CDNSupport = SettingsManager::GetSetting("cdn_downloader", "false") == "true";

        // Cleanup
        CleanupPackageCache();

        // Load assets from the game
        switch (ps::state->GameID)
        {
        // Modern Warfare 2019
        case 0x3931524157444F4D:
            GameModernWarfare4::PerformInitialSetup();
            GameID            = SupportedGames::ModernWarfare4;
            GameFlags         = SupportedGameFlags::None;
            GameXImageHandler = GameModernWarfare4::LoadXImage;
            GameStringHandler = GameModernWarfare4::LoadStringEntry;
            GamePackageCache  = std::make_unique<XPAKCache>();
            OnDemandCache     = std::make_unique<XPAKCache>();
            CDNDownloader     = CDNSupport ? std::make_unique<CoDCDNDownloaderV0>() : nullptr;
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            OnDemandCache->LoadPackageCacheAsync(FileSystems::CombinePath(ps::state->GameDirectory, "xpak_cache"));
            Success = GameModernWarfare4::LoadAssets();
            break;
        // Vanguard
        case 0x44524155474E4156:
            GameVanguard::PerformInitialSetup();
            GameID            = SupportedGames::Vanguard;
            GameFlags         = SupportedGameFlags::None;
            GameXImageHandler = GameVanguard::LoadXImage;
            GameStringHandler = GameVanguard::LoadStringEntry;
            GamePackageCache  = std::make_unique<XSUBCacheV2>();
            OnDemandCache     = std::make_unique<VGXPAKCache>();
            CDNDownloader     = CDNSupport ? std::make_unique<CoDCDNDownloaderV1>() : nullptr;
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            OnDemandCache->LoadPackageCacheAsync(FileSystems::CombinePath(ps::state->GameDirectory, "xpak_cache"));
            Success = GameVanguard::LoadAssets();
            break;
        // Modern Warfare Remastered
        case 0x30305453414D4552:
            GameID            = SupportedGames::ModernWarfareRemastered;
            GameFlags         = SupportedGameFlags::None;
            GameXImageHandler = GameModernWarfareRM::LoadXImagePS;
            GameStringHandler = GameModernWarfareRM::LoadStringEntry;
            GamePackageCache  = std::make_unique<PAKCache>();
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            Success = GameModernWarfareRM::LoadAssetsPS();
            break;
        // Advanced Warfare
        case 0x5241574E41564441:
            GameID            = SupportedGames::AdvancedWarfare;
            GameFlags         = SupportedGameFlags::None;
            GameXImageHandler = GameAdvancedWarfare::LoadXImagePS;
            GameStringHandler = GameAdvancedWarfare::LoadStringEntry;
            GamePackageCache  = std::make_unique<PAKCache>();
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            Success = GameAdvancedWarfare::LoadAssetsPS();
            break;
        // Infinite Warfare
        case 0x4652415749464E49:
            GameID = SupportedGames::InfiniteWarfare;
            GameFlags = SupportedGameFlags::None;
            GameXImageHandler = GameInfiniteWarfare::LoadXImagePS;
            GameStringHandler = GameInfiniteWarfare::LoadStringEntry;
            GamePackageCache = std::make_unique<PAKCache>();
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            Success = GameInfiniteWarfare::LoadAssetsPS();
            break;
        // Modern Warfare 2 Remastered
        case 0x32305453414D4552:
            GameID = SupportedGames::ModernWarfare2Remastered;
            GameFlags = SupportedGameFlags::None;
            GameXImageHandler = GameModernWarfare2RM::LoadXImagePS;
            GameStringHandler = GameModernWarfare2RM::LoadStringEntry;
            GamePackageCache = std::make_unique<PAKCache>();
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            Success = GameModernWarfare2RM::LoadAssetsPS();
            break;
        // Modern Warfare 2 (2022)
        case 0x3232524157444F4D:
            GameModernWarfare5::PerformInitialSetup();
            GameID            = SupportedGames::ModernWarfare5;
            GameFlags         = ps::state->HasFlag("sp") ? SupportedGameFlags::SP : SupportedGameFlags::MP;
            GameXImageHandler = GameModernWarfare5::LoadXImage;
            GameStringHandler = GameModernWarfare5::LoadStringEntry;
            GamePackageCache  = std::make_unique<XSUBCacheV3>();
            CDNDownloader     = CDNSupport ? std::make_unique<CoDCDNDownloaderV2>() : nullptr;
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            Success = GameModernWarfare5::LoadAssets();
            break;
        // Modern Warfare 3 (2023)
        case 0x4B4F4D41594D4159:
            GameModernWarfare6::PerformInitialSetup();
            GameID = SupportedGames::ModernWarfare6;
            GameFlags = ps::state->HasFlag("sp") ? SupportedGameFlags::SP : SupportedGameFlags::MP;
            GameXImageHandler = GameModernWarfare6::LoadXImage;
            GameStringHandler = GameModernWarfare6::LoadStringEntry;
            GamePackageCache = std::make_unique<XSUBCacheV3>();
            CDNDownloader = CDNSupport ? std::make_unique<CoDCDNDownloaderV2>() : nullptr;
            GamePackageCache->LoadPackageCacheAsync(ps::state->GameDirectory);
            Success = GameModernWarfare6::LoadAssets();
            break;
        }

        // Check for CDN
        if (CDNDownloader != nullptr)
            CDNDownloader->Initialize(ps::state->GameDirectory);

        // Done with logger
        XAssetLogWriter = nullptr;

        // Result check
        if (Success)
        {
            // Sort the assets, for now we only support 2 modes, but this can be extended in the future.
            auto sortMethod = AssetCompareMethodHelper::CalculateCompareMethod(SettingsManager::GetSetting("assetsortmethod", "Name"));

            if (sortMethod != AssetCompareMethod::None)
            {
                std::stable_sort(GameAssets->LoadedAssets.begin(), GameAssets->LoadedAssets.end(), [sortMethod](const CoDAsset_t* lhs, const CoDAsset_t* rhs)
                {
                    return lhs->Compare(rhs, sortMethod);
                });
            }


            // Success
            return LoadGameResult::Success;
        }
        else
        {
            // Failed to load
            return LoadGameResult::NoAssetsFound;
        }
    }

    // Reset
    if (GameAssets != nullptr)
    {
        // Clean up
        GameAssets.reset();
    }

    // Failed
    return LoadGameResult::ProcessNotRunning;
}

ps::XAsset64 CoDAssets::ParasyteRequest(const uint64_t& AssetPointer)
{
    return CoDAssets::GameInstance->Read<ps::XAsset64>(AssetPointer);
}

LoadGameFileResult CoDAssets::LoadFile(const std::string& FilePath)
{
    // Setup the assets
    GameAssets.reset(new AssetPool());

    // Load result
    auto LoadResult = false;

    // Determine based on file extension first
    auto FileExt = Strings::ToLower(FileSystems::GetExtension(FilePath));

    // Check known extensions
    if (FileExt == ".xpak")
    {
        // Pass off to XPAK File Parser (And Cache the File)
        LoadResult = XPAKSupport::ParseXPAK(FilePath);

        // Cache if success
        if (LoadResult)
        {
            // Allocate a new XPAK Cache
            GamePackageCache = std::make_unique<XPAKCache>();
            // Cache package entries for this specific file
            GamePackageCache->LoadPackageAsync(FilePath);

            // Set game mode
            GameFlags = SupportedGameFlags::Files;
        }
    }
    else if (FileExt == ".ipak")
    {
        // Pass off to IPAK File Parser
        LoadResult = IPAKSupport::ParseIPAK(FilePath);

        // Cache if success
        if (LoadResult)
        {
            // Allocate a new IPAK Cache
            GamePackageCache = std::make_unique<IPAKCache>();
            // Cache package entries for this specific file
            GamePackageCache->LoadPackageAsync(FilePath);

            // Set game mode
            GameID = SupportedGames::BlackOps2;
            GameFlags = SupportedGameFlags::Files;
        }
    }
    else if (FileExt == ".iwd")
    {
        // Pass off to IWD File Parser
        LoadResult = IWDSupport::ParseIWD(FilePath);

        // Cache if success
        if (LoadResult)
        {
            // Allocate a new IWD Cache
            GamePackageCache = std::make_unique<IWDCache>();
            // Cache package entries for this specific file
            GamePackageCache->LoadPackageAsync(FilePath);

            // Set game mode (Determine export path from the file's path)
            auto GamePath = Strings::ToLower(FileSystems::GetDirectoryName(FilePath));

            // Compare
            if (Strings::Contains(GamePath, "black ops"))
            {
                GameID = SupportedGames::BlackOps;
            }
            else if (Strings::Contains(GamePath, "call of duty 4"))
            {
                GameID = SupportedGames::ModernWarfare;
            }
            else if (Strings::Contains(GamePath, "modern warfare 2"))
            {
                GameID = SupportedGames::ModernWarfare2;
            }
            else if (Strings::Contains(GamePath, "modern warfare 3"))
            {
                GameID = SupportedGames::ModernWarfare3;
            }
            else
            {
                // Default to WAW path
                GameID = SupportedGames::WorldAtWar;
            }

            // Set file mode
            GameFlags = SupportedGameFlags::Files;
        }
    }
    else if (FileExt == ".sabs" || FileExt == ".sabl")
    {
        // Pass off to SAB File Parser
        LoadResult = SABSupport::ParseSAB(FilePath);

        // Cache if success
        if (LoadResult)
        {
            // Allocate a new SAB Cache
            GamePackageCache = std::make_unique<SABCache>();
            // Cache file path for faster extraction
            GamePackageCache->LoadPackageCacheAsync(FilePath);

            // Set file mode
            GameFlags = SupportedGameFlags::Files;
        }
    }
    else
    {
        // Unknown
        return LoadGameFileResult::UnknownError;
    }

    // Check result, then sort
    if (LoadResult)
    {
        // Sort the assets, for now we only support 2 modes, but this can be extended in the future.
        auto sortMethod = AssetCompareMethodHelper::CalculateCompareMethod(SettingsManager::GetSetting("assetsortmethod", "Name"));

        if (sortMethod != AssetCompareMethod::None)
        {
            std::stable_sort(GameAssets->LoadedAssets.begin(), GameAssets->LoadedAssets.end(), [sortMethod](const CoDAsset_t* lhs, const CoDAsset_t* rhs)
            {
                return lhs->Compare(rhs, sortMethod);
            });
        }

        // Success
        return LoadGameFileResult::Success;
    }

    // Reset
    if (GameAssets != nullptr)
    {
        // Clean up
        GameAssets.reset();
    }

    // Return it
    return LoadGameFileResult::InvalidFile;
}

ExportGameResult CoDAssets::ExportAsset(const CoDAsset_t* Asset,
    void* ProgressCaller, uint32_t ProgressStart, uint32_t ProgressSpan)
{
    LatestTerrainFinalizationFailed = false;
    // Hold an inheritable, exclusive file handle for the complete capture and
    // integrity seal. The Python finalizer inherits it, so force-closing
    // Greyhound cannot allow another export to overwrite a capture while its
    // hashes are still being recorded.
    HANDLE TerrainExportLock = INVALID_HANDLE_VALUE;
    if (Asset->AssetType == WraithAssetType::Terrain)
    {
        SECURITY_ATTRIBUTES Security{};
        Security.nLength = sizeof(Security);
        Security.bInheritHandle = TRUE;
        const auto LockPath = FileSystems::CombinePath(
            FileSystems::GetApplicationPath(), "terrain_export.lock");
        TerrainExportLock = CreateFileA(LockPath.c_str(), GENERIC_READ | GENERIC_WRITE,
            0, &Security, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (TerrainExportLock == INVALID_HANDLE_VALUE)
        {
            CoDAssets::Log->error("A terrain export is already running; wait for it to finish before exporting again");
            return ExportGameResult::UnknownError;
        }
    }
    const auto ReportProgress = [=](uint32_t LocalProgress)
    {
        if (ProgressCaller != nullptr && CoDAssets::OnExportProgress != nullptr)
        {
            const uint32_t Overall = ProgressStart +
                static_cast<uint32_t>((static_cast<uint64_t>(ProgressSpan) *
                    std::min<uint32_t>(LocalProgress, 100)) / 100);
            CoDAssets::OnExportProgress(ProgressCaller, std::min<uint32_t>(Overall, 100));
        }
    };
    if (Asset->AssetType == WraithAssetType::Terrain)
        ReportProgress(2);
    // Prepare to export the asset
    auto ExportPath = BuildExportPath(Asset);
    if (Asset->AssetType == WraithAssetType::Terrain)
    {
        ExportPath = TerrainLayout::CreateRun(ExportPath);
        if (ExportPath.empty())
        {
            if (TerrainExportLock != INVALID_HANDLE_VALUE) CloseHandle(TerrainExportLock);
            CoDAssets::Log->error("Could not reserve a NEW terrain capture run");
            return ExportGameResult::UnknownError;
        }
    }
    // Only ExportSelectedAssets used to record this, so anything driving
    // ExportAsset directly -- the headless CLI does -- saw an empty path and
    // wrote its follow-up output beside the exe instead of beside the asset.
    LatestExportPath = ExportPath;
    // Create it, if not exists
    FileSystems::CreateDirectory(ExportPath);
    const auto TerrainSourcePath = Asset->AssetType == WraithAssetType::Terrain
        ? FileSystems::CombinePath(ExportPath, TerrainLayout::Source) : ExportPath;
    const auto TerrainLogPath = FileSystems::CombinePath(ExportPath, TerrainLayout::Logs);
    if (Asset->AssetType == WraithAssetType::Terrain)
    {
        FileSystems::CreateDirectory(TerrainSourcePath);
        FileSystems::CreateDirectory(TerrainLogPath);
    }

    // Build image export path
    auto ImagesPath = (SettingsManager::GetSetting("global_images", "true") == "true") ? FileSystems::CombinePath(FileSystems::GetDirectoryName(ExportPath), "_images") : FileSystems::CombinePath(ExportPath, "_images");
    // Build images path
    auto ImageRelativePath = (SettingsManager::GetSetting("global_images", "true") == "true") ? "..\\\\_images\\\\" : "_images\\\\";
    // Build image ext
    auto ImageExtension = "." + Strings::ToLower(SettingsManager::GetSetting("exportimg"));
    // Build sound ext
    auto SoundExtension = "." + Strings::ToLower(SettingsManager::GetSetting("exportsnd"));

    // Result
    auto Result = ExportGameResult::Success;

// #ifndef _DEBUG
    try
    {
// #endif
        // Send to specific export handler
        switch (Asset->AssetType)
        {
            // Export an animation
            case WraithAssetType::Animation: {Result = ExportAnimationAsset((CoDAnim_t*)Asset, ExportPath); break;}
            // Export a model, combine the name of the model with the export path!
            case WraithAssetType::Model: {Result = ExportModelAsset((CoDModel_t*)Asset, ExportPath, ImagesPath, ImageRelativePath, ImageExtension); break;}
            // Export an image
            case WraithAssetType::Image: {Result = ExportImageAsset((CoDImage_t*)Asset, ExportPath, ImageExtension); break;}
            // Export a sound
            case WraithAssetType::Sound: {Result = ExportSoundAsset((CoDSound_t*)Asset, ExportPath, CoDAssets::GameID == SupportedGames::WorldAtWar ? ".wav" : SoundExtension); break;}
            // Export a rawfile
            case WraithAssetType::RawFile: {Result = ExportRawfileAsset((CoDRawFile_t*)Asset, ExportPath); break;}
            // Export a material
            case WraithAssetType::Material: {Result = ExportMaterialAsset((CoDMaterial_t*)Asset, ExportPath, ImagesPath, ImageRelativePath, ImageExtension); break;}
            // Export an opaque TerrainGfx header for the SuperTerrain decoder
            case WraithAssetType::Terrain: {Result = ExportTerrainAsset(
                (CoDTerrain_t*)Asset, TerrainSourcePath, ReportProgress); break;}
        }
// #ifndef _DEBUG
    }
    catch (const std::exception& Error)
    {
        Result = ExportGameResult::UnknownError;
        CoDAssets::Log->error("Export failed for {0}: {1}", Asset->AssetName, Error.what());
    }
    catch (...)
    {
        Result = ExportGameResult::UnknownError;
        CoDAssets::Log->error("An exception occurred while exporting asset: {0}", Asset->AssetName);
#if _DEBUG
		std::cout << "Error: An exception occurred while exporting asset:" << Asset->AssetName.c_str() << "\n";
#endif // _DEBUG
    }
// #endif

    // Terrain export ends by organizing and sealing immutable source data.
    // Reconstruction is a separate program and is never launched by Greyhound.
    if (Result == ExportGameResult::Success &&
        Asset->AssetType == WraithAssetType::Terrain &&
        !FinishTerrainExport(TerrainSourcePath, TerrainLogPath,
            ReportProgress))
    {
        LatestTerrainFinalizationFailed = true;
        Result = ExportGameResult::UnknownError;
    }

    if (TerrainExportLock != INVALID_HANDLE_VALUE)
        CloseHandle(TerrainExportLock);

    // Success, unless specific error
    return Result;
}

std::unique_ptr<WraithModel> CoDAssets::GetModelForPreview(const CoDModel_t* Model)
{
    // Attempt to load the model
    auto GenericModel = CoDAssets::LoadGenericModelAsset(Model);

    // If loaded, continue
    if (GenericModel != nullptr)
        return CoDXModelTranslator::TranslateXModel(GenericModel, CoDXModelTranslator::CalculateBiggestLodIndex(GenericModel));

    // Failed somehow
    return nullptr;
}

std::string CoDAssets::GetHashedName(const std::string& type, const uint64_t hash)
{
    auto found = AssetNameCache.NameDatabase.find(hash & 0xFFFFFFFFFFFFFFF);

    if (found != AssetNameCache.NameDatabase.end())
    {
        return found->second;
    }

    return Strings::Format("%s_%llx", type.c_str(), hash & 0xFFFFFFFFFFFFFFF);
}

std::string CoDAssets::GetHashedString(const std::string& type, const uint64_t hash)
{
    auto found = StringCache.NameDatabase.find(hash);

    if (found != StringCache.NameDatabase.end())
    {
        return found->second;
    }

    return Strings::Format("%s_%llx", type.c_str(), hash);
}

bool CoDAssets::LocateGameInfo()
{
    // Whether or not we found what we need
    bool Success = false;

    // Attempt to find the loaded game's offsets, either via DB or heuristics
    // Also, apply proper handlers for various game read functions (Non-inlinable functions only)
    switch (GameID)
    {
    case SupportedGames::QuantumSolace:
        // Load game offset info
        Success = GameQuantumSolace::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameQuantumSolace::LoadXImage;
        // Set game string handler
        GameStringHandler = GameQuantumSolace::LoadStringEntry;
        break;
    case SupportedGames::WorldAtWar:
        // Load game offset info
        Success = GameWorldAtWar::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameWorldAtWar::LoadXImage;
        // Set game string handler
        GameStringHandler = GameWorldAtWar::LoadStringEntry;
        // Allocate a new IWD Mega Cache
        GamePackageCache = std::make_unique<IWDCache>();
        // Set the IWD path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "main"));
        break;
    case SupportedGames::BlackOps:
        // Load game offset info
        Success = GameBlackOps::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameBlackOps::LoadXImage;
        // Set game string handler
        GameStringHandler = GameBlackOps::LoadStringEntry;
        // Allocate a new IWD Mega Cache
        GamePackageCache = std::make_unique<IWDCache>();
        // Set the IWD path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "main"));
        break;
    case SupportedGames::BlackOps2:
        // Load game offset info
        Success = GameBlackOps2::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameBlackOps2::LoadXImage;
        // Set game string handler
        GameStringHandler = GameBlackOps2::LoadStringEntry;
        // Allocate a new IPAK Mega Cache
        GamePackageCache = std::make_unique<IPAKCache>();
        // Set the IPAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "zone\\all"));
        break;
    case SupportedGames::BlackOps3:
        // Load game offset info
        Success = GameBlackOps3::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameBlackOps3::LoadXImage;
        // Set game string handler
        GameStringHandler = GameBlackOps3::LoadStringEntry;
        // Allocate a new XPAK Mega Cache
        GamePackageCache = std::make_unique<XPAKCache>();
        // Set the XPAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "zone"));
        break;
    case SupportedGames::BlackOps4:
    {
        // Initial setup required for BO4
        GameBlackOps4::PerformInitialSetup();
        // Load game offset info
        Success = GameBlackOps4::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameBlackOps4::LoadXImage;
        // Set game string handler
        GameStringHandler = GameBlackOps4::LoadStringEntry;
        break;
    }
    case SupportedGames::BlackOpsCW:
    {
        // Initial setup required for BO4
        GameBlackOpsCW::PerformInitialSetup();
        // Load game offset info
        Success = GameBlackOpsCW::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameBlackOpsCW::LoadXImage;
        // Set game string handler
        GameStringHandler = GameBlackOpsCW::LoadStringEntry;
        break;
    }
    case SupportedGames::ModernWarfare:
        // Load game offset info
        Success = GameModernWarfare::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameModernWarfare::LoadXImage;
        // Set game string handler
        GameStringHandler = GameModernWarfare::LoadStringEntry;
        // Allocate a new IWD Mega Cache
        GamePackageCache = std::make_unique<IWDCache>();
        // Set the IWD path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "main"));
        break;
    case SupportedGames::ModernWarfare2:
        // Load game offset info
        Success = GameModernWarfare2::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameModernWarfare2::LoadXImage;
        // Set game string handler
        GameStringHandler = GameModernWarfare2::LoadStringEntry;
        // Allocate a new IWD Mega Cache
        GamePackageCache = std::make_unique<IWDCache>();
        // Set the IWD path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "main"));
        break;
    case SupportedGames::ModernWarfare3:
        // Load game offset info
        Success = GameModernWarfare3::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameModernWarfare3::LoadXImage;
        // Set game string handler
        GameStringHandler = GameModernWarfare3::LoadStringEntry;
        // Allocate a new IWD Mega Cache
        GamePackageCache = std::make_unique<IWDCache>();
        // Set the IWD path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::CombinePath(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()), "main"));
        break;
    case SupportedGames::Ghosts:
        // Load game offset info
        Success = GameGhosts::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameGhosts::LoadXImage;
        // Set game string handler
        GameStringHandler = GameGhosts::LoadStringEntry;
        // Allocate a new PAK Mega Cache
        GamePackageCache = std::make_unique<PAKCache>();
        // Set the PAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
        break;
    case SupportedGames::AdvancedWarfare:
        // Load game offset info
        Success = GameAdvancedWarfare::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameAdvancedWarfare::LoadXImage;
        // Set game string handler
        GameStringHandler = GameAdvancedWarfare::LoadStringEntry;
        // Allocate a new PAK Mega Cache
        GamePackageCache = std::make_unique<PAKCache>();
        // Set the PAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
        break;
    case SupportedGames::ModernWarfareRemastered:
        // Load game offset info
        Success = GameModernWarfareRM::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameModernWarfareRM::LoadXImage;
        // Set game string handler
        GameStringHandler = GameModernWarfareRM::LoadStringEntry;
        // Allocate a new PAK Mega Cache
        GamePackageCache = std::make_unique<PAKCache>();
        // Set the PAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
        break;
    case SupportedGames::ModernWarfare2Remastered:
        // Load game offset info
        Success = GameModernWarfare2RM::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameModernWarfare2RM::LoadXImage;
        // Set game string handler
        GameStringHandler = GameModernWarfare2RM::LoadStringEntry;
        // Allocate a new PAK Mega Cache
        GamePackageCache = std::make_unique<PAKCache>();
        // Set the PAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
        break;
    case SupportedGames::InfiniteWarfare:
        // Load game offset info
        Success = GameInfiniteWarfare::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameInfiniteWarfare::LoadXImage;
        // Set game string handler
        GameStringHandler = GameInfiniteWarfare::LoadStringEntry;
        // Allocate a new PAK Mega Cache
        GamePackageCache = std::make_unique<PAKCache>();
        // Set the PAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
        break;
    case SupportedGames::WorldWar2:
        // Load game offset info
        Success = GameWorldWar2::LoadOffsets();
        // Set game ximage handler
        GameXImageHandler = GameWorldWar2::LoadXImage;
        // Set game string handler
        GameStringHandler = GameWorldWar2::LoadStringEntry;
        // Allocate a new PAK Mega Cache
        GamePackageCache = std::make_unique<XPTOCCache>();
        // Set the PAK path
        GamePackageCache->LoadPackageCacheAsync(FileSystems::GetDirectoryName(GameInstance->GetProcessPath()));
        break;
    case SupportedGames::Parasyte:
        // Locate Parasyte Current Handler Database
        const auto DBFile = FileSystems::CombinePath(FileSystems::GetDirectoryName(CoDAssets::GameInstance->GetProcessPath()), "Data\\CurrentHandler.csi");
        Success = FileSystems::FileExists(DBFile);
        // Validate
        if (Success)
        {
            ps::state = std::make_unique<ps::State>();
            Success = ps::state->Load(DBFile);
        }
        // Don't Check Offsets or Set up GDT until below
        return Success;
    }

    // Validate the results, every game should have at least 1 offset and 1 size, and success must be true
    if (Success && !GameOffsetInfos.empty() && !GamePoolSizes.empty())
    {
        // We succeeded
        return true;
    }

    // We failed to load
    return false;
}

std::string CoDAssets::BuildExportPath(const CoDAsset_t* Asset)
{
    // Build the export path
    auto ApplicationPath = FileSystems::CombinePath(FileSystems::GetApplicationPath(), "exported_files");

    // Append the game directory
    switch (GameID)
    {
    case SupportedGames::QuantumSolace: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "quantum_solace"); break;
    case SupportedGames::WorldAtWar: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "world_at_war"); break;
    case SupportedGames::BlackOps: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "black_ops_1"); break;
    case SupportedGames::BlackOps2: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "black_ops_2"); break;
    case SupportedGames::BlackOps3: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "black_ops_3"); break;
    case SupportedGames::BlackOps4: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "black_ops_4"); break;
    case SupportedGames::BlackOpsCW: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "black_ops_cw"); break;
    case SupportedGames::ModernWarfare: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare"); break;
    case SupportedGames::ModernWarfare2: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_2"); break;
    case SupportedGames::ModernWarfare3: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_3"); break;
    case SupportedGames::ModernWarfare4: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_4"); break;
    case SupportedGames::ModernWarfare5: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_5"); break;
    case SupportedGames::ModernWarfare6: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_6"); break;
    case SupportedGames::Ghosts: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "ghosts"); break;
    case SupportedGames::AdvancedWarfare: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "advanced_warfare"); break;
    case SupportedGames::ModernWarfareRemastered: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_rm"); break;
    case SupportedGames::ModernWarfare2Remastered: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "modern_warfare_2_rm"); break;
    case SupportedGames::InfiniteWarfare: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "infinite_warfare"); break;
    case SupportedGames::WorldWar2: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "world_war_2"); break;
    case SupportedGames::Vanguard: ApplicationPath = FileSystems::CombinePath(ApplicationPath, "vanguard"); break;
    }

    // Append the asset type folder (Some assets have specific folder names)
    switch (Asset->AssetType)
    {
    case WraithAssetType::Animation:
        // Default directory
        ApplicationPath = FileSystems::CombinePath(ApplicationPath, "xanims");
        break;
    case WraithAssetType::Model:
        // Directory with asset name
        ApplicationPath = FileSystems::CombinePath(FileSystems::CombinePath(ApplicationPath, "xmodels"), ModelFileName(Asset->AssetName));
        break;
    case WraithAssetType::Image:
        // Default directory
        ApplicationPath = FileSystems::CombinePath(ApplicationPath, "ximages");
        break;
    case WraithAssetType::Sound:
        // Default directory, OR, Merged with path, check setting
        ApplicationPath = FileSystems::CombinePath(ApplicationPath, "sounds");
        // Check setting for merged paths
        if (SettingsManager::GetSetting("keepsndpath", "true") == "true")
        {
            // Merge it
            ApplicationPath = FileSystems::CombinePath(ApplicationPath, ((CoDSound_t*)Asset)->FullPath);
        }
        break;
    case WraithAssetType::RawFile:
        // Default directory
        ApplicationPath = FileSystems::CombinePath(ApplicationPath, "xrawfiles");
        break;
    case WraithAssetType::Material:
        // Directory with asset name
        ApplicationPath = FileSystems::CombinePath(FileSystems::CombinePath(ApplicationPath, "xmaterials"), Asset->AssetName);
        break;
    case WraithAssetType::Terrain:
        // Keep every TerrainGfx asset and its metadata in a separate folder.
        ApplicationPath = FileSystems::CombinePath(FileSystems::CombinePath(ApplicationPath, "terrains"), Asset->AssetName);
        break;
    }

    // Return it
    return ApplicationPath;
}

std::string CoDAssets::GetExportPath(const CoDAsset_t* Asset)
{
    return BuildExportPath(Asset);
}

std::unique_ptr<XAnim_t> CoDAssets::LoadGenericAnimAsset(const CoDAnim_t* Animation)
{
    // Read from game
    switch (CoDAssets::GameID)
    {
    case SupportedGames::QuantumSolace: return GameQuantumSolace::ReadXAnim(Animation); break;
    case SupportedGames::WorldAtWar: return GameWorldAtWar::ReadXAnim(Animation); break;
    case SupportedGames::BlackOps: return GameBlackOps::ReadXAnim(Animation); break;
    case SupportedGames::BlackOps2: return GameBlackOps2::ReadXAnim(Animation); break;
    case SupportedGames::BlackOps3: return GameBlackOps3::ReadXAnim(Animation); break;
    case SupportedGames::BlackOps4: return GameBlackOps4::ReadXAnim(Animation); break;
    case SupportedGames::BlackOpsCW: return GameBlackOpsCW::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare: return GameModernWarfare::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare2: return GameModernWarfare2::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare3: return GameModernWarfare3::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare4: return GameModernWarfare4::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare5: return GameModernWarfare5::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare6: return GameModernWarfare6::ReadXAnim(Animation); break;
    case SupportedGames::Ghosts: return GameGhosts::ReadXAnim(Animation); break;
    case SupportedGames::AdvancedWarfare: return GameAdvancedWarfare::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfareRemastered: return GameModernWarfareRM::ReadXAnim(Animation); break;
    case SupportedGames::ModernWarfare2Remastered: return GameModernWarfare2RM::ReadXAnim(Animation); break;
    case SupportedGames::InfiniteWarfare: return GameInfiniteWarfare::ReadXAnim(Animation); break;
    case SupportedGames::WorldWar2: return GameWorldWar2::ReadXAnim(Animation); break;
    case SupportedGames::Vanguard: return GameVanguard::ReadXAnim(Animation); break;
    }

    // Unknown game
    return nullptr;
}

ExportGameResult CoDAssets::ExportAnimationAsset(const CoDAnim_t* Animation, const std::string& ExportPath)
{
    // Quit if we should not export this model (files already exist)
    if (!ShouldExportAnim(FileSystems::CombinePath(ExportPath, Animation->AssetName)))
        return ExportGameResult::Success;

    // Prepare to export the animation
    std::unique_ptr<XAnim_t> GenericAnimation = CoDAssets::LoadGenericAnimAsset(Animation);

    // Check
    if (GenericAnimation != nullptr)
    {
        // Translate generic animation to a WraithAnim, then export
        auto Result = CoDXAnimTranslator::TranslateXAnim(GenericAnimation);

        // Check result and export
        if (Result != nullptr)
        {
            // Prepare to export to the formats specified in settings

            // Check for DirectXAnim format
            if (SettingsManager::GetSetting("export_directxanim") == "true")
            {
                // Determine export file version
                auto XAnimVer = (SettingsManager::GetSetting("directxanim_ver") == "17") ? XAnimRawVersion::WorldAtWar : XAnimRawVersion::BlackOps;
                // Export a XAnim Raw
                XAnimRaw::ExportXAnimRaw(*Result.get(), FileSystems::CombinePath(ExportPath, Result->AssetName), XAnimVer);
            }

            // The following formats are scaled
            Result->ScaleAnimation(2.54f);

            // Check for SEAnim format
            if (SettingsManager::GetSetting("export_seanim") == "true")
            {
                // Export a SEAnim
                SEAnim::ExportSEAnim(*Result.get(), FileSystems::CombinePath(ExportPath, Result->AssetName + ".seanim"));
            }
            // Check for Cast format
            if (SettingsManager::GetSetting("export_castanim") == "true")
            {
                // Export a Cast
                Cast::ExportCastAnim(*Result.get(), FileSystems::CombinePath(ExportPath, Result->AssetName + ".cast"));
            }
        }
        else
        {
            // We failed
            return ExportGameResult::UnknownError;
        }
    }
    else
    {
        // We failed
        return ExportGameResult::UnknownError;
    }

    // Success, unless specific error
    return ExportGameResult::Success;
}

std::unique_ptr<XModel_t> CoDAssets::LoadGenericModelAsset(const CoDModel_t* Model)
{
    // Read from game
    switch (CoDAssets::GameID)
    {
    case SupportedGames::QuantumSolace: return GameQuantumSolace::ReadXModel(Model); break;
    case SupportedGames::WorldAtWar: return GameWorldAtWar::ReadXModel(Model); break;
    case SupportedGames::BlackOps: return GameBlackOps::ReadXModel(Model); break;
    case SupportedGames::BlackOps2: return GameBlackOps2::ReadXModel(Model); break;
    case SupportedGames::BlackOps3: return GameBlackOps3::ReadXModel(Model); break;
    case SupportedGames::BlackOps4: return GameBlackOps4::ReadXModel(Model); break;
    case SupportedGames::BlackOpsCW: return GameBlackOpsCW::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare: return GameModernWarfare::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare2: return GameModernWarfare2::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare3: return GameModernWarfare3::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare4: return GameModernWarfare4::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare5: return GameModernWarfare5::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare6: return GameModernWarfare6::ReadXModel(Model); break;
    case SupportedGames::Ghosts: return GameGhosts::ReadXModel(Model); break;
    case SupportedGames::AdvancedWarfare: return GameAdvancedWarfare::ReadXModel(Model); break;
    case SupportedGames::ModernWarfareRemastered: return GameModernWarfareRM::ReadXModel(Model); break;
    case SupportedGames::ModernWarfare2Remastered: return GameModernWarfare2RM::ReadXModel(Model); break;
    case SupportedGames::InfiniteWarfare: return GameInfiniteWarfare::ReadXModel(Model); break;
    case SupportedGames::WorldWar2: return GameWorldWar2::ReadXModel(Model); break;
    case SupportedGames::Vanguard: return GameVanguard::ReadXModel(Model); break;
    }

    // Unknown game
    return nullptr;
}

bool CoDAssets::ShouldExportAnim(std::string ExportPath)
{
    // Check if we want to skip previous anims
    auto SkipPrevAnims = SettingsManager::GetSetting("skipprevanim") == "true";

    // If we don't want to skip previously exported anims, then we will continue
    if (!SkipPrevAnims)
        return true;

    // Initialize result
    bool Result = false;

    // Check it
    if (SettingsManager::GetSetting("export_directxanim") == "true" && !FileSystems::FileExists(ExportPath))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_seanim") == "true" && !FileSystems::FileExists(ExportPath + ".seanim"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_castanim") == "true" && !FileSystems::FileExists(ExportPath + ".cast"))
        Result = true;

    // Done
    return Result;
}

bool CoDAssets::ShouldExportModel(std::string ExportPath)
{
    // Check if we want to skip previous models
    auto SkipPrevModels = SettingsManager::GetSetting("skipprevmodel") == "true";

    // If we don't want to skip previously exported models, then we will continue
    if (!SkipPrevModels)
        return true;

    // Initialize result
    bool Result = false;

    // Check it
    if (SettingsManager::GetSetting("export_xmexport") == "true" && !FileSystems::FileExists(ExportPath + ".XMODEL_EXPORT"))
        Result = true;
    // XMODEL_BIN was previously omitted here, so a CLI run requesting only
    // that format could be incorrectly treated as already exported.
    if (SettingsManager::GetSetting("export_xmbin") == "true" && !FileSystems::FileExists(ExportPath + ".XMODEL_BIN"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_smd") == "true" && !FileSystems::FileExists(ExportPath + ".smd"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_obj") == "true" && !FileSystems::FileExists(ExportPath + ".obj"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_ma") == "true" && !FileSystems::FileExists(ExportPath + ".ma"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_xna") == "true" && !FileSystems::FileExists(ExportPath + ".mesh.ascii"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_semodel") == "true" && !FileSystems::FileExists(ExportPath + ".semodel"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_gltf") == "true" && !FileSystems::FileExists(ExportPath + ".gltf"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_glb") == "true" && !FileSystems::FileExists(ExportPath + ".glb"))
        Result = true;
    // Check it
    if (SettingsManager::GetSetting("export_castmdl") == "true" && !FileSystems::FileExists(ExportPath + ".cast"))
        Result = true;
    //// Check it
    //if (SettingsManager::GetSetting("export_fbx") == "true" && !FileSystems::FileExists(ExportPath + ".fbx"))
    //    Result = true;

    // Done
    return Result;
}

ExportGameResult CoDAssets::ExportJsonBatchModel(const CoDModel_t* Model, const std::string& Root)
{
    if (GameID != SupportedGames::BlackOpsCW) throw std::runtime_error("JSON batch layout supports Cold War only");
    if (Root.empty()) throw std::runtime_error("Missing JSON batch output directory");
    const auto Models = FileSystems::CombinePath(Root, "models");
    const auto Images = FileSystems::CombinePath(Root, "images");
    const auto Materials = FileSystems::CombinePath(Root, "materials");
    FileSystems::CreateDirectory(Models);
    FileSystems::CreateDirectory(Images);
    FileSystems::CreateDirectory(Materials);
    LatestExportPath = Root;
    return ExportModelAsset(Model, Models, Images, "../images/",
        "." + Strings::ToLower(SettingsManager::GetSetting("exportimg", "PNG")), Root);
}

ExportGameResult CoDAssets::ExportModelAsset(const CoDModel_t* Model, const std::string& ExportPath, const std::string& ImagesPath, const std::string& ImageRelativePath, const std::string& ImageExtension, const std::string& BatchRoot)
{
    // Reserve the shortened directory with its original identity. This also
    // prevents a later map's variant from being mistaken for an existing export.
    // Check ordinary names too: they may collide with a cleaned map name.
    {
        static std::mutex IdentityMutex;
        std::lock_guard<std::mutex> Lock(IdentityMutex);
        if (!BatchRoot.empty())
        {
            const auto Path = FileSystems::CombinePath(BatchRoot, "model_identities.json");
            nlohmann::json Identities = nlohmann::json::object();
            std::ifstream Input(Path); if (Input) Input >> Identities;
            auto Key = Strings::ToLower(ModelFileName(Model->AssetName));
            if (Identities.contains(Key) && Identities[Key].get<std::string>() != Model->AssetName)
                throw std::runtime_error("Flat model name collision: " + ModelFileName(Model->AssetName));
            if (!Identities.contains(Key))
            {
                const auto Stem = ModelFileName(Model->AssetName);
                if (!FileSystems::GetFiles(ExportPath, Stem + ".*").empty() ||
                    !FileSystems::GetFiles(ExportPath, Stem + "_LOD*").empty())
                    throw std::runtime_error("Existing flat model files have no recorded identity: " + Stem);
                Identities[Key] = Model->AssetName;
                std::ofstream Output(Path, std::ios::binary); Output << Identities.dump(2); Output.close();
                if (!Output) throw std::runtime_error("Could not save batch model identities");
            }
        }
        else
        {
        const auto IdentityPath = FileSystems::CombinePath(ExportPath, "model_identity.json");
        std::ifstream Existing(IdentityPath);
        if (Existing)
        {
            nlohmann::json Identity; Existing >> Identity;
            if (Identity.value("original_name", std::string()) != Model->AssetName)
                throw std::runtime_error("Short model name collision at " + ExportPath + "; model_identity.json belongs to another runtime name.");
        }
        else if (ModelExportNaming::Stem(Model->AssetName) != Model->AssetName)
        {
            // Do not claim an existing unlabelled directory of model files.
            const auto Files = FileSystems::GetFiles(ExportPath, "*");
            if (!Files.empty())
                throw std::runtime_error("Cannot verify ownership of existing shortened model directory: " + ExportPath);
            nlohmann::json Identity = {{"original_name",Model->AssetName},
                {"export_name",ModelFileName(Model->AssetName)},
                {"kind","compiled_map_named_xmodel"},
                {"coordinates","original model coordinates; CAST/OBJ scaled from game inches to centimetres"}};
            std::ofstream Output(IdentityPath, std::ios::binary); Output << Identity.dump(2); Output.close();
            if (!Output) throw std::runtime_error("Could not save model identity: " + IdentityPath);
        }
        }
    }
    // Prepare to export the model
    std::unique_ptr<XModel_t> GenericModel = CoDAssets::LoadGenericModelAsset(Model);
    // Grab the image format type
    auto ImageFormatType = ImageFormat::Standard_PNG;
    // Check setting
    auto ImageSetting = SettingsManager::GetSetting("exportimg", "PNG");
    // Check if we even need images
    auto ExportImages = SettingsManager::GetSetting("exportmodelimg") == "true";
    // Check if we want image names
    auto ExportImageNames = SettingsManager::GetSetting("exportimgnames") == "true";
    // Check if we want material folders
    auto ExportMaterialFolders = BatchRoot.empty() && SettingsManager::GetSetting("mdlmtlfolders") == "true";
    const auto MaterialsPath = BatchRoot.empty() ? std::string() : FileSystems::CombinePath(BatchRoot, "materials");


    // Only create if Model Images are enabled
    if (ExportImages)
    {
        // Create if not exists
        FileSystems::CreateDirectory(ImagesPath);
    }

    // Check it
    if (ImageSetting == "DDS")
    {
        ImageFormatType = ImageFormat::DDS_WithHeader;
    }
    else if (ImageSetting == "TGA")
    {
        ImageFormatType = ImageFormat::Standard_TGA;
    }
    else if (ImageSetting == "TIFF")
    {
        ImageFormatType = ImageFormat::Standard_TIFF;
    }

    // Check
    if (GenericModel != nullptr)
    {
        const bool ExportAllLods = SettingsManager::GetSetting("exportalllods") == "true";
        const auto BiggestLodIndex = ExportAllLods ? -1 : CoDXModelTranslator::CalculateBiggestLodIndex(GenericModel);
        if (!ExportAllLods && BiggestLodIndex < 0)
            return ExportGameResult::UnknownError;
        const auto ShouldWriteModel = [&](const std::string& Path)
        {
            return BatchRoot.empty() ? ShouldExportModel(Path) :
                (SettingsManager::GetSetting("skipprevmodel") != "true" || !ModelBatchResume::CompleteCast(Path + ".cast"));
        };

        // Prepare material images
        for (size_t LodIndex = 0; LodIndex < GenericModel->ModelLods.size(); ++LodIndex)
        {
            // Dependencies must follow the same LOD selection as the model files.
            if (!ExportAllLods && LodIndex != static_cast<size_t>(BiggestLodIndex))
                continue;
            auto& LOD = GenericModel->ModelLods[LodIndex];
            // Iterate over all materials for the lod
            for (auto& Material : LOD.Materials)
            {
                bool NewBatchMaterial = false;
                if (!BatchRoot.empty())
                {
                    const auto OriginalMaterial = Material.MaterialName;
                    Material.MaterialName = ModelExportNaming::Escape(Material.MaterialName);
                    nlohmann::json Bindings = nlohmann::json::array(), Parameters = nlohmann::json::array();
                    for (auto& Image : Material.Images)
                    {
                        const auto SourceName = Image.ImageName;
                        Image.ImageName = ModelExportNaming::Escape(Image.ImageName);
                        Bindings.push_back({{"Name",Image.ImageName},{"SourceName",SourceName},
                            {"File","../images/" + Image.ImageName + ImageExtension}, {"SemanticHash",Image.SemanticHash}});
                    }
                    for (const auto& Setting : Material.Settings)
                        Parameters.push_back({{"Name",Setting.Name},{"Type",Setting.Type},
                            {"Value",{Setting.Data[0],Setting.Data[1],Setting.Data[2],Setting.Data[3]}}});
                    const nlohmann::json Description = {{"Name",Material.MaterialName},{"SourceName",OriginalMaterial},
                        {"Techset",Material.TechsetName},{"SurfaceType",Material.SurfaceTypeName},{"Images",Bindings},{"Settings",Parameters}};
                    // One exported material per name; keep the first description.
                    Material.MaterialName = FlatMaterialExport::Save(MaterialsPath, Description, &NewBatchMaterial);
                }
                auto CompleteImagesPath = ImagesPath;
                auto CompleteImageRelativePath = ImageRelativePath;

                // Check if we want material folders
                if (ExportMaterialFolders)
                {
                    // Create a new Folder
                    CompleteImagesPath = FileSystems::CombinePath(ImagesPath, Material.MaterialName);
                    CompleteImageRelativePath = FileSystems::CombinePath(ImageRelativePath, Material.MaterialName) + "\\\\";
                    // Create if not exists
                    if (ExportImages || ExportImageNames)
                        FileSystems::CreateDirectory(CompleteImagesPath);
                }

                // Export image names if needed
                if (ExportImageNames && (BatchRoot.empty() || NewBatchMaterial))
                {
                    // Process Image Names
                    // Keep parameter/settings files beside this material's textures,
                    // including metadata-only exports. Flat exports retain the model folder.
                    ExportMaterialImageNames(Material, !BatchRoot.empty() ? MaterialsPath : (ExportMaterialFolders ? CompleteImagesPath : ExportPath));
                }
                if (ExportImages)
                {
                    // Process the material
                    ExportMaterialImages(Material, CompleteImagesPath, ImageExtension, ImageFormatType, MaterialsPath);
                }

                // Apply image paths
                for (auto& Image : Material.Images)
                {
                    // Append the relative path and image extension here, since we are done with these images
                    Image.ImageName = CompleteImageRelativePath + Image.ImageName + ImageExtension;
                }
            }
        }

        // Determine lod export type
        if (ExportAllLods)
        {
            // We should export all loaded lods from this xmodel
            auto LodCount = (uint32_t)GenericModel->ModelLods.size();

            // Iterate and convert
            for (uint32_t i = 0; i < LodCount; i++)
            {
                // Continue if we should not export this model (files already exist)
                if (ShouldWriteModel(FileSystems::CombinePath(ExportPath, ModelFileName(Model->AssetName) + Strings::Format("_LOD%d", i))))
                {
                    // Translate generic model to a WraithModel, then export
                    auto Result = CoDXModelTranslator::TranslateXModel(GenericModel, i);

                    // Check result and export
                    if (Result != nullptr)
                    {
                        Result->AssetName = ModelExportNaming::Stem(Model->AssetName) + Strings::Format("_LOD%d", i);
                        // Send off to exporter
                        ExportWraithModel(Result, ExportPath, !BatchRoot.empty());
                    }
                    else
                    {
                        // We failed
                        return ExportGameResult::UnknownError;
                    }
                }
            }
        }
        else
        {
            // We should export the biggest we can find
            // If the biggest > -1 translate
            if (BiggestLodIndex > -1)
            {
                // A single default export shares its stem with the folder and placement Name.
                const auto LodIndexSuffix = ModelExportNaming::LodSuffix(false,
                    SettingsManager::GetSetting("match_game_lod_index", "false") == "true", BiggestLodIndex);

                // Check if we should not export this model (files already exist)
                if (ShouldWriteModel(FileSystems::CombinePath(ExportPath, ModelFileName(Model->AssetName) + LodIndexSuffix)))
                {
                    // Translate generic model to a WraithModel, then export
                    const auto Result = CoDXModelTranslator::TranslateXModel(GenericModel, BiggestLodIndex);

                    // Check result and export
                    if (Result != nullptr)
                    {
                        Result->AssetName = ModelExportNaming::Stem(Model->AssetName) + LodIndexSuffix;
                        // Send off to exporter
                        ExportWraithModel(Result, ExportPath, !BatchRoot.empty());
                    }
                    else
                    {
                        // We failed
                        return ExportGameResult::UnknownError;
                    }
                }
            }
            else
            {
                // Failed, no loaded lods (Should be marked placeholder anyways)
                return ExportGameResult::UnknownError;
            }
        }

        // Check whether or not to export the hitbox model
        if (SettingsManager::GetSetting("exporthitbox") == "true")
        {
            // The hitbox result, if any
            std::unique_ptr<WraithModel> Result = nullptr;
            // Check the game
            switch (CoDAssets::GameID)
            {
            case SupportedGames::BlackOps3:
            case SupportedGames::BlackOps: Result = CoDXModelTranslator::TranslateXModelHitbox(GenericModel); break;
            }

            // Export if we have a reslt
            if (Result != nullptr)
            {
                // Export it
                Result->AssetName = ModelExportNaming::Stem(Model->AssetName) + "_HITBOX";
                ExportWraithModel(Result, ExportPath, !BatchRoot.empty());
            }
        }
    }
    else
    {
        // We failed
        return ExportGameResult::UnknownError;
    }

    // Success, unless specific error
    return ExportGameResult::Success;
}

ExportGameResult CoDAssets::ExportImageAsset(const CoDImage_t* Image, const std::string& ExportPath, const std::string& ImageExtension)
{
    // Grab the full image path, if it doesn't exist convert it!
    auto FullImagePath = FileSystems::CombinePath(ExportPath, Image->AssetName + ImageExtension);
    // Check if we want to skip previous images
    auto SkipPrevImages = SettingsManager::GetSetting("skipprevimg") == "true";

    // Check if it exists and if we want to skip it or not
    if (!FileSystems::FileExists(FullImagePath) || !SkipPrevImages)
    {
        // Buffer for the image (Loaded via the global game handler)
        std::unique_ptr<XImageDDS> ImageData = nullptr;

        // Check what mode we're in
        if (Image->IsFileEntry)
        {
            // Read from specific handler (By game)
            switch (CoDAssets::GameID)
            {
            case SupportedGames::WorldAtWar:
            case SupportedGames::ModernWarfare:
            case SupportedGames::ModernWarfare2:
            case SupportedGames::ModernWarfare3:
            case SupportedGames::BlackOps:
                ImageData = IWDSupport::ReadImageFile(Image);
                break;

            case SupportedGames::BlackOps2:
                ImageData = IPAKSupport::ReadImageFile(Image);
                break;
            case SupportedGames::BlackOps3:
            case SupportedGames::BlackOps4:
            case SupportedGames::BlackOpsCW:
            case SupportedGames::ModernWarfare4:
            case SupportedGames::ModernWarfare5:
                ImageData = XPAKSupport::ReadImageFile(Image);
                break;
            }
        }
        else
        {
            // Read from game
            switch (CoDAssets::GameID)
            {
            case SupportedGames::BlackOps3: ImageData                = GameBlackOps3::ReadXImage(Image); break;
            case SupportedGames::BlackOps4: ImageData                = GameBlackOps4::ReadXImage(Image); break;
            case SupportedGames::BlackOpsCW: ImageData               = GameBlackOpsCW::ReadXImage(Image); break;
            case SupportedGames::Ghosts: ImageData                   = GameGhosts::ReadXImage(Image); break;
            case SupportedGames::AdvancedWarfare: ImageData          = GameAdvancedWarfare::ReadXImage(Image); break;
            case SupportedGames::ModernWarfareRemastered: ImageData  = GameModernWarfareRM::ReadXImage(Image); break;
            case SupportedGames::ModernWarfare2Remastered: ImageData = GameModernWarfare2RM::ReadXImage(Image); break;
            case SupportedGames::InfiniteWarfare: ImageData          = GameInfiniteWarfare::ReadXImage(Image); break;
            case SupportedGames::ModernWarfare4: ImageData           = GameModernWarfare4::ReadXImage(Image); break;
            case SupportedGames::ModernWarfare5: ImageData           = GameModernWarfare5::ReadXImage(Image); break;
            case SupportedGames::ModernWarfare6: ImageData           = GameModernWarfare6::ReadXImage(Image); break;
            case SupportedGames::WorldWar2: ImageData                = GameWorldWar2::ReadXImage(Image); break;
            case SupportedGames::Vanguard: ImageData                 = GameVanguard::ReadXImage(Image); break;
            }
        }

        // Grab the image format type
        auto ImageFormatType = ImageFormat::Standard_PNG;
        // Check setting
        auto ImageSetting = SettingsManager::GetSetting("exportimg", "PNG");

        // Check it
        if (ImageSetting == "DDS")
        {
            ImageFormatType = ImageFormat::DDS_WithHeader;
        }
        else if (ImageSetting == "TGA")
        {
            ImageFormatType = ImageFormat::Standard_TGA;
        }
        else if (ImageSetting == "TIFF")
        {
            ImageFormatType = ImageFormat::Standard_TIFF;
        }

        // Check if we got it
        if (ImageData != nullptr)
        {
            // Convert it to a file or just write the DDS data raw
            if (ImageFormatType == ImageFormat::DDS_WithHeader)
            {
                // Since this can throw, wrap it in an exception handler
                try
                {
                    // Just write the buffer
                    auto Writer = BinaryWriter();
                    // Make the file
                    Writer.Create(FullImagePath);
                    // Write the DDS buffer
                    Writer.Write((const int8_t*)ImageData->DataBuffer, ImageData->DataSize);
                }
                catch (...)
                {
                    // Nothing, this means that something is already accessing the image
                }
            }
            else
            {
                // Convert it, this method is a nothrow
                Image::ConvertImageMemory(ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader, FullImagePath, ImageFormatType, ImageData->ImagePatchType);
            }
        }
    }

    // Success, unless specific error
    return ExportGameResult::Success;
}

ExportGameResult CoDAssets::ExportSoundAsset(const CoDSound_t* Sound, const std::string& ExportPath, const std::string& SoundExtension)
{
    // Grab the full sound path, if it doesn't exist convert it!
    auto FullSoundPath = FileSystems::CombinePath(ExportPath, Sound->AssetName + SoundExtension);
    // Check if we want to skip previous Sounds
    auto SkipPrevSound = SettingsManager::GetSetting("skipprevsound") == "true";

    // Check if it exists
    if (!FileSystems::FileExists(FullSoundPath) || !SkipPrevSound)
    {
        // Holds universal sound data
        std::unique_ptr<XSound> SoundData = nullptr;

        // Attempt to load it based on game
        switch (CoDAssets::GameID)
        {
        case SupportedGames::BlackOps2:
        case SupportedGames::BlackOps3:
        case SupportedGames::BlackOps4:
        case SupportedGames::InfiniteWarfare:
            SoundData = SABSupport::LoadSound(Sound);
            break;
        case SupportedGames::BlackOpsCW:
            SoundData = GameBlackOpsCW::ReadXSound(Sound);
            break;
        case SupportedGames::Ghosts:
        case SupportedGames::AdvancedWarfare:
        case SupportedGames::ModernWarfareRemastered:
        case SupportedGames::ModernWarfare2Remastered:
        case SupportedGames::WorldWar2:
        case SupportedGames::WorldAtWar:
        case SupportedGames::ModernWarfare:
        case SupportedGames::ModernWarfare2:
        case SupportedGames::ModernWarfare3:
            SoundData = GameWorldWar2::ReadXSound(Sound);
            break;
        case SupportedGames::ModernWarfare4:
            if(Sound->IsFileEntry)
                SoundData = SABSupport::LoadOpusSound(Sound);
            else
                SoundData = GameVanguard::ReadXSound(Sound);
            break;
        case SupportedGames::ModernWarfare5:
            if (Sound->IsFileEntry)
                SoundData = SABSupport::LoadOpusSound(Sound);
            else
                SoundData = GameModernWarfare5::ReadXSound(Sound);
            break;
        case SupportedGames::ModernWarfare6:
            SoundData = GameModernWarfare6::ReadXSound(Sound);
            break;
        case SupportedGames::Vanguard:
            if (Sound->IsFileEntry)
                SoundData = SABSupport::LoadOpusSound(Sound);
            else
                SoundData = GameVanguard::ReadXSound(Sound);
            break;
        }

        // Grab the image format type
        auto SoundFormatType = SoundFormat::Standard_WAV;
        // Check setting
        auto SoundSetting = SettingsManager::GetSetting("exportsnd", "WAV");

        // Check it
        if (SoundSetting == "FLAC")
        {
            SoundFormatType = SoundFormat::Standard_FLAC;
        }

        // Check if we got it
        if (SoundData != nullptr)
        {
            // Check what format the DATA is, and see if we need to transcode
            if (((SoundData->DataType == SoundDataTypes::FLAC_WithHeader && SoundFormatType == SoundFormat::Standard_FLAC) || SoundData->DataType == SoundDataTypes::WAV_WithHeader && SoundFormatType == SoundFormat::Standard_WAV) || CoDAssets::GameID == SupportedGames::WorldAtWar)
            {
                // We have an already-prepared sound buffer, just write it
                // Since this can throw, wrap it in an exception handler
                try
                {
                    // Just write the buffer
                    auto Writer = BinaryWriter();
                    // Make the file
                    Writer.Create(FullSoundPath);
                    // Write the Sound buffer
                    Writer.Write((const int8_t*)SoundData->DataBuffer, SoundData->DataSize);
                }
                catch (...)
                {
                    // Nothing, this means that something is already accessing the sound
                }
            }
            else
            {
                // We must convert it
                auto InFormat = (SoundData->DataType == SoundDataTypes::FLAC_WithHeader) ? SoundFormat::FLAC_WithHeader : SoundFormat::WAV_WithHeader;
                // Convert the asset
                Sound::ConvertSoundMemory(SoundData->DataBuffer, SoundData->DataSize, InFormat, FullSoundPath, SoundFormatType);
            }
        }
    }

    // Success, unless specific error
    return ExportGameResult::Success;
}

ExportGameResult CoDAssets::ExportRawfileAsset(const CoDRawFile_t* Rawfile, const std::string& ExportPath)
{
    if (CoDAssets::GameID == SupportedGames::BlackOpsCW && Rawfile->ResearchPoolIndex != UINT32_MAX)
        return GameBlackOpsCW::ExportResearchPool(Rawfile, ExportPath)
            ? ExportGameResult::Success : ExportGameResult::UnknownError;
    // Read from specific handler (By game)
    switch (CoDAssets::GameID)
    {
    case SupportedGames::BlackOps:
        // Send to generic translator, Black Ops does not compress the anim trees, but does compress the GSCs
        CoDRawfileTranslator::TranslateRawfile(Rawfile, ExportPath, false, true);
        break;
    case SupportedGames::BlackOps2:
    case SupportedGames::BlackOps3:
    case SupportedGames::BlackOps4:
        // Send to generic translator, these games compress the anim trees
        CoDRawfileTranslator::TranslateRawfile(Rawfile, ExportPath, true, false);
        break;
    case SupportedGames::ModernWarfare4:
        // Send to MW Raw File Extractor (SAB Files)
        GameModernWarfare4::TranslateRawfile(Rawfile, ExportPath);
        break;
    case SupportedGames::ModernWarfare5:
        // Send to MW Raw File Extractor (SAB Files)
        GameModernWarfare5::TranslateRawfile(Rawfile, ExportPath);
        break;
    case SupportedGames::Vanguard:
        // Send to VG Raw File Extractor (SAB Files)
        GameVanguard::TranslateRawfile(Rawfile, ExportPath);
        break;
    }

    // Success, unless specific error
    return ExportGameResult::Success;
}

ExportGameResult CoDAssets::ExportTerrainAsset(const CoDTerrain_t* Terrain, const std::string& ExportPath,
    const std::function<void(uint32_t)>& ReportProgress)
{
    if (CoDAssets::GameID != SupportedGames::BlackOpsCW ||
        CoDAssets::GameInstance == nullptr ||
        Terrain->AssetPointer == 0 ||
        Terrain->AssetSize <= 0 ||
        Terrain->AssetSize > UINT32_MAX)
    {
        return ExportGameResult::UnknownError;
    }

    const auto HeaderPath = FileSystems::CombinePath(ExportPath, "header.terraingfx.bin");
    const auto MetadataPath = FileSystems::CombinePath(ExportPath, "terraingfx.json");
    // Greyhound is the source-data producer. These are intentionally fixed so
    // a capture cannot silently omit data needed by an external reconstructor.
    const bool SourceOnly = true;
    const bool SkipPrevious = SettingsManager::GetSetting("skipprevterrain", "false") == "true";
    // Every terrain export is archival source data. It retains material
    // dependencies as well as the raw terrain probes:
    // _images.txt preserves semantic-to-image links, _settings.txt preserves
    // readable material parameters, and ExportMaterialAsset writes every image
    // referenced by the captured slot material.  This remains an export-only
    // operation; it never generates or installs a BO3 GDT.
    const bool ExportMaterialDependencies = true;
    // Dependency identity and painted-slot mapping need the capture tables.
    const bool CaptureResearch = true;
    const bool ExportTerrainTiles = true;
    if (SkipPrevious && FileSystems::FileExists(HeaderPath) && FileSystems::FileExists(MetadataPath) &&
        !CaptureResearch)
    {
        return ExportGameResult::Success;
    }

    uintptr_t BytesRead = 0;
    auto Header = CoDAssets::GameInstance->Read(
        Terrain->AssetPointer,
        static_cast<uintptr_t>(Terrain->AssetSize),
        BytesRead);

    if (Header == nullptr || BytesRead != static_cast<uintptr_t>(Terrain->AssetSize))
    {
        delete[] Header;
        return ExportGameResult::UnknownError;
    }

    auto HeaderWriter = BinaryWriter();
    if (!HeaderWriter.Create(HeaderPath))
    {
        delete[] Header;
        return ExportGameResult::UnknownError;
    }
    HeaderWriter.Write(Header, static_cast<uint32_t>(BytesRead));
    HeaderWriter.Close();

    auto ReadHeaderUInt64 = [Header, BytesRead](size_t Offset) -> uint64_t
    {
        uint64_t Value = 0;
        if (Offset <= BytesRead && sizeof(Value) <= BytesRead - Offset)
            std::memcpy(&Value, Header + Offset, sizeof(Value));
        return Value;
    };

    auto ReadHeaderUInt32 = [Header, BytesRead](size_t Offset) -> uint32_t
    {
        uint32_t Value = 0;
        if (Offset <= BytesRead && sizeof(Value) <= BytesRead - Offset)
            std::memcpy(&Value, Header + Offset, sizeof(Value));
        return Value;
    };

    auto ReadHeaderFloat = [Header, BytesRead](size_t Offset) -> float
    {
        float Value = 0.0f;
        if (Offset <= BytesRead && sizeof(Value) <= BytesRead - Offset)
            std::memcpy(&Value, Header + Offset, sizeof(Value));
        return Value;
    };

    constexpr uint64_t MaximumCaptureBytes = 16ull * 1024ull * 1024ull;
    auto CaptureBuffer = [&](uint64_t Pointer, uint64_t Count, uint64_t ElementSize,
        const std::string& FileName, const std::string& Interpretation) -> nlohmann::json
    {
        nlohmann::json Result = {
            {"file", FileName},
            {"pointer", Strings::Format("0x%llX", Pointer)},
            {"count", Count},
            {"element_size", ElementSize},
            {"interpretation", Interpretation},
            {"status", "not_attempted"}
        };

        if (Pointer == 0 || Count == 0 || ElementSize == 0)
        {
            Result["status"] = "empty";
            return Result;
        }

        if (Count > MaximumCaptureBytes / ElementSize)
        {
            Result["status"] = "rejected_size_limit";
            return Result;
        }

        const uint64_t BufferSize = Count * ElementSize;
        uintptr_t ChildBytesRead = 0;
        auto ChildBuffer = CoDAssets::GameInstance->Read(
            static_cast<uintptr_t>(Pointer), static_cast<uintptr_t>(BufferSize), ChildBytesRead);

        if (ChildBuffer == nullptr || ChildBytesRead != static_cast<uintptr_t>(BufferSize))
        {
            delete[] ChildBuffer;
            Result["status"] = "read_failed";
            Result["bytes_requested"] = BufferSize;
            Result["bytes_read"] = ChildBytesRead;
            return Result;
        }

        auto Writer = BinaryWriter();
        const auto OutputPath = FileSystems::CombinePath(ExportPath, FileName);
        if (!Writer.Create(OutputPath))
        {
            delete[] ChildBuffer;
            Result["status"] = "write_failed";
            return Result;
        }

        Writer.Write(ChildBuffer, static_cast<uint32_t>(BufferSize));
        Writer.Close();
        delete[] ChildBuffer;

        Result["status"] = "captured";
        Result["bytes"] = BufferSize;
        return Result;
    };

    const uint64_t Pointer0010 = ReadHeaderUInt64(0x10);
    const uint64_t Count0030 = ReadHeaderUInt64(0x30);
    const uint64_t Pointer0038 = ReadHeaderUInt64(0x38);
    const uint64_t Count0040 = ReadHeaderUInt64(0x40);
    const uint64_t Pointer0048 = ReadHeaderUInt64(0x48);
    const uint64_t Pointer0108 = ReadHeaderUInt64(0x108);
    const uint64_t Count0110 = ReadHeaderUInt64(0x110);
    const uint64_t Pointer0118 = ReadHeaderUInt64(0x118);

    nlohmann::json Captures = nlohmann::json::array();
    if (CaptureResearch)
    {
        Captures.push_back(CaptureBuffer(Pointer0038, Count0030, 8,
            "array_0038_u64.bin", "inferred 8-byte entries from adjacent pointer distance"));
        Captures.push_back(CaptureBuffer(Pointer0048, Count0040, 4,
            "array_0048_u32.bin", "inferred 4-byte entries from aligned allocation distance"));

        const uint64_t AdjacentSpan = Pointer0118 > Pointer0108 ? Pointer0118 - Pointer0108 : 0;
        if (AdjacentSpan >= 8 && AdjacentSpan <= 4096)
        {
            Captures.push_back(CaptureBuffer(Pointer0108, AdjacentSpan, 1,
                "block_0108_to_0118.bin", "bounded span between adjacent header pointers"));
        }
        else
        {
            Captures.push_back({
                {"file", "block_0108_to_0118.bin"},
                {"pointer", Strings::Format("0x%llX", Pointer0108)},
                {"status", "rejected_non_adjacent_pointers"}
            });
        }

        // The 0x108 block stops exactly where this one starts, which is why
        // the bytes at 0x118 went unread for so long. They are Count0110
        // records of twelve GfxImage pointers -- four (gloss, colour, normal)
        // triples each. On mp_dune one triple carries a real layer material
        // whose normal and gloss the 0x38 image array never lists, so this is
        // a second source of terrain layer textures. Keep the raw bytes: the
        // twelve-pointer stride is measured on two captures, not documented.
        if (Pointer0118 != 0 && Count0110 > 0 && Count0110 <= 64)
        {
            Captures.push_back(CaptureBuffer(Pointer0118, Count0110 * 12, 8,
                "layer_material_images.bin",
                "header 0x118: Count0110 x 4 (gloss, colour, normal) GfxImage "
                "pointer triples; decoded into terrain_layer_material_images"));
        }
    }

    nlohmann::json EntityProbe = {
        {"status", CaptureResearch ? "not_attempted" : "disabled"},
        {"table_pointer", Strings::Format("0x%llX", Pointer0108)},
        {"record_count", Count0110}
    };
    if (CaptureResearch && Pointer0108 != 0 && Count0110 > 0 && Count0110 <= 1024)
    {
        const uint64_t EntityTableSpan = Pointer0118 > Pointer0108 ? Pointer0118 - Pointer0108 : 0;
        if (EntityTableSpan >= Count0110 * 0x20 && EntityTableSpan <= MaximumCaptureBytes &&
            EntityTableSpan % Count0110 == 0)
        {
            const uint64_t EntityRecordStride = EntityTableSpan / Count0110;
            uintptr_t EntityBytesRead = 0;
            auto EntityBuffer = CoDAssets::GameInstance->Read(
                static_cast<uintptr_t>(Pointer0108), static_cast<uintptr_t>(EntityTableSpan), EntityBytesRead);
            if (EntityBuffer != nullptr && EntityBytesRead == EntityTableSpan)
            {
                auto ReadEntityUInt32 = [EntityBuffer, EntityTableSpan](size_t Offset) -> uint32_t
                {
                    uint32_t Value = 0;
                    if (Offset <= EntityTableSpan && sizeof(Value) <= EntityTableSpan - Offset)
                        std::memcpy(&Value, EntityBuffer + Offset, sizeof(Value));
                    return Value;
                };
                auto ReadEntityUInt64 = [EntityBuffer, EntityTableSpan](size_t Offset) -> uint64_t
                {
                    uint64_t Value = 0;
                    if (Offset <= EntityTableSpan && sizeof(Value) <= EntityTableSpan - Offset)
                        std::memcpy(&Value, EntityBuffer + Offset, sizeof(Value));
                    return Value;
                };

                const uint64_t CandidateRecordsPointer = ReadEntityUInt64(0x00);
                const uint32_t CandidateRecordStride = ReadEntityUInt32(0x08);
                const uint32_t CandidateRecordCount = ReadEntityUInt32(0x0C);
                const uint64_t CandidateAssetPointer = ReadEntityUInt64(0x10);
                EntityProbe = {
                    {"status", "initial_entity_hypothesis_rejected_descriptor_decoded"},
                    {"table_pointer", Strings::Format("0x%llX", Pointer0108)},
                    {"record_count", Count0110},
                    {"record_stride", EntityRecordStride},
                    {"design_correlation", "96-byte nested payload contains only scalar 0/1 values; this does not resemble mesh vertices or quadtree nodes and is retained as an unknown descriptor/constant block"},
                    {"first_record", {
                        {"candidate_records_pointer_0000", Strings::Format("0x%llX", CandidateRecordsPointer)},
                        {"candidate_record_stride_0008", CandidateRecordStride},
                        {"candidate_record_count_000c", CandidateRecordCount},
                        {"candidate_asset_pointer_0010", Strings::Format("0x%llX", CandidateAssetPointer)},
                        {"value_0020", ReadEntityUInt32(0x20)},
                        {"value_0024", ReadEntityUInt32(0x24)},
                        {"value_002c", ReadEntityUInt32(0x2C)},
                        {"value_0030", ReadEntityUInt32(0x30)},
                        {"value_0034", ReadEntityUInt32(0x34)}
                    }}
                };

                if (CandidateRecordsPointer != 0 && CandidateRecordStride >= 8 && CandidateRecordStride <= 4096 &&
                    CandidateRecordCount > 0 && CandidateRecordCount <= 4096)
                {
                    auto NestedCapture = CaptureBuffer(CandidateRecordsPointer, CandidateRecordCount,
                        CandidateRecordStride, "entity_0000_candidate_records.bin",
                        "bounded nested payload; initial terrain-entity interpretation rejected after scalar inspection");
                    Captures.push_back(NestedCapture);
                    EntityProbe["nested_capture"] = NestedCapture;
                }

                if (CandidateAssetPointer != 0)
                {
                    constexpr uint64_t CandidateMaterialHeaderSize = 0x158;
                    auto CandidateHeaderCapture = CaptureBuffer(CandidateAssetPointer, CandidateMaterialHeaderSize, 1,
                        "candidate_asset_0010_header.bin",
                        "bounded candidate asset header tested against Greyhound BOCWXMaterialEx layout");
                    Captures.push_back(CandidateHeaderCapture);
                    EntityProbe["candidate_asset_header_capture"] = CandidateHeaderCapture;

                    uintptr_t CandidateHeaderBytesRead = 0;
                    auto CandidateHeader = CoDAssets::GameInstance->Read(static_cast<uintptr_t>(CandidateAssetPointer),
                        static_cast<uintptr_t>(CandidateMaterialHeaderSize), CandidateHeaderBytesRead);
                    if (CandidateHeader != nullptr && CandidateHeaderBytesRead == CandidateMaterialHeaderSize)
                    {
                        auto ReadCandidateUInt64 = [CandidateHeader](size_t Offset) -> uint64_t
                        {
                            uint64_t Value = 0;
                            std::memcpy(&Value, CandidateHeader + Offset, sizeof(Value));
                            return Value;
                        };
                        const uint64_t CandidateName = ReadCandidateUInt64(0x00) & 0x0FFFFFFFFFFFFFFFull;
                        const uint64_t CandidateTechsetPointer = ReadCandidateUInt64(0x28);
                        const uint64_t CandidateImageTablePointer = ReadCandidateUInt64(0x30);
                        const uint64_t CandidateConstantBufferSize = ReadCandidateUInt64(0x110);
                        const uint64_t CandidateConstantBufferPointer = ReadCandidateUInt64(0x118);
                        const uint8_t CandidateImageCount = CandidateHeader[0x148];
                        const bool MaterialLayoutPlausible = CandidateName != 0 && CandidateTechsetPointer != 0 &&
                            CandidateImageCount <= 128 && CandidateConstantBufferSize <= MaximumCaptureBytes &&
                            (CandidateImageCount == 0 || CandidateImageTablePointer != 0) &&
                            (CandidateConstantBufferSize == 0 || CandidateConstantBufferPointer != 0);

                        EntityProbe["candidate_asset_layout_test"] = {
                            {"layout", "Greyhound BOCWXMaterialEx (0x158 bytes)"},
                            {"status", MaterialLayoutPlausible ? "plausible_material_layout" : "layout_not_confirmed"},
                            {"name_hash", Strings::Format("0x%llX", CandidateName)},
                            {"techset_pointer_0028", Strings::Format("0x%llX", CandidateTechsetPointer)},
                            {"image_table_pointer_0030", Strings::Format("0x%llX", CandidateImageTablePointer)},
                            {"constant_buffer_size_0110", CandidateConstantBufferSize},
                            {"constant_buffer_pointer_0118", Strings::Format("0x%llX", CandidateConstantBufferPointer)},
                            {"image_count_0148", CandidateImageCount}
                        };

                        if (MaterialLayoutPlausible && CandidateConstantBufferSize > 0)
                        {
                            auto ConstantCapture = CaptureBuffer(CandidateConstantBufferPointer,
                                CandidateConstantBufferSize, 1, "candidate_asset_0010_constant_buffer.bin",
                                "candidate constant-buffer payload bounded by BOCWXMaterialEx fields");
                            Captures.push_back(ConstantCapture);
                            EntityProbe["candidate_asset_layout_test"]["constant_buffer_capture"] = ConstantCapture;
                        }
                        if (MaterialLayoutPlausible && CandidateImageCount > 0)
                        {
                            auto ImageTableCapture = CaptureBuffer(CandidateImageTablePointer,
                                CandidateImageCount, 0x18, "candidate_asset_0010_image_table.bin",
                                "candidate image table bounded by BOCWXMaterialEx ImageCount and 0x18-byte entries");
                            Captures.push_back(ImageTableCapture);
                            EntityProbe["candidate_asset_layout_test"]["image_table_capture"] = ImageTableCapture;
                        }
                    }
                    else
                    {
                        EntityProbe["candidate_asset_layout_test"] = {{"status", "header_read_failed"}};
                    }
                    delete[] CandidateHeader;
                }
            }
            else
            {
                EntityProbe["status"] = "table_read_failed";
            }
            delete[] EntityBuffer;
        }
        else
        {
            EntityProbe["status"] = "rejected_table_span";
            EntityProbe["table_span"] = EntityTableSpan;
        }
    }

    // Preserve the engine's per-tile adaptive triangulation as source data.
    struct ShippedTile
    {
        uint32_t Tile;
        uint32_t TileX;
        uint32_t TileY;
        float MinimumX;
        float MinimumY;
        std::vector<uint32_t> Packed;
    };
    std::vector<ShippedTile> ShippedTiles;
    std::vector<std::array<float, 2>> ShippedTileBoundsMinimum;
    uint64_t ShippedTilesReused = 0;
    struct ShippedCoarseTile
    {
        uint32_t Level;
        uint32_t Tile;
        uint32_t TileX;
        uint32_t TileY;
        float MinimumX;
        float MinimumY;
        std::vector<uint32_t> PackedXY;
        std::vector<uint32_t> Extra;
        std::vector<uint16_t> Indices;
    };
    std::vector<ShippedCoarseTile> ShippedCoarseTiles;

    nlohmann::json ImageBindings = nlohmann::json::array();
    nlohmann::json LoadedTerrainImageCandidates = nlohmann::json::array();
    std::string ImageBindingsStatus = "disabled";
    std::vector<uint16_t> HeightSamples;
    uint32_t HeightWidth = 0;
    uint32_t HeightHeight = 0;
    uint32_t HeightBindingId = 0;
    uint64_t HeightNameHash = 0;
    std::string BaseColorTextureUri;
    uint32_t BaseColorBindingId = 0;
    uint64_t BaseColorNameHash = 0;
    std::vector<uint8_t> TerrainNormalXYSamples;
    uint32_t TerrainNormalWidth = 0;
    uint32_t TerrainNormalHeight = 0;
    uint32_t TerrainNormalBindingId = 0;
    uint64_t TerrainNormalNameHash = 0;
    std::string TerrainNormalTextureUri;
    std::string SurfaceParametersTextureUri;
    std::string MaterialIndexTextureUri;
    std::string TerrainControlTextureUri;
    std::vector<uint64_t> TerrainImagePointers;
    std::vector<uint32_t> TerrainImageBindingIds;
    std::vector<uint8_t> MaterialIndexSamples;
    uint32_t MaterialIndexWidth = 0;
    uint32_t MaterialIndexHeight = 0;
    uint32_t MaterialIndexBindingId = 0;
    std::vector<uint32_t> TerrainControlSamples;
    uint32_t TerrainControlWidth = 0;
    uint32_t TerrainControlHeight = 0;
    uint32_t TerrainControlBindingId = 0;
    // Binding 10 expanded to one byte per unified-height texel: 1 solid, 0 hole.
    std::vector<uint8_t> TerrainSolidMask;
    uint32_t TerrainSolidWidth = 0;
    uint32_t TerrainSolidHeight = 0;
    uint64_t TerrainHoleTexels = 0;
    uint32_t TerrainHoleMinimumX = 0;
    uint32_t TerrainHoleMinimumY = 0;
    uint32_t TerrainHoleMaximumX = 0;
    uint32_t TerrainHoleMaximumY = 0;
    uint32_t ResolvedBindingNameCount = 0;
    nlohmann::json TerrainHoles = nlohmann::json::object();
    nlohmann::json TerrainQuadtree = nlohmann::json::object();
    uint64_t LegalMaterialSlotCount = 0;
    uint64_t SlotMaterialTablePointer = 0;
    // Measured on two captures: the slot record is 0x130 bytes and begins with
    // the material pointer. Everything after offset 8 is still unread.
    constexpr uint64_t SlotMaterialRecordStride = 0x130;
    uint64_t MeasuredMaterialIndexOffset = 0;
    bool MeasuredMaterialIndexOffsetValid = false;
    nlohmann::json SlotPaintedTexels = nlohmann::json::object();
    bool RootTileBoundsRead = false;
    float RootTileBoundsMinX = 0.0f;
    float RootTileBoundsMinY = 0.0f;
    bool RuntimeHeightDecodeValidated = false;
    float RuntimeTerrainOriginX = 0.0f;
    float RuntimeTerrainOriginY = 0.0f;
    float RuntimeTerrainCellSize = 0.0f;
    float RuntimeHeightBias = 0.0f;
    float RuntimeHeightRange = 0.0f;
    float RuntimeMaximumTextureCoordinate = 0.0f;
    uint16_t RuntimeHeightWidth = 0;
    uint16_t RuntimeHeightHeight = 0;
    static_assert(sizeof(BOCWGfxImage) == 0xD0, "Unexpected BOCW GfxImage size");
    if (CaptureResearch && Count0030 == Count0040 && Count0030 > 0 && Count0030 <= 4096)
    {
        const auto ImagesDirectory = FileSystems::CombinePath(ExportPath, "terrain_images");
        const auto LayersDirectory = FileSystems::CombinePath(ExportPath, "terrain_layers");
        FileSystems::CreateDirectory(ImagesDirectory);
        FileSystems::CreateDirectory(LayersDirectory);

        uintptr_t ImagePointerBytesRead = 0;
        uintptr_t BindingIdBytesRead = 0;
        const uint64_t ImagePointerBytes = Count0030 * sizeof(uint64_t);
        const uint64_t BindingIdBytes = Count0040 * sizeof(uint32_t);
        auto ImagePointerBuffer = CoDAssets::GameInstance->Read(
            static_cast<uintptr_t>(Pointer0038), static_cast<uintptr_t>(ImagePointerBytes), ImagePointerBytesRead);
        auto BindingIdBuffer = CoDAssets::GameInstance->Read(
            static_cast<uintptr_t>(Pointer0048), static_cast<uintptr_t>(BindingIdBytes), BindingIdBytesRead);

        if (ImagePointerBuffer != nullptr && BindingIdBuffer != nullptr &&
            ImagePointerBytesRead == ImagePointerBytes && BindingIdBytesRead == BindingIdBytes)
        {
            ImageBindingsStatus = "captured";
            for (uint64_t i = 0; i < Count0030; i++)
            {
                uint64_t ImagePointer = 0;
                uint32_t BindingId = 0;
                std::memcpy(&ImagePointer, ImagePointerBuffer + i * sizeof(uint64_t), sizeof(ImagePointer));
                std::memcpy(&BindingId, BindingIdBuffer + i * sizeof(uint32_t), sizeof(BindingId));
                TerrainImagePointers.push_back(ImagePointer);
                TerrainImageBindingIds.push_back(BindingId);

                nlohmann::json Binding = {
                    {"index", i},
                    {"binding_id", BindingId},
                    {"image_pointer", Strings::Format("0x%llX", ImagePointer)},
                    {"header_status", "not_attempted"},
                    {"dds_status", "not_attempted"}
                };

                uintptr_t ImageHeaderBytesRead = 0;
                auto ImageHeaderBuffer = CoDAssets::GameInstance->Read(
                    static_cast<uintptr_t>(ImagePointer), sizeof(BOCWGfxImage), ImageHeaderBytesRead);
                if (ImageHeaderBuffer == nullptr || ImageHeaderBytesRead != sizeof(BOCWGfxImage))
                {
                    delete[] ImageHeaderBuffer;
                    Binding["header_status"] = "read_failed";
                    ImageBindings.push_back(Binding);
                    continue;
                }

                BOCWGfxImage ImageInfo{};
                std::memcpy(&ImageInfo, ImageHeaderBuffer, sizeof(ImageInfo));
                const uint64_t ImageNameHash = ImageInfo.NamePtr & 0x0FFFFFFFFFFFFFFFull;
                const auto ImageBaseName = Strings::Format("binding_%03u_ximage_%llx", BindingId, ImageNameHash);

                // Terrain image name hashes are ordinary asset name hashes. Resolving them
                // through Greyhound's own cache names every source-layer family, and the
                // engine's _c/_n/_h/_r/_g/_sm/_o suffixes then give the channel semantics.
                // File names stay hash-based so existing exports and tools keep matching.
                const auto ResolvedName = GameBlackOpsCW::AssetNameCache.NameDatabase.find(ImageNameHash);
                if (ResolvedName != GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                {
                    Binding["resolved_name"] = ResolvedName->second;
                    ResolvedBindingNameCount++;
                }
                else
                {
                    Binding["resolved_name_status"] = "unresolved";
                }

                // Map-wide roles come from the engine's own names. Binding ids are not
                // stable across maps: the composites sit at 7-13 on one captured map and
                // 26-32 on another, so the id rules below are only a fallback for images
                // whose name hash could not be resolved.
                const auto BindingName = Binding.value("resolved_name", std::string());
                const bool BindingUnnamed = BindingName.empty();
                auto BindingNameHas = [&BindingName](const char* Needle)
                {
                    return BindingName.find(Needle) != std::string::npos;
                };
                auto BindingNameEndsWith = [&BindingName](const char* Suffix)
                {
                    const size_t Length = std::strlen(Suffix);
                    return BindingName.size() >= Length &&
                        BindingName.compare(BindingName.size() - Length, Length, Suffix) == 0;
                };
                const bool RoleCombined0 = BindingNameHas("terrain_combined_maps") && BindingNameEndsWith("_0");
                const bool RoleCombined1 = BindingNameHas("terrain_combined_maps") && BindingNameEndsWith("_1");
                const bool RoleColorMap = BindingNameHas("terrain_color_map");
                const bool RoleIndexMap = BindingNameHas("terrain_index_maps");
                const bool RoleMaskMap = BindingNameHas("terrain_mask_maps");
                // Source-layer families are all i_t<n>_ prefixed.
                const bool SourceLayerBinding = BindingUnnamed
                    ? BindingId >= 15
                    : BindingName.compare(0, 3, "i_t") == 0;
                if (!BindingUnnamed)
                {
                    const char* RoleName =
                        RoleCombined0 ? "terrain_combined_map_0" :
                        RoleCombined1 ? "terrain_combined_map_1" :
                        RoleColorMap ? "terrain_color_map" :
                        RoleIndexMap ? "terrain_index_map" :
                        RoleMaskMap ? "terrain_mask_map" :
                        BindingNameHas("terrain_height_maps") ? "terrain_height_map" :
                        SourceLayerBinding ? "source_layer_resource" : nullptr;
                    if (RoleName != nullptr)
                        Binding["named_role"] = RoleName;
                }

                const auto HeaderFileName = ImageBaseName + ".gfximage.bin";
                const auto MipsFileName = ImageBaseName + ".mips.bin";
                const auto DdsFileName = ImageBaseName + ".dds";

                auto ImageHeaderWriter = BinaryWriter();
                if (ImageHeaderWriter.Create(FileSystems::CombinePath(ImagesDirectory, HeaderFileName)))
                {
                    ImageHeaderWriter.Write(ImageHeaderBuffer, static_cast<uint32_t>(sizeof(BOCWGfxImage)));
                    ImageHeaderWriter.Close();
                    Binding["header_status"] = "captured";
                    Binding["header_file"] = FileSystems::CombinePath("terrain_images", HeaderFileName);
                }
                else
                {
                    Binding["header_status"] = "write_failed";
                }
                delete[] ImageHeaderBuffer;

                Binding["name_hash"] = Strings::Format("0x%llX", ImageNameHash);
                Binding["image_format"] = ImageInfo.ImageFormat;
                Binding["width"] = ImageInfo.LoadedMipWidth;
                Binding["height"] = ImageInfo.LoadedMipHeight;
                Binding["loaded_mip_size"] = ImageInfo.LoadedMipSize;
                Binding["mip_count"] = ImageInfo.GfxMipMaps;
                Binding["loaded_mip_pointer"] = Strings::Format("0x%llX", ImageInfo.LoadedMipPtr);
                Binding["mip_table_pointer"] = Strings::Format("0x%llX", ImageInfo.GfxMipsPtr);
                Binding["stream_descriptor_pointer"] = Strings::Format("0x%llX", ImageInfo.UnknownPtr1);

                // Streamed images carry a unique runtime descriptor beside their mip
                // table. Capture a bounded block for VT/page-cache research; never follow
                // nested pointers here until their layout is independently validated.
                if (ImageInfo.UnknownPtr1 != 0)
                {
                    constexpr uint32_t StreamDescriptorBytes = 256;
                    uintptr_t DescriptorBytesRead = 0;
                    auto Descriptor = CoDAssets::GameInstance->Read(
                        static_cast<uintptr_t>(ImageInfo.UnknownPtr1),
                        static_cast<uintptr_t>(StreamDescriptorBytes), DescriptorBytesRead);
                    if (Descriptor != nullptr && DescriptorBytesRead == StreamDescriptorBytes)
                    {
                        const auto DescriptorFileName = ImageBaseName + ".stream_descriptor.bin";
                        auto DescriptorWriter = BinaryWriter();
                        if (DescriptorWriter.Create(FileSystems::CombinePath(
                            ImagesDirectory, DescriptorFileName)))
                        {
                            DescriptorWriter.Write(Descriptor, StreamDescriptorBytes);
                            DescriptorWriter.Close();
                            Binding["stream_descriptor_status"] = "captured";
                            Binding["stream_descriptor_file"] = FileSystems::CombinePath(
                                "terrain_images", DescriptorFileName);
                            Binding["stream_descriptor_bytes"] = StreamDescriptorBytes;
                        }
                    }
                    else
                    {
                        Binding["stream_descriptor_status"] = "read_failed";
                    }
                    delete[] Descriptor;
                }

                const bool HeightCandidate =
                    ImageInfo.ImageFormat == 41 || ImageInfo.ImageFormat == 42 || ImageInfo.ImageFormat == 43 ||
                    ImageInfo.ImageFormat == 54 || ImageInfo.ImageFormat == 56 || ImageInfo.ImageFormat == 57 ||
                    ImageInfo.ImageFormat == 58;
                Binding["height_candidate"] = HeightCandidate;
                Binding["height_candidate_basis"] = HeightCandidate
                    ? "single-channel 16/32-bit DXGI format; pixel semantics still unverified"
                    : "format is not a conservative single-channel 16/32-bit candidate";

                if (ImageInfo.GfxMipsPtr != 0 && ImageInfo.GfxMipMaps > 0 && ImageInfo.GfxMipMaps <= 32)
                {
                    const uint64_t MipBytes = static_cast<uint64_t>(ImageInfo.GfxMipMaps) * sizeof(BOCWGfxMip);
                    uintptr_t MipBytesRead = 0;
                    auto MipBuffer = CoDAssets::GameInstance->Read(
                        static_cast<uintptr_t>(ImageInfo.GfxMipsPtr), static_cast<uintptr_t>(MipBytes), MipBytesRead);
                    if (MipBuffer != nullptr && MipBytesRead == MipBytes)
                    {
                        auto MipWriter = BinaryWriter();
                        if (MipWriter.Create(FileSystems::CombinePath(ImagesDirectory, MipsFileName)))
                        {
                            MipWriter.Write(MipBuffer, static_cast<uint32_t>(MipBytes));
                            MipWriter.Close();
                            Binding["mip_table_status"] = "captured";
                            Binding["mip_table_file"] = FileSystems::CombinePath("terrain_images", MipsFileName);
                        }
                        else
                        {
                            Binding["mip_table_status"] = "write_failed";
                        }
                    }
                    else
                    {
                        Binding["mip_table_status"] = "read_failed";
                    }
                    delete[] MipBuffer;
                }
                else
                {
                    Binding["mip_table_status"] = "empty_or_rejected";
                }

                try
                {
                    const XImage_t ImageReference(
                        ImageUsageType::Unknown, 0, ImagePointer, ImageBaseName);
                    auto ImageData = GameBlackOpsCW::LoadXImage(ImageReference);
                    if (ImageData != nullptr && ImageData->DataBuffer != nullptr && ImageData->DataSize > 0)
                    {
                        auto DdsWriter = BinaryWriter();
                        if (DdsWriter.Create(FileSystems::CombinePath(ImagesDirectory, DdsFileName)))
                        {
                            DdsWriter.Write(ImageData->DataBuffer, ImageData->DataSize);
                            DdsWriter.Close();
                            Binding["dds_status"] = "captured";
                            Binding["dds_file"] = FileSystems::CombinePath("terrain_images", DdsFileName);
                            Binding["dds_size"] = ImageData->DataSize;
                            const auto DdsBytes = reinterpret_cast<const uint8_t*>(ImageData->DataBuffer);
                            const uint32_t DdsHeaderSize = ImageData->DataSize >= 148 &&
                                std::memcmp(DdsBytes + 84, "DX10", 4) == 0 ? 148 : 128;

                            if ((RoleCombined0 || (BindingUnnamed && BindingId == 7)) &&
                                ImageInfo.ImageFormat == 78)
                            {
                                const auto BaseColorFileName = std::string("terrain_basecolor.png");
                                const auto BaseColorPath = FileSystems::CombinePath(ImagesDirectory, BaseColorFileName);
                                const bool Converted = Image::ConvertImageMemory(
                                    ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader,
                                    BaseColorPath, ImageFormat::Standard_PNG, ImagePatch::Color_StripAlpha);
                                Binding["material_role"] = "bocw_virtual_texture_base_color";
                                Binding["png_status"] = Converted ? "converted" : "conversion_failed";
                                if (Converted)
                                {
                                    BaseColorTextureUri = "terrain_images/terrain_basecolor.png";
                                    BaseColorBindingId = BindingId;
                                    BaseColorNameHash = ImageNameHash;
                                    Binding["png_file"] = BaseColorTextureUri;
                                }
                            }
                            else if (RoleCombined1 || (BindingUnnamed && BindingId == 8))
                            {
                                Binding["material_role"] = "map_wide_xy_normal";
                                Binding["role_validation"] = "BC5 R/G correlate 0.923/0.913 with X/Y normals derived independently from binding 9; cross-axis correlations are near zero";
                                const auto NormalPath = FileSystems::CombinePath(ImagesDirectory, "terrain_normal_source.png");
                                const bool NormalConverted = Image::ConvertImageMemory(
                                    ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader,
                                    NormalPath, ImageFormat::Standard_PNG, ImagePatch::Normal_Expand);
                                Binding["normal_png_status"] = NormalConverted ? "converted" : "conversion_failed";
                                if (NormalConverted)
                                {
                                    TerrainNormalTextureUri = "terrain_images/terrain_normal_source.png";
                                    Binding["normal_png_file"] = TerrainNormalTextureUri;
                                }

                                DirectX::ScratchImage SourceNormalImage;
                                DirectX::ScratchImage ExpandedNormalImage;
                                DirectX::TexMetadata SourceNormalMetadata{};
                                const auto LoadResult = DirectX::LoadFromDDSMemory(
                                    reinterpret_cast<const uint8_t*>(ImageData->DataBuffer),
                                    static_cast<size_t>(ImageData->DataSize), DirectX::DDS_FLAGS::DDS_FLAGS_NONE,
                                    &SourceNormalMetadata, SourceNormalImage);
                                const auto SourcePixels = SUCCEEDED(LoadResult)
                                    ? SourceNormalImage.GetImage(0, 0, 0) : nullptr;
                                const auto ExpandResult = SourcePixels != nullptr
                                    ? DirectX::Decompress(*SourcePixels, DXGI_FORMAT_R8G8B8A8_UNORM,
                                        ExpandedNormalImage)
                                    : E_FAIL;
                                const auto ExpandedPixels = SUCCEEDED(ExpandResult)
                                    ? ExpandedNormalImage.GetImage(0, 0, 0) : nullptr;
                                if (ExpandedPixels != nullptr && ExpandedPixels->width == ImageInfo.LoadedMipWidth &&
                                    ExpandedPixels->height == ImageInfo.LoadedMipHeight)
                                {
                                    TerrainNormalXYSamples.resize(static_cast<size_t>(ExpandedPixels->width) *
                                        ExpandedPixels->height * 2);
                                    for (size_t Row = 0; Row < ExpandedPixels->height; Row++)
                                    {
                                        const auto SourceRow = ExpandedPixels->pixels + Row * ExpandedPixels->rowPitch;
                                        for (size_t Column = 0; Column < ExpandedPixels->width; Column++)
                                        {
                                            const size_t TargetIndex = (Row * ExpandedPixels->width + Column) * 2;
                                            TerrainNormalXYSamples[TargetIndex + 0] = SourceRow[Column * 4 + 0];
                                            TerrainNormalXYSamples[TargetIndex + 1] = SourceRow[Column * 4 + 1];
                                        }
                                    }
                                    TerrainNormalWidth = static_cast<uint32_t>(ExpandedPixels->width);
                                    TerrainNormalHeight = static_cast<uint32_t>(ExpandedPixels->height);
                                    TerrainNormalBindingId = BindingId;
                                    TerrainNormalNameHash = ImageNameHash;
                                    Binding["selected_vertex_normal_source"] = true;
                                }
                                else
                                {
                                    Binding["normal_decode_status"] = "directxtex_decode_failed";
                                    Binding["normal_load_hresult"] = Strings::Format("0x%08X",
                                        static_cast<uint32_t>(LoadResult));
                                    Binding["normal_decompress_hresult"] = Strings::Format("0x%08X",
                                        static_cast<uint32_t>(ExpandResult));
                                }
                            }
                            else if (RoleColorMap || (BindingUnnamed && BindingId == 12))
                            {
                                Binding["material_role"] = "map_wide_surface_parameter_composite";
                                Binding["assignment"] = "exported for channel research; not assigned to PBR slots until channel semantics are verified";
                                const auto SurfacePath = FileSystems::CombinePath(ImagesDirectory,
                                    "terrain_surface_parameters.png");
                                const bool SurfaceConverted = Image::ConvertImageMemory(
                                    ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader,
                                    SurfacePath, ImageFormat::Standard_PNG, ImagePatch::NoPatch);
                                Binding["surface_png_status"] = SurfaceConverted ? "converted" : "conversion_failed";
                                if (SurfaceConverted)
                                {
                                    SurfaceParametersTextureUri = "terrain_images/terrain_surface_parameters.png";
                                    Binding["surface_png_file"] = SurfaceParametersTextureUri;
                                }
                            }

                            if (ImageInfo.ImageFormat == 42 && ImageInfo.LoadedMipWidth != ImageInfo.LoadedMipHeight)
                            {
                                // Binding 10 holds exactly one bit per unified-height texel.
                                // Each R32_UINT texel packs an 8 x 4 block of height texels:
                                // bit n addresses sub-y n >> 3 and sub-x n & 7, LSB first.
                                // A set bit means terrain is present, a cleared bit is a hole.
                                Binding["decoded_role"] = "terrain_hole_bitmask";
                                Binding["decoded_role_basis"] = "131072 packed u32 equals 4194304 bits, exactly one per unified-height texel; cleared bits form axis-aligned building footprints";
                                const uint64_t PackedCount = static_cast<uint64_t>(ImageInfo.LoadedMipWidth) *
                                    ImageInfo.LoadedMipHeight;
                                const uint64_t RequiredBytes = PackedCount * sizeof(uint32_t);
                                if (TerrainSolidMask.empty() && PackedCount != 0 &&
                                    ImageData->DataSize >= DdsHeaderSize &&
                                    RequiredBytes <= ImageData->DataSize - DdsHeaderSize)
                                {
                                    const uint32_t ExpandedWidth = ImageInfo.LoadedMipWidth * 8;
                                    const uint32_t ExpandedHeight = ImageInfo.LoadedMipHeight * 4;
                                    TerrainSolidMask.assign(
                                        static_cast<size_t>(ExpandedWidth) * ExpandedHeight, 1);
                                    TerrainSolidWidth = ExpandedWidth;
                                    TerrainSolidHeight = ExpandedHeight;
                                    TerrainHoleMinimumX = ExpandedWidth;
                                    TerrainHoleMinimumY = ExpandedHeight;

                                    for (uint32_t PackedY = 0; PackedY < ImageInfo.LoadedMipHeight; PackedY++)
                                    {
                                        for (uint32_t PackedX = 0; PackedX < ImageInfo.LoadedMipWidth; PackedX++)
                                        {
                                            uint32_t Packed = 0;
                                            std::memcpy(&Packed, DdsBytes + DdsHeaderSize +
                                                (static_cast<size_t>(PackedY) * ImageInfo.LoadedMipWidth + PackedX) *
                                                sizeof(uint32_t), sizeof(Packed));
                                            if (Packed == 0xFFFFFFFFu)
                                                continue;

                                            for (uint32_t Bit = 0; Bit < 32; Bit++)
                                            {
                                                if ((Packed >> Bit) & 1u)
                                                    continue;
                                                const uint32_t TexelX = PackedX * 8 + (Bit & 7u);
                                                const uint32_t TexelY = PackedY * 4 + (Bit >> 3);
                                                TerrainSolidMask[static_cast<size_t>(TexelY) * ExpandedWidth + TexelX] = 0;
                                                TerrainHoleTexels++;
                                                TerrainHoleMinimumX = std::min(TerrainHoleMinimumX, TexelX);
                                                TerrainHoleMinimumY = std::min(TerrainHoleMinimumY, TexelY);
                                                TerrainHoleMaximumX = std::max(TerrainHoleMaximumX, TexelX);
                                                TerrainHoleMaximumY = std::max(TerrainHoleMaximumY, TexelY);
                                            }
                                        }
                                    }

                                    Binding["selected_terrain_hole_source"] = true;
                                    Binding["hole_texels"] = TerrainHoleTexels;
                                    if (TerrainHoleTexels == 0)
                                    {
                                        TerrainHoleMinimumX = 0;
                                        TerrainHoleMinimumY = 0;
                                    }
                                }
                            }
                            else if ((RoleIndexMap || (BindingUnnamed && BindingId == 11)) &&
                                ImageInfo.ImageFormat == 62)
                            {
                                Binding["decoded_role"] = "material_index_map";
                                Binding["decoded_role_basis"] = "R8_UINT values form coherent terrain regions and correlate with the GDC OMPV/index-map design";
                                const uint64_t RequiredBytes = static_cast<uint64_t>(ImageInfo.LoadedMipWidth) * ImageInfo.LoadedMipHeight;
                                if (MaterialIndexSamples.empty() && ImageData->DataSize >= DdsHeaderSize &&
                                    RequiredBytes <= ImageData->DataSize - DdsHeaderSize)
                                {
                                    MaterialIndexSamples.resize(static_cast<size_t>(RequiredBytes));
                                    std::memcpy(MaterialIndexSamples.data(), DdsBytes + DdsHeaderSize,
                                        static_cast<size_t>(RequiredBytes));
                                    MaterialIndexWidth = ImageInfo.LoadedMipWidth;
                                    MaterialIndexHeight = ImageInfo.LoadedMipHeight;
                                    MaterialIndexBindingId = BindingId;
                                    Binding["selected_material_index_source"] = true;

                                    const auto IndexPreviewPath = FileSystems::CombinePath(ImagesDirectory,
                                        "terrain_material_index.png");
                                    const bool Converted = Image::ConvertImageMemory(
                                        ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader,
                                        IndexPreviewPath, ImageFormat::Standard_PNG, ImagePatch::NoPatch);
                                    Binding["index_preview_status"] = Converted ? "converted" : "conversion_failed";
                                    if (Converted)
                                        Binding["index_preview_file"] = "terrain_images/terrain_material_index.png";
                                }
                            }
                            else if ((RoleMaskMap || (BindingUnnamed && BindingId == 13)) &&
                                ImageInfo.ImageFormat == 42 && ImageInfo.LoadedMipWidth == ImageInfo.LoadedMipHeight)
                            {
                                Binding["decoded_role"] = "packed_257_control_grid";
                                Binding["decoded_role_basis"] = "all R32_UINT cells are populated and packed byte planes contain coherent, distinct terrain features; exact channel semantics remain unresolved";
                                const uint64_t RequiredBytes = static_cast<uint64_t>(ImageInfo.LoadedMipWidth) *
                                    ImageInfo.LoadedMipHeight * sizeof(uint32_t);
                                if (TerrainControlSamples.empty() && ImageData->DataSize >= DdsHeaderSize &&
                                    RequiredBytes <= ImageData->DataSize - DdsHeaderSize)
                                {
                                    TerrainControlSamples.resize(static_cast<size_t>(ImageInfo.LoadedMipWidth) * ImageInfo.LoadedMipHeight);
                                    std::memcpy(TerrainControlSamples.data(), DdsBytes + DdsHeaderSize,
                                        static_cast<size_t>(RequiredBytes));
                                    TerrainControlWidth = ImageInfo.LoadedMipWidth;
                                    TerrainControlHeight = ImageInfo.LoadedMipHeight;
                                    TerrainControlBindingId = BindingId;
                                    Binding["selected_packed_control_source"] = true;
                                }
                            }

                            const bool SourceAlbedoCandidate = SourceLayerBinding &&
                                (ImageInfo.ImageFormat == 72 || ImageInfo.ImageFormat == 99);
                            const bool PreviousAlbedoCandidate = !ImageBindings.empty() &&
                                (ImageBindings.back().value("image_format", 0u) == 72 ||
                                 ImageBindings.back().value("image_format", 0u) == 99);
                            if (SourceAlbedoCandidate && !PreviousAlbedoCandidate)
                            {
                                const auto LayerAlbedoFileName = Strings::Format("albedo_binding_%03u.png", BindingId);
                                const auto LayerAlbedoPath = FileSystems::CombinePath(LayersDirectory, LayerAlbedoFileName);
                                const bool Converted = Image::ConvertImageMemory(
                                    ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader,
                                    LayerAlbedoPath, ImageFormat::Standard_PNG, ImagePatch::Color_StripAlpha);
                                Binding["source_layer_role"] = "albedo_marker";
                                Binding["source_layer_basis"] = "BC1/BC7 color image in repeating layer sequence; correlated with GDC material layers";
                                Binding["layer_png_status"] = Converted ? "converted" : "conversion_failed";
                                if (Converted)
                                    Binding["layer_png_file"] = Strings::Format("terrain_layers/albedo_binding_%03u.png", BindingId);
                            }
                            else if (SourceAlbedoCandidate)
                            {
                                Binding["source_layer_role"] = "adjacent_color_auxiliary";
                                Binding["source_layer_basis"] = "adjacent BC1/BC7 candidate does not begin a new repeating material-layer sequence";
                            }

                            if (SourceLayerBinding && (ImageInfo.ImageFormat == 80 || ImageInfo.ImageFormat == 98))
                            {
                                const bool ScalarResource = ImageInfo.ImageFormat == 80;
                                const auto ResourceFileName = Strings::Format(ScalarResource
                                    ? "scalar_binding_%03u.png" : "surface_binding_%03u.png", BindingId);
                                const auto ResourcePath = FileSystems::CombinePath(LayersDirectory, ResourceFileName);
                                const bool Converted = Image::ConvertImageMemory(
                                    ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader,
                                    ResourcePath, ImageFormat::Standard_PNG, ImagePatch::NoPatch);
                                Binding["layer_resource_role"] = ScalarResource
                                    ? "scalar_material_resource" : "linear_surface_or_normal_resource";
                                Binding["layer_resource_basis"] = "resource in repeating source-material sequence; exact semantic requires hash/name or shader correlation";
                                Binding["layer_resource_png_status"] = Converted ? "converted" : "conversion_failed";
                                if (Converted)
                                    Binding["layer_resource_png_file"] = FileSystems::CombinePath("terrain_layers", ResourceFileName);

                                // Treyarch's named _n resources store tangent-space X/Y
                                // in R/G while B carries unrelated packed data. Build a
                                // standards-compliant RGB normal image by reconstructing
                                // positive Z; the original packed PNG remains untouched.
                                if (!ScalarResource && BindingNameEndsWith("_n"))
                                {
                                    DirectX::TexMetadata NormalMetadata{};
                                    DirectX::ScratchImage PackedNormal;
                                    DirectX::ScratchImage ExpandedNormal;
                                    DirectX::ScratchImage StandardNormal;
                                    const auto LoadNormalResult = DirectX::LoadFromDDSMemory(
                                        ImageData->DataBuffer, static_cast<size_t>(ImageData->DataSize),
                                        DirectX::DDS_FLAGS::DDS_FLAGS_NONE, &NormalMetadata, PackedNormal);
                                    const auto PackedPixels = SUCCEEDED(LoadNormalResult)
                                        ? PackedNormal.GetImage(0, 0, 0) : nullptr;
                                    const auto ExpandNormalResult = PackedPixels != nullptr
                                        ? DirectX::Decompress(*PackedPixels, DXGI_FORMAT_R8G8B8A8_UNORM,
                                            ExpandedNormal) : E_FAIL;
                                    const auto ExpandedPixels = SUCCEEDED(ExpandNormalResult)
                                        ? ExpandedNormal.GetImage(0, 0, 0) : nullptr;
                                    const auto InitializeNormalResult = ExpandedPixels != nullptr
                                        ? StandardNormal.Initialize2D(DXGI_FORMAT_R8G8B8A8_UNORM,
                                            ExpandedPixels->width, ExpandedPixels->height, 1, 1) : E_FAIL;
                                    const auto StandardPixels = SUCCEEDED(InitializeNormalResult)
                                        ? StandardNormal.GetImage(0, 0, 0) : nullptr;
                                    if (ExpandedPixels != nullptr && StandardPixels != nullptr)
                                    {
                                        for (size_t Row = 0; Row < ExpandedPixels->height; Row++)
                                        {
                                            const auto SourceRow = ExpandedPixels->pixels +
                                                Row * ExpandedPixels->rowPitch;
                                            auto TargetRow = StandardPixels->pixels + Row * StandardPixels->rowPitch;
                                            for (size_t Column = 0; Column < ExpandedPixels->width; Column++)
                                            {
                                                const uint8_t R = SourceRow[Column * 4];
                                                const uint8_t G = SourceRow[Column * 4 + 1];
                                                const float NX = static_cast<float>(R) / 127.5f - 1.0f;
                                                const float NY = static_cast<float>(G) / 127.5f - 1.0f;
                                                const float NZ = std::sqrt(std::max(0.0f,
                                                    1.0f - NX * NX - NY * NY));
                                                TargetRow[Column * 4] = R;
                                                TargetRow[Column * 4 + 1] = G;
                                                TargetRow[Column * 4 + 2] = static_cast<uint8_t>(
                                                    std::max(0.0f, std::min(255.0f,
                                                        (NZ * 0.5f + 0.5f) * 255.0f + 0.5f)));
                                                TargetRow[Column * 4 + 3] = 255;
                                            }
                                        }
                                        const auto StandardNormalFile = Strings::Format(
                                            "normal_binding_%03u.png", BindingId);
                                        const auto StandardNormalPath = FileSystems::CombinePath(
                                            LayersDirectory, StandardNormalFile);
                                        const auto SaveNormalResult = DirectX::SaveToWICFile(*StandardPixels,
                                            DirectX::WIC_FLAGS::WIC_FLAGS_NONE,
                                            DirectX::GetWICCodec(DirectX::WICCodecs::WIC_CODEC_PNG),
                                            Strings::ToUnicodeString(StandardNormalPath).c_str());
                                        if (SUCCEEDED(SaveNormalResult))
                                        {
                                            Binding["standard_normal_png_file"] =
                                                FileSystems::CombinePath("terrain_layers", StandardNormalFile);
                                            Binding["standard_normal_decode"] =
                                                "R/G signed tangent XY preserved; positive Z reconstructed; packed B discarded";
                                        }
                                    }
                                }
                            }

                            if (HeightSamples.empty() && ImageInfo.ImageFormat == 56 &&
                                ImageInfo.LoadedMipWidth >= 2 && ImageInfo.LoadedMipHeight >= 2)
                            {
                                const uint64_t RequiredHeightBytes = static_cast<uint64_t>(ImageInfo.LoadedMipWidth) *
                                    ImageInfo.LoadedMipHeight * sizeof(uint16_t);
                                if (ImageData->DataSize >= DdsHeaderSize &&
                                    RequiredHeightBytes <= ImageData->DataSize - DdsHeaderSize)
                                {
                                    HeightSamples.resize(static_cast<size_t>(ImageInfo.LoadedMipWidth) * ImageInfo.LoadedMipHeight);
                                    std::memcpy(HeightSamples.data(), DdsBytes + DdsHeaderSize,
                                        static_cast<size_t>(RequiredHeightBytes));
                                    HeightWidth = ImageInfo.LoadedMipWidth;
                                    HeightHeight = ImageInfo.LoadedMipHeight;
                                    HeightBindingId = BindingId;
                                    HeightNameHash = ImageNameHash;
                                    Binding["selected_height_source"] = true;
                                }
                            }
                        }
                        else
                        {
                            Binding["dds_status"] = "write_failed";
                        }
                    }
                    else
                    {
                        Binding["dds_status"] = "unavailable";
                    }
                }
                catch (...)
                {
                    Binding["dds_status"] = "load_exception";
                }

                ImageBindings.push_back(Binding);
            }
        }
        else
        {
            ImageBindingsStatus = "table_read_failed";
        }

        delete[] ImagePointerBuffer;
        delete[] BindingIdBuffer;
    }
    else if (CaptureResearch)
    {
        ImageBindingsStatus = "rejected_count_mismatch_or_limit";
    }

    nlohmann::json MaterialMappingProbe = {
        {"status", CaptureResearch ? "not_attempted" : "disabled"},
        {"root_pointer_0010", Strings::Format("0x%llX", Pointer0010)},
        {"purpose", "locate records that connect OMPV index values 0-30 to BOCW material definitions and captured terrain images"},
        {"known_image_references", nlohmann::json::array()},
        {"compact_index_runs", nlohmann::json::array()},
        {"material_candidates", nlohmann::json::array()}
    };
    if (CaptureResearch && Pointer0010 != 0)
    {
        constexpr uintptr_t PreferredMappingProbeSize = 0x1000;
        constexpr uintptr_t FallbackMappingProbeSize = 0x400;
        uintptr_t MappingBytesRead = 0;
        uintptr_t MappingProbeSize = PreferredMappingProbeSize;
        auto MappingBuffer = CoDAssets::GameInstance->Read(static_cast<uintptr_t>(Pointer0010),
            MappingProbeSize, MappingBytesRead);
        if (MappingBuffer == nullptr || MappingBytesRead != MappingProbeSize)
        {
            delete[] MappingBuffer;
            MappingProbeSize = FallbackMappingProbeSize;
            MappingBytesRead = 0;
            MappingBuffer = CoDAssets::GameInstance->Read(static_cast<uintptr_t>(Pointer0010),
                MappingProbeSize, MappingBytesRead);
        }

        if (MappingBuffer != nullptr && MappingBytesRead == MappingProbeSize)
        {
            const auto MappingBytes = reinterpret_cast<const uint8_t*>(MappingBuffer);
            auto ProbeWriter = BinaryWriter();
            const auto ProbeFileName = std::string("mapping_root_0010.bin");
            if (ProbeWriter.Create(FileSystems::CombinePath(ExportPath, ProbeFileName)))
            {
                ProbeWriter.Write(MappingBuffer, static_cast<uint32_t>(MappingBytesRead));
                ProbeWriter.Close();
                MaterialMappingProbe["status"] = "root_captured_and_scanned";
                MaterialMappingProbe["root_file"] = ProbeFileName;
                MaterialMappingProbe["root_bytes"] = MappingBytesRead;
            }
            else
            {
                MaterialMappingProbe["status"] = "root_write_failed_but_scanned";
            }

            auto ReadRootUInt64 = [MappingBuffer, MappingBytesRead](size_t Offset) -> uint64_t
            {
                uint64_t Value = 0;
                if (Offset <= MappingBytesRead && sizeof(Value) <= MappingBytesRead - Offset)
                    std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                return Value;
            };
            auto ReadRootFloat = [MappingBuffer, MappingBytesRead](size_t Offset) -> float
            {
                float Value = 0.0f;
                if (Offset <= MappingBytesRead && sizeof(Value) <= MappingBytesRead - Offset)
                    std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                return Value;
            };
            auto ReadRootUInt16 = [MappingBuffer, MappingBytesRead](size_t Offset) -> uint16_t
            {
                uint16_t Value = 0;
                if (Offset <= MappingBytesRead && sizeof(Value) <= MappingBytesRead - Offset)
                    std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                return Value;
            };

            RuntimeTerrainOriginX = ReadRootFloat(0xE8);
            RuntimeTerrainOriginY = ReadRootFloat(0xEC);
            RuntimeTerrainCellSize = ReadRootFloat(0xF0);
            RuntimeHeightBias = ReadRootFloat(0xF4);
            RuntimeHeightRange = ReadRootFloat(0xF8);
            RuntimeMaximumTextureCoordinate = ReadRootFloat(0xFC);
            RuntimeHeightWidth = ReadRootUInt16(0x100);
            RuntimeHeightHeight = ReadRootUInt16(0x102);
            // Header bounds agree with the runtime origin on one captured map and not on
            // another, so they cannot decide validity. Require the runtime block to be
            // internally consistent here; the quadtree root tile confirms the origin below.
            const bool HeaderBoundsAgree =
                RuntimeTerrainOriginX == ReadHeaderFloat(0x18) &&
                RuntimeTerrainOriginY == ReadHeaderFloat(0x1C) &&
                RuntimeTerrainCellSize == ReadHeaderFloat(0x54) &&
                RuntimeTerrainCellSize == ReadHeaderFloat(0x58);
            RuntimeHeightDecodeValidated =
                RuntimeHeightWidth == HeightWidth && RuntimeHeightHeight == HeightHeight &&
                RuntimeTerrainCellSize > 0.0f && RuntimeHeightRange > 0.0f;
            MaterialMappingProbe["runtime_height_decode"] = {
                {"status", RuntimeHeightDecodeValidated ? "validated" : "candidate_mismatch"},
                {"header_bounds_agree", HeaderBoundsAgree},
                {"formula", "world_z = height_unorm * height_range + height_bias"},
                {"terrain_origin_xy", {RuntimeTerrainOriginX, RuntimeTerrainOriginY}},
                {"cell_size", RuntimeTerrainCellSize},
                {"height_bias", RuntimeHeightBias},
                {"height_range", RuntimeHeightRange},
                {"maximum_texture_coordinate", RuntimeMaximumTextureCoordinate},
                {"height_dimensions", {RuntimeHeightWidth, RuntimeHeightHeight}},
                {"evidence", "contiguous runtime shader constants agree with TerrainGfx origin, spacing, and selected height texture dimensions"}
            };

            const uint64_t GenericIndexCount = ReadRootUInt64(0x18);
            const uint64_t GenericIndexPointer = ReadRootUInt64(0x20);
            const uint64_t GenericIndexBytes = ReadRootUInt64(0x30);
            const uint64_t FollowingPointer = ReadRootUInt64(0x48);
            bool GenericGridValidated = false;
            uint16_t GenericGridMaximumIndex = 0;
            if (GenericIndexCount == 32ull * 32ull * 6ull &&
                GenericIndexBytes == GenericIndexCount * sizeof(uint16_t) &&
                GenericIndexPointer + GenericIndexBytes == FollowingPointer)
            {
                uintptr_t GenericBytesRead = 0;
                auto GenericBytes = CoDAssets::GameInstance->Read(
                    static_cast<uintptr_t>(GenericIndexPointer),
                    static_cast<uintptr_t>(GenericIndexBytes), GenericBytesRead);
                if (GenericBytes != nullptr && GenericBytesRead == GenericIndexBytes)
                {
                    GenericGridValidated = true;
                    for (uint32_t Y = 0; Y < 32 && GenericGridValidated; Y++)
                    {
                        for (uint32_t X = 0; X < 32 && GenericGridValidated; X++)
                        {
                            const uint16_t A = static_cast<uint16_t>(Y * 33 + X);
                            const uint16_t B = static_cast<uint16_t>(A + 1);
                            const uint16_t C = static_cast<uint16_t>(A + 33);
                            const uint16_t D = static_cast<uint16_t>(C + 1);
                            const uint16_t Expected[6] = { A, C, D, A, D, B };
                            const size_t Base = (static_cast<size_t>(Y) * 32 + X) * 6;
                            for (size_t Component = 0; Component < 6; Component++)
                            {
                                uint16_t Value = 0;
                                std::memcpy(&Value, GenericBytes +
                                    (Base + Component) * sizeof(Value), sizeof(Value));
                                GenericGridMaximumIndex = std::max(GenericGridMaximumIndex, Value);
                                GenericGridValidated = GenericGridValidated && Value == Expected[Component];
                            }
                        }
                    }
                }
                delete[] GenericBytes;
            }
            if (GenericGridValidated)
            {
                auto GenericGridCapture = CaptureBuffer(GenericIndexPointer, GenericIndexCount,
                    sizeof(uint16_t), "terrain_generic_grid_33x33_u16.bin",
                    "exact 33 x 33 regular-grid template: 32 x 32 cells, two triangles per cell");
                Captures.push_back(GenericGridCapture);
                MaterialMappingProbe["generic_highest_lod_grid"] = {
                    {"status", "validated"}, {"capture", GenericGridCapture},
                    {"vertex_dimensions", {33, 33}}, {"vertex_count", 1089},
                    {"cell_dimensions", {32, 32}}, {"triangle_count", 2048},
                    {"index_count", GenericIndexCount}, {"maximum_index", GenericGridMaximumIndex},
                    {"winding", "A,C,D / A,D,B"},
                    {"powerpoint_correlation", "slide 29: highest LOD is a regular grid using a generic mesh"}
                };
            }
            const uint64_t Count00C8 = ReadRootUInt64(0xC8);
            const uint64_t Pointer00D0 = ReadRootUInt64(0xD0);
            const uint64_t Count0108 = ReadRootUInt64(0x108);
            const uint64_t Pointer0110 = ReadRootUInt64(0x110);
            const uint64_t Count0158 = ReadRootUInt64(0x158);
            const uint64_t Pointer0160 = ReadRootUInt64(0x160);
            const uint64_t Count0180 = ReadRootUInt64(0x180);
            const uint64_t Pointer0188 = ReadRootUInt64(0x188);
            const uint64_t Count01B0 = ReadRootUInt64(0x1B0);
            const uint64_t Pointer01B8 = ReadRootUInt64(0x1B8);

            // The legal material-slot count is per map, not a constant: one captured map
            // declares 31 slots and another 39. All four per-slot arrays agree on it,
            // which is what makes it safe to size captures from.
            const uint64_t SlotCount = Count00C8;
            const bool SlotCountValid = SlotCount >= 1 && SlotCount <= 256 &&
                Count0108 == SlotCount && Count0180 == SlotCount && Count01B0 == SlotCount;
            MaterialMappingProbe["root_layout"] = {
                {"count_00c8", Count00C8}, {"pointer_00d0", Strings::Format("0x%llX", Pointer00D0)},
                {"count_0108", Count0108}, {"pointer_0110", Strings::Format("0x%llX", Pointer0110)},
                {"count_0158", Count0158}, {"pointer_0160", Strings::Format("0x%llX", Pointer0160)},
                {"count_0180", Count0180}, {"pointer_0188", Strings::Format("0x%llX", Pointer0188)},
                {"count_01b0", Count01B0}, {"pointer_01b8", Strings::Format("0x%llX", Pointer01B8)},
                {"slot_count", SlotCount},
                {"slot_count_agrees_across_arrays", SlotCountValid},
                {"index_range_correlation", "the per-slot arrays size the legal material-index range"},
                {"arrays", nlohmann::json::array()}
            };
            auto RecordRootArray = [&](uint64_t Pointer, uint64_t Count, uint64_t ElementSize,
                const std::string& FileName, const std::string& Evidence)
            {
                auto Capture = CaptureBuffer(Pointer, Count, ElementSize, FileName, Evidence);
                Captures.push_back(Capture);
                MaterialMappingProbe["root_layout"]["arrays"].push_back(Capture);
            };

            if (SlotCountValid && (SourceOnly || (Pointer0160 > Pointer00D0 &&
                Pointer0160 - Pointer00D0 == Count00C8 * sizeof(uint32_t))))
            {
                RecordRootArray(Pointer00D0, Count00C8, sizeof(uint32_t),
                    Strings::Format("mapping_indices_%llu_u32.bin", SlotCount),
                    SourceOnly ? "counted u32 legal-index/remap candidate; allocation adjacency not required"
                        : "adjacent span: counted u32 legal-index identity list/remap");
            }
            if (Count0158 == 256 && (SourceOnly || (Pointer0110 > Pointer0160 &&
                Pointer0110 - Pointer0160 == Count0158 * sizeof(uint64_t))))
            {
                RecordRootArray(Pointer0160, Count0158, sizeof(uint64_t),
                    "mapping_lookup_256_u64.bin",
                    SourceOnly ? "counted 256-entry packed index/priority table; allocation adjacency not required"
                        : "exact adjacent span: 256 packed index/priority records; reveal-order lookup");
            }
            if (SlotCountValid && Pointer0110 != 0)
            {
                SlotMaterialTablePointer = Pointer0110;
                RecordRootArray(Pointer0110, Count0108, sizeof(uint64_t),
                    Strings::Format("mapping_indices_%llu_unknown_u64.bin", SlotCount),
                    "first 8 bytes of each 0x130 slot record; superseded by "
                    "slot_material_table.bin, kept so old captures still diff");
                // The real shape: SlotCount records of 0x130 bytes, each with an
                // XMaterial* at offset 0. Read as SlotCount x 8 this looked like
                // a mixed descriptor rather than an array, which is why the
                // slot-to-material assignment was inferred from colour and slope
                // for so long instead of just being read.
                RecordRootArray(Pointer0110, Count0108, SlotMaterialRecordStride,
                    "slot_material_table.bin",
                    "slot -> XMaterial*: SlotCount x 0x130 records, material "
                    "pointer at offset 0");
            }
            if (SlotCountValid && Pointer01B8 > Pointer0188 &&
                Pointer01B8 - Pointer0188 == Count0180 * sizeof(uint64_t))
            {
                RecordRootArray(Pointer0188, Count0180, sizeof(uint64_t),
                    Strings::Format("mapping_indices_%llu_u64.bin", SlotCount),
                    "exact adjacent span: 31 x u64; decoded as all-null per-index state");
            }
            // The 0x1B8 array is 31 x u16. Research-v15 reread it as 31 x u64 and only
            // recovered the already-captured image pointer table, which begins 64 bytes in:
            //   0x188 -> 31 x u64 (null)
            //   0x1B8 -> 31 x u16 (0xFFFF), 62 bytes, then 2 bytes of alignment padding
            //   header 0x38 -> 126 x u64 image pointers
            const uint64_t ImagePointerGap = Pointer0038 > Pointer01B8 ? Pointer0038 - Pointer01B8 : 0;
            if (SlotCountValid && Pointer01B8 != 0)
            {
                auto SlotStateCapture = CaptureBuffer(Pointer01B8, Count01B0, sizeof(uint16_t),
                    Strings::Format("mapping_indices_%llu_u16.bin", SlotCount),
                    "31 x u16 per-slot state, all 0xFFFF; the image pointer table begins 2 bytes after it");
                SlotStateCapture["image_pointer_table_gap"] = ImagePointerGap;
                SlotStateCapture["adjacency_validated"] =
                    ImagePointerGap == Count01B0 * sizeof(uint16_t) + 2;
                Captures.push_back(SlotStateCapture);
                MaterialMappingProbe["root_layout"]["arrays"].push_back(SlotStateCapture);
            }
            LegalMaterialSlotCount = SlotCountValid ? SlotCount : 0;

            // The allocation after the generic index buffer is the quadtree LOD pyramid:
            // an array of { uint32 width; uint32 height; uint64 tiles; } records that halve
            // each level and end with a 0 x 0 terminator. Tile stride is derived from the
            // gap between consecutive levels rather than assumed.
            const uint64_t GenericGridEnd = GenericIndexPointer + GenericIndexCount * sizeof(uint16_t);
            if (FollowingPointer != 0)
            {
                constexpr size_t MaximumLodLevels = 16;
                constexpr size_t LodRecordSize = 16;
                TerrainQuadtree = {
                    {"pointer", Strings::Format("0x%llX", FollowingPointer)},
                    {"source", "TerrainGfx mapping root offset 0x48"},
                    {"record", "struct { uint32_t width; uint32_t height; uint64_t tiles; }"},
                    {"follows_generic_index_buffer", FollowingPointer == GenericGridEnd},
                    {"status", "read_failed"},
                    {"levels", nlohmann::json::array()},
                    {"stream_residency", nlohmann::json::array()}
                };

                uintptr_t LodBytesRead = 0;
                auto LodBuffer = CoDAssets::GameInstance->Read(
                    static_cast<uintptr_t>(FollowingPointer),
                    MaximumLodLevels * LodRecordSize, LodBytesRead);
                if (LodBuffer != nullptr && LodBytesRead == MaximumLodLevels * LodRecordSize)
                {
                    std::vector<uint32_t> LevelWidth;
                    std::vector<uint32_t> LevelHeight;
                    std::vector<uint64_t> LevelPointer;
                    for (size_t Level = 0; Level < MaximumLodLevels; Level++)
                    {
                        uint32_t Width = 0;
                        uint32_t Height = 0;
                        uint64_t Tiles = 0;
                        std::memcpy(&Width, LodBuffer + Level * LodRecordSize, sizeof(Width));
                        std::memcpy(&Height, LodBuffer + Level * LodRecordSize + 4, sizeof(Height));
                        std::memcpy(&Tiles, LodBuffer + Level * LodRecordSize + 8, sizeof(Tiles));
                        if (Width == 0 || Height == 0 || Tiles == 0 || Width > 8192 || Height > 8192)
                            break;
                        if (!LevelWidth.empty() &&
                            (Width > LevelWidth.back() || Height > LevelHeight.back()))
                            break;
                        LevelWidth.push_back(Width);
                        LevelHeight.push_back(Height);
                        LevelPointer.push_back(Tiles);
                    }

                    uint64_t TileStride = 0;
                    uint32_t StrideAgreements = 0;
                    for (size_t Level = 0; Level + 1 < LevelWidth.size(); Level++)
                    {
                        const uint64_t Tiles = static_cast<uint64_t>(LevelWidth[Level]) * LevelHeight[Level];
                        if (Tiles == 0 || LevelPointer[Level + 1] <= LevelPointer[Level])
                            continue;
                        const uint64_t Span = LevelPointer[Level + 1] - LevelPointer[Level];
                        if (Span % Tiles != 0)
                            continue;
                        const uint64_t Candidate = Span / Tiles;
                        if (Candidate < 16 || Candidate > 8192)
                            continue;
                        if (TileStride == 0)
                            TileStride = Candidate;
                        if (TileStride == Candidate)
                            StrideAgreements++;
                    }

                    uint64_t TotalTiles = 0;
                    for (size_t Level = 0; Level < LevelWidth.size(); Level++)
                        TotalTiles += static_cast<uint64_t>(LevelWidth[Level]) * LevelHeight[Level];

                    TerrainQuadtree["status"] = LevelWidth.empty() ? "no_levels" : "decoded";
                    TerrainQuadtree["level_count"] = LevelWidth.size();
                    TerrainQuadtree["total_tiles"] = TotalTiles;
                    TerrainQuadtree["tile_stride"] = TileStride;
                    TerrainQuadtree["tile_stride_agreements"] = StrideAgreements;
                    TerrainQuadtree["stream_record_layout"] = {
                        {"stride", 56},
                        {"fields", {
                            {{"offset", 0}, {"type", "byte[16]"}, {"meaning", "content hash; distinct for every tile"}},
                            {{"offset", 16}, {"type", "uint32"}, {"meaning", "unidentified"}},
                            {{"offset", 20}, {"type", "uint32"}, {"meaning", "constant 0x00030005"}},
                            {{"offset", 24}, {"type", "byte[8]"}, {"meaning", "unidentified"}},
                            {{"offset", 32}, {"type", "uint64"}, {"meaning", "streamed geometry blob pointer"}},
                            {{"offset", 40}, {"type", "uint64"}, {"meaning", "back-pointer to the owning tile record"}},
                            {{"offset", 48}, {"type", "uint32"}, {"meaning", "streamed blob size in bytes"}},
                            {{"offset", 52}, {"type", "uint32"}, {"meaning", "constant 0x00010004"}}
                        }}
                    };
                    if (!LevelWidth.empty())
                    {
                        // The finest level tiles the unified height map exactly when each tile
                        // carries the validated 33 x 33 generic grid.
                        const uint64_t FinestCells = static_cast<uint64_t>(LevelWidth[0]) * 32;
                        TerrainQuadtree["finest_tile_grid"] = {LevelWidth[0], LevelHeight[0]};
                        TerrainQuadtree["cells_per_tile"] = 32;
                        TerrainQuadtree["finest_cell_span"] = FinestCells;
                        TerrainQuadtree["matches_height_map"] = RuntimeHeightWidth != 0 &&
                            FinestCells == static_cast<uint64_t>(RuntimeHeightWidth);
                        if (RuntimeTerrainCellSize > 0.0f)
                            TerrainQuadtree["tile_world_size"] = RuntimeTerrainCellSize * 32.0f;
                    }

                    for (size_t Level = 0; Level < LevelWidth.size(); Level++)
                    {
                        const uint64_t Tiles = static_cast<uint64_t>(LevelWidth[Level]) * LevelHeight[Level];
                        nlohmann::json LevelEntry = {
                            {"level", Level},
                            {"tile_grid", {LevelWidth[Level], LevelHeight[Level]}},
                            {"tiles", Tiles},
                            {"pointer", Strings::Format("0x%llX", LevelPointer[Level])}
                        };
                        if (Level + 1 < LevelWidth.size())
                        {
                            const bool Contiguous = TileStride != 0 &&
                                LevelPointer[Level] + Tiles * TileStride == LevelPointer[Level + 1];
                            LevelEntry["contiguous_with_next"] = Contiguous;
                        }
                        if (TileStride != 0)
                        {
                            auto TileCapture = CaptureBuffer(LevelPointer[Level], Tiles, TileStride,
                                Strings::Format("terrain_lod_tiles_level%u.bin", static_cast<uint32_t>(Level)),
                                "quadtree tile records at this LOD level");
                            Captures.push_back(TileCapture);
                            LevelEntry["capture"] = TileCapture;
                        }

                        // A level's allocation is two parallel per-tile arrays: a 352-byte tile
                        // record then a 144-byte culling record, which is why the gap between
                        // levels is tiles * 496. Tile record offset 160 addresses a third,
                        // 56-byte-stride array that only the streamed levels populate.
                        constexpr uint64_t TileRecordStride = 352;
                        constexpr uint64_t TileStreamStride = 56;
                        // The per-tile allocation is not an engine constant: one captured map
                        // uses 496 bytes per tile and another 487. Only require that it can hold
                        // the 352-byte record, then validate the record from its own fields.
                        if (TileStride >= TileRecordStride && Tiles > 0 &&
                            Tiles <= MaximumCaptureBytes / TileRecordStride)
                        {
                            uintptr_t TileBytesRead = 0;
                            auto TileBuffer = CoDAssets::GameInstance->Read(
                                static_cast<uintptr_t>(LevelPointer[Level]),
                                static_cast<uintptr_t>(Tiles * TileRecordStride), TileBytesRead);
                            if (TileBuffer != nullptr &&
                                TileBytesRead == static_cast<uintptr_t>(Tiles * TileRecordStride))
                            {
                                // The tile record is self-describing: offset 272 holds its LOD
                                // level and 264/268 its row-major tile X/Y. If those agree on every
                                // tile the layout is confirmed without assuming any stride.
                                bool RecordLayoutValid = LevelWidth[Level] != 0;
                                for (uint64_t Tile = 0; Tile < Tiles && RecordLayoutValid; Tile++)
                                {
                                    uint32_t RecordLevel = 0;
                                    uint32_t RecordX = 0;
                                    uint32_t RecordY = 0;
                                    std::memcpy(&RecordLevel,
                                        TileBuffer + Tile * TileRecordStride + 272, sizeof(RecordLevel));
                                    std::memcpy(&RecordX,
                                        TileBuffer + Tile * TileRecordStride + 264, sizeof(RecordX));
                                    std::memcpy(&RecordY,
                                        TileBuffer + Tile * TileRecordStride + 268, sizeof(RecordY));
                                    RecordLayoutValid =
                                        RecordLevel == static_cast<uint32_t>(Level) &&
                                        RecordX == static_cast<uint32_t>(Tile % LevelWidth[Level]) &&
                                        RecordY == static_cast<uint32_t>(Tile / LevelWidth[Level]);
                                }
                                LevelEntry["tile_record_layout_validated"] = RecordLayoutValid;
                                if (RecordLayoutValid && Tiles == 1)
                                {
                                    std::memcpy(&RootTileBoundsMinX, TileBuffer + 280, sizeof(float));
                                    std::memcpy(&RootTileBoundsMinY, TileBuffer + 284, sizeof(float));
                                    RootTileBoundsRead = true;
                                }

                                uint64_t StreamBase = 0;
                                bool StreamPresent = true;
                                bool StreamContiguous = true;
                                for (uint64_t Tile = 0; Tile < Tiles; Tile++)
                                {
                                    uint64_t StreamPointer = 0;
                                    std::memcpy(&StreamPointer,
                                        TileBuffer + Tile * TileRecordStride + 160, sizeof(StreamPointer));
                                    if (StreamPointer == 0)
                                    {
                                        StreamPresent = false;
                                        break;
                                    }
                                    if (Tile == 0)
                                        StreamBase = StreamPointer;
                                    else if (StreamPointer != StreamBase + Tile * TileStreamStride)
                                        StreamContiguous = false;
                                }

                                LevelEntry["tile_record_stride"] = TileRecordStride;
                                LevelEntry["cull_record_stride"] = TileStride - TileRecordStride;
                                LevelEntry["stream_array_present"] = StreamPresent;
                                LevelEntry["stream_array_contiguous"] = StreamPresent && StreamContiguous;

                                // Contiguity varies between sessions for the same map, so it is
                                // recorded above and never gates. Assemble the records in tile order
                                // ourselves; the output file is identical either way.
                                if (RecordLayoutValid && StreamPresent)
                                {
                                    const size_t StreamBytes =
                                        static_cast<size_t>(Tiles) * TileStreamStride;
                                    std::vector<uint8_t> StreamRecords(StreamBytes, 0);
                                    uint64_t StreamReadFailures = 0;
                                    for (uint64_t Tile = 0; Tile < Tiles; Tile++)
                                    {
                                        uint64_t StreamPointer = 0;
                                        std::memcpy(&StreamPointer,
                                            TileBuffer + Tile * TileRecordStride + 160,
                                            sizeof(StreamPointer));
                                        uintptr_t RecordBytesRead = 0;
                                        auto Record = CoDAssets::GameInstance->Read(
                                            static_cast<uintptr_t>(StreamPointer),
                                            static_cast<uintptr_t>(TileStreamStride), RecordBytesRead);
                                        if (Record != nullptr &&
                                            RecordBytesRead == static_cast<uintptr_t>(TileStreamStride))
                                        {
                                            std::memcpy(StreamRecords.data() + Tile * TileStreamStride,
                                                Record, static_cast<size_t>(TileStreamStride));
                                        }
                                        else
                                        {
                                            StreamReadFailures++;
                                        }
                                        delete[] Record;
                                    }

                                    nlohmann::json StreamCapture = {
                                        {"file", Strings::Format("terrain_tile_stream_level%u.bin",
                                            static_cast<uint32_t>(Level))},
                                        {"count", Tiles},
                                        {"element_size", TileStreamStride},
                                        {"bytes", StreamBytes},
                                        {"read_failures", StreamReadFailures},
                                        {"assembled_per_tile", true},
                                        {"interpretation", "56-byte per-tile record addressed by tile record offset 160"}
                                    };
                                    auto StreamWriter = BinaryWriter();
                                    if (StreamWriter.Create(FileSystems::CombinePath(ExportPath,
                                        StreamCapture["file"].get<std::string>())))
                                    {
                                        StreamWriter.Write(StreamRecords.data(),
                                            static_cast<uint32_t>(StreamBytes));
                                        StreamWriter.Close();
                                        StreamCapture["status"] = "captured";
                                    }
                                    else
                                    {
                                        StreamCapture["status"] = "write_failed";
                                    }
                                    Captures.push_back(StreamCapture);
                                    LevelEntry["stream_capture"] = StreamCapture;

                                    // Per-tile geometry is streamed, so most blobs are either
                                    // unmapped or zero-filled. Classify every tile first, then
                                    // capture only what is actually resident.
                                    // Classify from the records assembled per tile above, never
                                    // from a contiguous read at the first tile's pointer. When the
                                    // array is scattered - which it is on some sessions of the same
                                    // map - that read lands in unrelated memory and every pointer
                                    // and size below then belongs to the wrong tile.
                                    const uint8_t* StreamArray = StreamRecords.data();
                                    LevelEntry["stream_records_are_blob_source"] = true;
                                    if (StreamReadFailures < Tiles)
                                    {
                                        std::vector<uint64_t> BlobPointer(static_cast<size_t>(Tiles), 0);
                                        std::vector<uint32_t> BlobSize(static_cast<size_t>(Tiles), 0);
                                        if (Level == 0)
                                        {
                                            ShippedTileBoundsMinimum.assign(static_cast<size_t>(Tiles), { 0.0f, 0.0f });
                                            for (uint64_t Tile = 0; Tile < Tiles; Tile++)
                                            {
                                                std::memcpy(&ShippedTileBoundsMinimum[static_cast<size_t>(Tile)][0],
                                                    TileBuffer + Tile * TileRecordStride + 280, sizeof(float));
                                                std::memcpy(&ShippedTileBoundsMinimum[static_cast<size_t>(Tile)][1],
                                                    TileBuffer + Tile * TileRecordStride + 284, sizeof(float));
                                            }
                                        }
                                        std::vector<uint8_t> Resident(static_cast<size_t>(Tiles), 0);
                                        uint64_t Unreadable = 0;
                                        uint64_t ZeroFilled = 0;
                                        uint64_t ResidentCount = 0;
                                        uint32_t MinimumX = LevelWidth[Level];
                                        uint32_t MinimumY = LevelHeight[Level];
                                        uint32_t MaximumX = 0;
                                        uint32_t MaximumY = 0;
                                        uint64_t SumX = 0;
                                        uint64_t SumY = 0;

                                        for (uint64_t Tile = 0; Tile < Tiles; Tile++)
                                        {
                                            std::memcpy(&BlobPointer[static_cast<size_t>(Tile)],
                                                StreamArray + Tile * TileStreamStride + 32, sizeof(uint64_t));
                                            std::memcpy(&BlobSize[static_cast<size_t>(Tile)],
                                                StreamArray + Tile * TileStreamStride + 48, sizeof(uint32_t));

                                            const uint64_t Pointer = BlobPointer[static_cast<size_t>(Tile)];
                                            if (Pointer <= 0x10000000000ull || Pointer >= 0x8000000000000ull)
                                            {
                                                Unreadable++;
                                                continue;
                                            }
                                            uintptr_t WindowBytesRead = 0;
                                            auto Window = CoDAssets::GameInstance->Read(
                                                static_cast<uintptr_t>(Pointer), 64, WindowBytesRead);
                                            if (Window == nullptr || WindowBytesRead != 64)
                                            {
                                                delete[] Window;
                                                Unreadable++;
                                                continue;
                                            }
                                            bool AnyNonZero = false;
                                            for (uint32_t Byte = 0; Byte < 64 && !AnyNonZero; Byte++)
                                                AnyNonZero = Window[Byte] != 0;
                                            delete[] Window;

                                            if (!AnyNonZero)
                                            {
                                                ZeroFilled++;
                                                continue;
                                            }
                                            Resident[static_cast<size_t>(Tile)] = 1;
                                            ResidentCount++;
                                            const uint32_t TileX = static_cast<uint32_t>(Tile % LevelWidth[Level]);
                                            const uint32_t TileY = static_cast<uint32_t>(Tile / LevelWidth[Level]);
                                            MinimumX = std::min(MinimumX, TileX);
                                            MinimumY = std::min(MinimumY, TileY);
                                            MaximumX = std::max(MaximumX, TileX);
                                            MaximumY = std::max(MaximumY, TileY);
                                            SumX += TileX;
                                            SumY += TileY;
                                        }

                                        nlohmann::json Residency = {
                                            {"level", Level},
                                            {"tiles", Tiles},
                                            {"resident", ResidentCount},
                                            {"zero_filled", ZeroFilled},
                                            {"unreadable", Unreadable}
                                        };
                                        if (ResidentCount != 0)
                                        {
                                            Residency["tile_bounds"] = {
                                                {"minimum", {MinimumX, MinimumY}},
                                                {"maximum", {MaximumX, MaximumY}}
                                            };
                                            Residency["centroid"] = {
                                                SumX / ResidentCount, SumY / ResidentCount
                                            };
                                        }
                                        TerrainQuadtree["stream_residency"].push_back(Residency);

                                        // Capture a contiguous cluster rather than the first N resident
                                        // tiles, so captured neighbours share edges and cross-validate.
                                        if (ExportTerrainTiles && (SourceOnly || Level <= 2) && ResidentCount != 0)
                                        {
                                            auto NeighbourScore = [&](uint64_t Tile) -> uint32_t
                                            {
                                                const int64_t TileX = static_cast<int64_t>(Tile % LevelWidth[Level]);
                                                const int64_t TileY = static_cast<int64_t>(Tile / LevelWidth[Level]);
                                                uint32_t Score = 0;
                                                for (int64_t OffsetY = -1; OffsetY <= 1; OffsetY++)
                                                {
                                                    for (int64_t OffsetX = -1; OffsetX <= 1; OffsetX++)
                                                    {
                                                        const int64_t NeighbourX = TileX + OffsetX;
                                                        const int64_t NeighbourY = TileY + OffsetY;
                                                        if (NeighbourX < 0 || NeighbourY < 0 ||
                                                            NeighbourX >= LevelWidth[Level] ||
                                                            NeighbourY >= LevelHeight[Level])
                                                            continue;
                                                        if (Resident[static_cast<size_t>(
                                                            NeighbourY * LevelWidth[Level] + NeighbourX)])
                                                            Score++;
                                                    }
                                                }
                                                return Score;
                                            };

                                            uint64_t SeedTile = 0;
                                            uint32_t SeedScore = 0;
                                            for (uint64_t Tile = 0; Tile < Tiles; Tile++)
                                            {
                                                if (!Resident[static_cast<size_t>(Tile)])
                                                    continue;
                                                const uint32_t Score = NeighbourScore(Tile);
                                                if (Score > SeedScore)
                                                {
                                                    SeedScore = Score;
                                                    SeedTile = Tile;
                                                }
                                            }

                                            const uint64_t MaximumStreamCaptureBytes = (SourceOnly ? 512ull : 128ull) * 1024ull * 1024ull;
                                            uint64_t SkippedSize = 0, SkippedBudget = 0;
                                            const int64_t SeedX = static_cast<int64_t>(SeedTile % LevelWidth[Level]);
                                            const int64_t SeedY = static_cast<int64_t>(SeedTile / LevelWidth[Level]);
                                            uint64_t CapturedBytes = 0;
                                            nlohmann::json Geometry = nlohmann::json::array();

                                            for (int64_t Radius = 0;
                                                Radius < static_cast<int64_t>(std::max(LevelWidth[Level], LevelHeight[Level])) &&
                                                CapturedBytes < MaximumStreamCaptureBytes; Radius++)
                                            {
                                                for (int64_t OffsetY = -Radius;
                                                    OffsetY <= Radius && CapturedBytes < MaximumStreamCaptureBytes; OffsetY++)
                                                {
                                                    for (int64_t OffsetX = -Radius;
                                                        OffsetX <= Radius && CapturedBytes < MaximumStreamCaptureBytes; OffsetX++)
                                                    {
                                                        // Only the newly added ring each pass.
                                                        if (Radius != 0 &&
                                                            std::max(std::abs(OffsetX), std::abs(OffsetY)) != Radius)
                                                            continue;
                                                        const int64_t TileX = SeedX + OffsetX;
                                                        const int64_t TileY = SeedY + OffsetY;
                                                        if (TileX < 0 || TileY < 0 ||
                                                            TileX >= LevelWidth[Level] || TileY >= LevelHeight[Level])
                                                            continue;
                                                        const uint64_t Tile =
                                                            static_cast<uint64_t>(TileY) * LevelWidth[Level] + TileX;
                                                        if (!Resident[static_cast<size_t>(Tile)])
                                                            continue;
                                                        const uint32_t Size = BlobSize[static_cast<size_t>(Tile)];
                                                        if (Size == 0 || Size > (SourceOnly ? 16u : 1u) * 1024u * 1024u)
                                                        {
                                                            ++SkippedSize;
                                                            continue;
                                                        }
                                                        if (Size > MaximumStreamCaptureBytes - CapturedBytes)
                                                        {
                                                            ++SkippedBudget;
                                                            continue;
                                                        }

                                                        const auto GeometryFile = Level == 0
                                                            ? Strings::Format("terrain_tile_geometry_t%u.bin",
                                                                static_cast<uint32_t>(Tile))
                                                            : Strings::Format("terrain_tile_geometry_l%u_t%u.bin",
                                                                static_cast<uint32_t>(Level), static_cast<uint32_t>(Tile));
                                                        auto BlobCapture = CaptureBuffer(
                                                            BlobPointer[static_cast<size_t>(Tile)], Size, 1,
                                                            GeometryFile,
                                                            "streamed per-tile geometry blob addressed by stream record offset 32");
                                                        BlobCapture["level"] = Level;
                                                        BlobCapture["tile"] = Tile;
                                                        BlobCapture["tile_x"] = TileX;
                                                        BlobCapture["tile_y"] = TileY;
                                                        BlobCapture["blob_size"] = Size;
                                                        uint32_t TileVertexCount = 0;
                                                        uint32_t TileIndexCount = 0;
                                                        std::memcpy(&TileVertexCount,
                                                            TileBuffer + Tile * TileRecordStride + 112, sizeof(TileVertexCount));
                                                        std::memcpy(&TileIndexCount,
                                                            TileBuffer + Tile * TileRecordStride + 124, sizeof(TileIndexCount));
                                                        BlobCapture["vertex_count"] = TileVertexCount;
                                                        BlobCapture["index_count"] = TileIndexCount;
                                                        Captures.push_back(BlobCapture);
                                                        Geometry.push_back(BlobCapture);
                                                        if (BlobCapture.value("status", std::string()) == "captured")
                                                        {
                                                            CapturedBytes += Size;

                                                            // Retain the source vertex array. The blob is [128-byte
                                                            // header][1089 x 4-byte vertex][reserved index space], and
                                                            // the vertex is two uint16 XY with no Z.
                                                            constexpr uint32_t ShippedHeaderBytes = 128;
                                                            const uint32_t ShippedVertexBytes = TileVertexCount * 4;
                                                            if (Level == 0 && TileVertexCount == 1089 &&
                                                                Size >= ShippedHeaderBytes + ShippedVertexBytes)
                                                            {
                                                                uintptr_t VertexBytesRead = 0;
                                                                auto VertexBuffer = CoDAssets::GameInstance->Read(
                                                                    static_cast<uintptr_t>(BlobPointer[static_cast<size_t>(Tile)] +
                                                                        ShippedHeaderBytes),
                                                                    static_cast<uintptr_t>(ShippedVertexBytes), VertexBytesRead);
                                                                if (VertexBuffer != nullptr &&
                                                                    VertexBytesRead == static_cast<uintptr_t>(ShippedVertexBytes))
                                                                {
                                                                    ShippedTile Entry{};
                                                                    Entry.Tile = static_cast<uint32_t>(Tile);
                                                                    Entry.TileX = static_cast<uint32_t>(TileX);
                                                                    Entry.TileY = static_cast<uint32_t>(TileY);
                                                                    std::memcpy(&Entry.MinimumX,
                                                                        TileBuffer + Tile * TileRecordStride + 280, sizeof(float));
                                                                    std::memcpy(&Entry.MinimumY,
                                                                        TileBuffer + Tile * TileRecordStride + 284, sizeof(float));
                                                                    Entry.Packed.resize(TileVertexCount);
                                                                    std::memcpy(Entry.Packed.data(), VertexBuffer, ShippedVertexBytes);
                                                                    ShippedTiles.push_back(std::move(Entry));
                                                                }
                                                                delete[] VertexBuffer;
                                                            }
                                                            else if (Level > 0 && Level <= 2 &&
                                                                TileVertexCount != 0 && TileIndexCount != 0)
                                                            {
                                                                const uint64_t CoarseBytes =
                                                                    static_cast<uint64_t>(TileVertexCount) * 8 +
                                                                    static_cast<uint64_t>(TileIndexCount) * 2;
                                                                constexpr uint32_t ShippedHeaderBytes = 128;
                                                                if (Size >= ShippedHeaderBytes + CoarseBytes)
                                                                {
                                                                    uintptr_t CoarseBytesRead = 0;
                                                                    auto CoarseBuffer = CoDAssets::GameInstance->Read(
                                                                        static_cast<uintptr_t>(BlobPointer[static_cast<size_t>(Tile)] +
                                                                            ShippedHeaderBytes),
                                                                        static_cast<uintptr_t>(CoarseBytes), CoarseBytesRead);
                                                                    if (CoarseBuffer != nullptr &&
                                                                        CoarseBytesRead == static_cast<uintptr_t>(CoarseBytes))
                                                                    {
                                                                        ShippedCoarseTile Entry{};
                                                                        Entry.Level = static_cast<uint32_t>(Level);
                                                                        Entry.Tile = static_cast<uint32_t>(Tile);
                                                                        Entry.TileX = static_cast<uint32_t>(TileX);
                                                                        Entry.TileY = static_cast<uint32_t>(TileY);
                                                                        std::memcpy(&Entry.MinimumX,
                                                                            TileBuffer + Tile * TileRecordStride + 280, sizeof(float));
                                                                        std::memcpy(&Entry.MinimumY,
                                                                            TileBuffer + Tile * TileRecordStride + 284, sizeof(float));
                                                                        Entry.PackedXY.resize(TileVertexCount);
                                                                        Entry.Extra.resize(TileVertexCount);
                                                                        for (uint32_t Vertex = 0; Vertex < TileVertexCount; Vertex++)
                                                                        {
                                                                            std::memcpy(&Entry.PackedXY[Vertex],
                                                                                CoarseBuffer + Vertex * 8, sizeof(uint32_t));
                                                                            std::memcpy(&Entry.Extra[Vertex],
                                                                                CoarseBuffer + Vertex * 8 + 4, sizeof(uint32_t));
                                                                        }
                                                                        Entry.Indices.resize(TileIndexCount);
                                                                        std::memcpy(Entry.Indices.data(),
                                                                            CoarseBuffer + TileVertexCount * 8,
                                                                            static_cast<size_t>(TileIndexCount) * 2);
                                                                        bool IndicesValid = true;
                                                                        for (const auto Index : Entry.Indices)
                                                                            IndicesValid = IndicesValid && Index < TileVertexCount;
                                                                        if (IndicesValid)
                                                                            ShippedCoarseTiles.push_back(std::move(Entry));
                                                                    }
                                                                    delete[] CoarseBuffer;
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }

                                            if (!Geometry.empty() || SourceOnly)
                                            {
                                                nlohmann::json LevelGeometry = {
                                                    {"level", Level},
                                                    {"seed_tile", SeedTile},
                                                    {"seed_tile_xy", {SeedX, SeedY}},
                                                    {"seed_resident_neighbours", SeedScore},
                                                    {"captured_bytes", CapturedBytes},
                                                    {"budget_bytes", MaximumStreamCaptureBytes},
                                                    {"resident_candidates", ResidentCount},
                                                    {"attempted_blobs", Geometry.size()},
                                                    {"skipped_size", SkippedSize},
                                                    {"skipped_budget", SkippedBudget},
                                                    {"all_resident_blobs_attempted", Geometry.size() == ResidentCount},
                                                    {"blobs", Geometry}
                                                };
                                                TerrainQuadtree["stream_geometry_levels"].push_back(LevelGeometry);
                                                // Preserve the original level-0 key for existing offline tools.
                                                if (Level == 0)
                                                    TerrainQuadtree["stream_geometry"] = LevelGeometry;
                                            }
                                        }
                                    }
                                }
                            }
                            delete[] TileBuffer;
                        }
                        TerrainQuadtree["levels"].push_back(LevelEntry);
                    }
                }
                delete[] LodBuffer;
            }

            if (RootTileBoundsRead)
            {
                MaterialMappingProbe["runtime_height_decode"]["root_tile_bounds_agree"] =
                    RootTileBoundsMinX == RuntimeTerrainOriginX &&
                    RootTileBoundsMinY == RuntimeTerrainOriginY;
                MaterialMappingProbe["runtime_height_decode"]["root_tile_bounds_minimum"] =
                    { RootTileBoundsMinX, RootTileBoundsMinY };
            }

            std::unordered_map<uint64_t, uint32_t> KnownImages;
            for (size_t Index = 0; Index < TerrainImagePointers.size() &&
                Index < TerrainImageBindingIds.size(); Index++)
            {
                KnownImages[TerrainImagePointers[Index]] = TerrainImageBindingIds[Index];
            }

            nlohmann::json DecodedArrays = nlohmann::json::object();
            auto ReadExactArray = [](uint64_t Pointer, size_t Size, uintptr_t& BytesRead) -> int8_t*
            {
                BytesRead = 0;
                return CoDAssets::GameInstance->Read(static_cast<uintptr_t>(Pointer), Size, BytesRead);
            };

            if (SlotCountValid && Pointer00D0 != 0)
            {
                const size_t Size = static_cast<size_t>(Count00C8) * sizeof(uint32_t);
                uintptr_t BytesRead = 0;
                auto Bytes = ReadExactArray(Pointer00D0, Size, BytesRead);
                if (Bytes != nullptr && BytesRead == Size)
                {
                    bool Identity = true;
                    nlohmann::json Values = nlohmann::json::array();
                    for (uint32_t Index = 0; Index < Count00C8; Index++)
                    {
                        uint32_t Value = 0;
                        std::memcpy(&Value, Bytes + Index * sizeof(Value), sizeof(Value));
                        Values.push_back(Value);
                        Identity = Identity && Value == Index;
                    }
                    DecodedArrays["indices_slots_u32"] = {
                        {"values", Values}, {"identity", Identity},
                        {"classification", Identity ? "legal material-index slot list / identity remap" : "non-identity remap"},
                        {"source_layer_mapping", false}
                    };
                }
                delete[] Bytes;
            }

            if (SlotCountValid && Pointer01B8 != 0)
            {
                const size_t Size = static_cast<size_t>(Count01B0) * sizeof(uint16_t);
                uintptr_t BytesRead = 0;
                auto Bytes = ReadExactArray(Pointer01B8, Size, BytesRead);
                if (Bytes != nullptr && BytesRead == Size)
                {
                    bool AllSentinel = true;
                    nlohmann::json Values = nlohmann::json::array();
                    for (uint32_t Index = 0; Index < Count01B0; Index++)
                    {
                        uint16_t Value = 0;
                        std::memcpy(&Value, Bytes + Index * sizeof(Value), sizeof(Value));
                        Values.push_back(Value);
                        AllSentinel = AllSentinel && Value == 0xFFFFu;
                    }
                    DecodedArrays["indices_slots_u16"] = {
                        {"values", Values}, {"all_unassigned_sentinel", AllSentinel},
                        {"classification", "per-index optional/unassigned state"},
                        {"source_layer_mapping", false}
                    };
                }
                delete[] Bytes;
            }

            if (SlotCountValid && Pointer0188 != 0)
            {
                const size_t Size = static_cast<size_t>(Count0180) * sizeof(uint64_t);
                uintptr_t BytesRead = 0;
                auto Bytes = ReadExactArray(Pointer0188, Size, BytesRead);
                if (Bytes != nullptr && BytesRead == Size)
                {
                    bool AllNull = true;
                    size_t KnownImageMatches = 0;
                    nlohmann::json Values = nlohmann::json::array();
                    for (uint32_t Index = 0; Index < Count0180; Index++)
                    {
                        uint64_t Value = 0;
                        std::memcpy(&Value, Bytes + Index * sizeof(Value), sizeof(Value));
                        Values.push_back(Strings::Format("0x%llX", Value));
                        AllNull = AllNull && Value == 0;
                        KnownImageMatches += KnownImages.find(Value) != KnownImages.end() ? 1 : 0;
                    }
                    DecodedArrays["indices_slots_u64"] = {
                        {"values", Values}, {"all_null", AllNull},
                        {"known_image_pointer_matches", KnownImageMatches},
                        {"classification", "per-index optional/null pointer state"},
                        {"source_layer_mapping", false}
                    };
                }
                delete[] Bytes;
            }

            if (SlotCountValid && Pointer0110 != 0)
            {
                const size_t Size = static_cast<size_t>(Count0108) * sizeof(uint64_t);
                uintptr_t BytesRead = 0;
                auto Bytes = ReadExactArray(Pointer0110, Size, BytesRead);
                if (Bytes != nullptr && BytesRead == Size)
                {
                    size_t PointerLikeValues = 0;
                    size_t KnownImageMatches = 0;
                    nlohmann::json Values = nlohmann::json::array();
                    for (uint32_t Index = 0; Index < Count0108; Index++)
                    {
                        uint64_t Value = 0;
                        std::memcpy(&Value, Bytes + Index * sizeof(Value), sizeof(Value));
                        Values.push_back(Strings::Format("0x%016llX", Value));
                        PointerLikeValues += Value >= 0x100000000ull && Value < 0x800000000000ull ? 1 : 0;
                        KnownImageMatches += KnownImages.find(Value) != KnownImages.end() ? 1 : 0;
                    }
                    DecodedArrays["indices_slots_unknown_u64"] = {
                        {"values", Values}, {"pointer_like_values", PointerLikeValues},
                        {"known_image_pointer_matches", KnownImageMatches},
                        {"contains_grid_constants", true},
                        {"observed_float_constants", {0.0078125, 0.00006103515625, -0.0078125, 0.025, 0.5, 0.25}},
                        {"classification", "mixed runtime/mesh descriptor; count is not an element-count proof"},
                        {"source_layer_mapping", false}
                    };
                }
                delete[] Bytes;
            }

            if (Count0158 == 256 && Pointer0160 != 0)
            {
                struct IndexPriority
                {
                    uint32_t Index;
                    float Priority;
                };
                static_assert(sizeof(IndexPriority) == sizeof(uint64_t), "unexpected index-priority packing");
                const size_t Size = static_cast<size_t>(Count0158) * sizeof(IndexPriority);
                uintptr_t BytesRead = 0;
                auto Bytes = ReadExactArray(Pointer0160, Size, BytesRead);
                if (Bytes != nullptr && BytesRead == Size)
                {
                    std::array<bool, 32> Seen{};
                    std::array<float, 32> PriorityByIndex{};
                    bool First32Permutation = true;
                    bool DescendingPriority = true;
                    bool TailIdentityZero = true;
                    float PreviousPriority = 1000000.0f;
                    nlohmann::json RevealOrder = nlohmann::json::array();
                    for (uint32_t RecordIndex = 0; RecordIndex < Count0158; RecordIndex++)
                    {
                        IndexPriority Record{};
                        std::memcpy(&Record, Bytes + RecordIndex * sizeof(Record), sizeof(Record));
                        if (RecordIndex < 32)
                        {
                            First32Permutation = First32Permutation && Record.Index < 32;
                            if (Record.Index < 32)
                            {
                                First32Permutation = First32Permutation && !Seen[Record.Index];
                                Seen[Record.Index] = true;
                                PriorityByIndex[Record.Index] = Record.Priority;
                            }
                            DescendingPriority = DescendingPriority && Record.Priority <= PreviousPriority;
                            PreviousPriority = Record.Priority;
                            RevealOrder.push_back({
                                {"rank", RecordIndex}, {"index", Record.Index}, {"priority", Record.Priority}
                            });
                        }
                        else
                        {
                            TailIdentityZero = TailIdentityZero && Record.Index == RecordIndex && Record.Priority == 0.0f;
                        }
                    }
                    First32Permutation = First32Permutation &&
                        std::all_of(Seen.begin(), Seen.end(), [](bool Value) { return Value; });
                    nlohmann::json IndexToPriority = nlohmann::json::array();
                    for (uint32_t Index = 0; Index < PriorityByIndex.size(); Index++)
                        IndexToPriority.push_back({{"index", Index}, {"priority", PriorityByIndex[Index]}});
                    DecodedArrays["lookup_256_u64"] = {
                        {"record_layout", "{uint32 index, float priority}"},
                        {"first_32_complete_permutation", First32Permutation},
                        {"first_32_descending_priority", DescendingPriority},
                        {"entries_32_255_identity_zero", TailIdentityZero},
                        {"reveal_order", RevealOrder}, {"index_to_priority", IndexToPriority},
                        {"classification", "material reveal/blend ordering lookup"},
                        {"regular_grid_topology_match", false},
                        {"source_layer_mapping", "ordering only; does not identify any of the 22 source-layer sequences"}
                    };
                }
                delete[] Bytes;
            }
            MaterialMappingProbe["decoded_arrays"] = DecodedArrays;
            MaterialMappingProbe["array_classification"] = {
                {"material_mapping_table", "mapping_lookup_256_u64.bin stores index-to-reveal-priority ordering"},
                {"source_layer_assignment_table", "none of the five captured arrays"},
                {"mesh_or_lod_structure", Strings::Format(
                    "mapping_indices_%llu_unknown_u64.bin is a mixed descriptor, "
                    "not a %llu-entry array", LegalMaterialSlotCount, LegalMaterialSlotCount)},
                {"topology_evidence", "no captured table has the repeated adjacent-row six-index triangle motif of a regular grid"}
            };

            for (size_t Offset = 0; Offset + sizeof(uint64_t) <= MappingBytesRead; Offset += sizeof(uint64_t))
            {
                uint64_t Value = 0;
                std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                const auto KnownImage = KnownImages.find(Value);
                if (KnownImage != KnownImages.end())
                {
                    MaterialMappingProbe["known_image_references"].push_back({
                        {"offset", Offset},
                        {"pointer", Strings::Format("0x%llX", Value)},
                        {"binding_id", KnownImage->second}
                    });
                }
            }

            size_t ByteRunCount = 0;
            for (size_t Offset = 0; Offset < MappingBytesRead && ByteRunCount < 32;)
            {
                if (MappingBytes[Offset] > 30)
                {
                    Offset++;
                    continue;
                }
                const size_t Begin = Offset;
                std::array<bool, 31> Seen{};
                while (Offset < MappingBytesRead && MappingBytes[Offset] <= 30)
                {
                    Seen[MappingBytes[Offset]] = true;
                    Offset++;
                }
                const size_t Length = Offset - Begin;
                const size_t Distinct = static_cast<size_t>(std::count(Seen.begin(), Seen.end(), true));
                if (Length >= 16 && Distinct >= 4)
                {
                    MaterialMappingProbe["compact_index_runs"].push_back({
                        {"encoding", "u8"}, {"offset", Begin}, {"length", Length},
                        {"distinct_values", Distinct}
                    });
                    ByteRunCount++;
                }
            }

            size_t UInt32RunCount = 0;
            for (size_t Offset = 0; Offset + sizeof(uint32_t) <= MappingBytesRead && UInt32RunCount < 32;)
            {
                uint32_t Value = 0;
                std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                if (Value > 30)
                {
                    Offset += sizeof(uint32_t);
                    continue;
                }
                const size_t Begin = Offset;
                std::array<bool, 31> Seen{};
                while (Offset + sizeof(uint32_t) <= MappingBytesRead)
                {
                    std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                    if (Value > 30)
                        break;
                    Seen[Value] = true;
                    Offset += sizeof(uint32_t);
                }
                const size_t Length = (Offset - Begin) / sizeof(uint32_t);
                const size_t Distinct = static_cast<size_t>(std::count(Seen.begin(), Seen.end(), true));
                if (Length >= 4 && Distinct >= 3)
                {
                    MaterialMappingProbe["compact_index_runs"].push_back({
                        {"encoding", "u32"}, {"offset", Begin}, {"length", Length},
                        {"distinct_values", Distinct}
                    });
                    UInt32RunCount++;
                }
            }

            auto IsLikelyUserPointer = [](uint64_t Value) -> bool
            {
                return Value >= 0x100000000ull && Value < 0x800000000000ull;
            };
            std::vector<std::pair<uint64_t, size_t>> PointerCandidates;
            PointerCandidates.emplace_back(Pointer0010, static_cast<size_t>(-1));
            std::unordered_set<uint64_t> SeenPointers = { Pointer0010 };
            for (size_t Offset = 0; Offset + sizeof(uint64_t) <= MappingBytesRead &&
                PointerCandidates.size() < 96; Offset += sizeof(uint64_t))
            {
                uint64_t Value = 0;
                std::memcpy(&Value, MappingBuffer + Offset, sizeof(Value));
                if (IsLikelyUserPointer(Value) && KnownImages.find(Value) == KnownImages.end() &&
                    SeenPointers.insert(Value).second)
                {
                    PointerCandidates.emplace_back(Value, Offset);
                }
            }

            size_t ValidMaterialCount = 0;
            for (const auto& PointerCandidate : PointerCandidates)
            {
                if (ValidMaterialCount >= 16)
                    break;
                constexpr uintptr_t MaterialHeaderSize = 0x158;
                uintptr_t MaterialBytesRead = 0;
                auto MaterialHeader = CoDAssets::GameInstance->Read(
                    static_cast<uintptr_t>(PointerCandidate.first), MaterialHeaderSize, MaterialBytesRead);
                if (MaterialHeader == nullptr || MaterialBytesRead != MaterialHeaderSize)
                {
                    delete[] MaterialHeader;
                    continue;
                }
                auto ReadMaterialUInt64 = [MaterialHeader](size_t Offset) -> uint64_t
                {
                    uint64_t Value = 0;
                    std::memcpy(&Value, MaterialHeader + Offset, sizeof(Value));
                    return Value;
                };
                const uint64_t NameHash = ReadMaterialUInt64(0x00) & 0x0FFFFFFFFFFFFFFFull;
                const uint64_t TechsetPointer = ReadMaterialUInt64(0x28);
                const uint64_t ImageTablePointer = ReadMaterialUInt64(0x30);
                const uint64_t ConstantBufferSize = ReadMaterialUInt64(0x110);
                const uint64_t ConstantBufferPointer = ReadMaterialUInt64(0x118);
                const uint8_t ImageCount = MaterialHeader[0x148];
                const bool Plausible = NameHash != 0 && IsLikelyUserPointer(TechsetPointer) &&
                    IsLikelyUserPointer(ImageTablePointer) && ImageCount > 0 && ImageCount <= 128 &&
                    ConstantBufferSize <= MaximumCaptureBytes &&
                    (ConstantBufferSize == 0 || IsLikelyUserPointer(ConstantBufferPointer));
                if (!Plausible)
                {
                    delete[] MaterialHeader;
                    continue;
                }

                nlohmann::json ReferencedTerrainBindings = nlohmann::json::array();
                const uint64_t ImageTableBytes = static_cast<uint64_t>(ImageCount) * 0x18;
                uintptr_t ImageTableBytesRead = 0;
                auto MaterialImageTable = CoDAssets::GameInstance->Read(
                    static_cast<uintptr_t>(ImageTablePointer), static_cast<uintptr_t>(ImageTableBytes),
                    ImageTableBytesRead);
                if (MaterialImageTable != nullptr && ImageTableBytesRead == ImageTableBytes)
                {
                    for (uint8_t ImageIndex = 0; ImageIndex < ImageCount; ImageIndex++)
                    {
                        uint64_t ImagePointer = 0;
                        uint32_t SemanticHash = 0;
                        std::memcpy(&ImagePointer, MaterialImageTable + static_cast<size_t>(ImageIndex) * 0x18,
                            sizeof(ImagePointer));
                        std::memcpy(&SemanticHash,
                            MaterialImageTable + static_cast<size_t>(ImageIndex) * 0x18 + 8,
                            sizeof(SemanticHash));
                        const auto KnownImage = KnownImages.find(ImagePointer);
                        if (KnownImage != KnownImages.end())
                        {
                            ReferencedTerrainBindings.push_back({
                                {"material_image_index", ImageIndex},
                                {"binding_id", KnownImage->second},
                                {"semantic_hash", Strings::Format("0x%08X", SemanticHash)}
                            });
                        }
                    }
                }
                delete[] MaterialImageTable;

                const auto CandidateFileName = Strings::Format("mapping_material_%02u_header.bin",
                    static_cast<uint32_t>(ValidMaterialCount));
                auto HeaderCapture = CaptureBuffer(PointerCandidate.first, MaterialHeaderSize, 1,
                    CandidateFileName, "BOCWXMaterialEx candidate discovered by bounded mapping-root pointer scan");
                Captures.push_back(HeaderCapture);
                nlohmann::json Candidate = {
                    {"pointer", Strings::Format("0x%llX", PointerCandidate.first)},
                    {"source_offset", PointerCandidate.second == static_cast<size_t>(-1)
                        ? nlohmann::json(nullptr) : nlohmann::json(PointerCandidate.second)},
                    {"name_hash", Strings::Format("0x%llX", NameHash)},
                    {"techset_pointer", Strings::Format("0x%llX", TechsetPointer)},
                    {"image_table_pointer", Strings::Format("0x%llX", ImageTablePointer)},
                    {"image_count", ImageCount},
                    {"constant_buffer_size", ConstantBufferSize},
                    {"referenced_terrain_bindings", ReferencedTerrainBindings},
                    {"header_capture", HeaderCapture}
                };
                if (ImageTableBytesRead == ImageTableBytes)
                {
                    const auto TableFileName = Strings::Format("mapping_material_%02u_images.bin",
                        static_cast<uint32_t>(ValidMaterialCount));
                    auto TableCapture = CaptureBuffer(ImageTablePointer, ImageCount, 0x18,
                        TableFileName, "BOCWXMaterialImage table for mapping candidate");
                    Captures.push_back(TableCapture);
                    Candidate["image_table_capture"] = TableCapture;
                }
                MaterialMappingProbe["material_candidates"].push_back(Candidate);
                ValidMaterialCount++;
                delete[] MaterialHeader;
            }
            MaterialMappingProbe["known_image_reference_count"] =
                MaterialMappingProbe["known_image_references"].size();
            MaterialMappingProbe["material_candidate_count"] =
                MaterialMappingProbe["material_candidates"].size();
        }
        else
        {
            MaterialMappingProbe["status"] = "root_read_failed";
        }
        delete[] MappingBuffer;
    }

    // Decode the 0x118 pointer triples now that the binding table is known, so
    // each image can say whether the ordinary 0x38 array already carries it.
    // The ones that answer no are the point: they are layer textures reachable
    // only through here, and they are what makes this table worth capturing.
    nlohmann::json LayerMaterialImages = {
        {"status", CaptureResearch ? "not_attempted" : "disabled"},
        {"table_pointer", Strings::Format("0x%llX", Pointer0118)},
        {"record_count", Count0110},
        {"triples_per_record", 4},
        {"triple_order", "gloss, color, normal"},
        {"basis", "measured on two captures; the stride is not documented, so "
                  "layer_material_images.bin keeps the raw bytes"}
    };
    if (CaptureResearch && Pointer0118 != 0 && Count0110 > 0 && Count0110 <= 64)
    {
        const uint64_t TriplesPerRecord = 4;
        const uint64_t PointersPerRecord = TriplesPerRecord * 3;
        const uint64_t TableBytes = Count0110 * PointersPerRecord * sizeof(uint64_t);
        uintptr_t TableBytesRead = 0;
        auto TableBuffer = CoDAssets::GameInstance->Read(
            static_cast<uintptr_t>(Pointer0118), static_cast<uintptr_t>(TableBytes), TableBytesRead);
        if (TableBuffer != nullptr && TableBytesRead == TableBytes)
        {
            auto AlreadyBound = [&TerrainImagePointers](uint64_t Value)
            {
                for (const auto Bound : TerrainImagePointers)
                {
                    if (Bound == Value)
                        return true;
                }
                return false;
            };
            static const char* const TripleRoles[3] = { "gloss", "color", "normal" };
            nlohmann::json Records = nlohmann::json::array();
            uint32_t OutsideBindingTable = 0;
            uint32_t Identified = 0;
            for (uint64_t RecordIndex = 0; RecordIndex < Count0110; RecordIndex++)
            {
                nlohmann::json Triples = nlohmann::json::array();
                for (uint64_t Triple = 0; Triple < TriplesPerRecord; Triple++)
                {
                    nlohmann::json Entry = { {"triple", Triple} };
                    for (uint32_t Slot = 0; Slot < 3; Slot++)
                    {
                        const uint64_t Offset = (RecordIndex * PointersPerRecord +
                            Triple * 3 + Slot) * sizeof(uint64_t);
                        uint64_t ImagePointer = 0;
                        std::memcpy(&ImagePointer, TableBuffer + Offset, sizeof(ImagePointer));
                        nlohmann::json Image = {
                            {"image_pointer", Strings::Format("0x%llX", ImagePointer)}
                        };
                        if (ImagePointer == 0)
                        {
                            Image["status"] = "null";
                        }
                        else
                        {
                            uintptr_t HeaderBytesRead = 0;
                            auto HeaderBuffer = CoDAssets::GameInstance->Read(
                                static_cast<uintptr_t>(ImagePointer), sizeof(BOCWGfxImage), HeaderBytesRead);
                            if (HeaderBuffer != nullptr && HeaderBytesRead == sizeof(BOCWGfxImage))
                            {
                                BOCWGfxImage ImageInfo{};
                                std::memcpy(&ImageInfo, HeaderBuffer, sizeof(ImageInfo));
                                const uint64_t NameHash = ImageInfo.NamePtr & 0x0FFFFFFFFFFFFFFFull;
                                Image["status"] = "captured";
                                Image["name_hash"] = Strings::Format("0x%llX", NameHash);
                                Image["image_format"] = ImageInfo.ImageFormat;
                                Image["width"] = ImageInfo.LoadedMipWidth;
                                Image["height"] = ImageInfo.LoadedMipHeight;
                                const auto Named = GameBlackOpsCW::AssetNameCache.NameDatabase.find(NameHash);
                                if (Named != GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                                    Image["resolved_name"] = Named->second;
                                const bool Bound = AlreadyBound(ImagePointer);
                                Image["in_binding_table"] = Bound;
                                if (!Bound)
                                    OutsideBindingTable++;
                                Identified++;
                            }
                            else
                            {
                                Image["status"] = "header_read_failed";
                            }
                            delete[] HeaderBuffer;
                        }
                        Entry[TripleRoles[Slot]] = Image;
                    }
                    Triples.push_back(Entry);
                }
                Records.push_back({ {"record", RecordIndex}, {"triples", Triples} });
            }
            LayerMaterialImages["status"] = "captured";
            LayerMaterialImages["records"] = Records;
            LayerMaterialImages["images_identified"] = Identified;
            LayerMaterialImages["images_outside_binding_table"] = OutsideBindingTable;
        }
        else
        {
            LayerMaterialImages["status"] = "table_read_failed";
        }
        delete[] TableBuffer;
    }

    nlohmann::json MaterialLayers = nlohmann::json::array();
    nlohmann::json AbsorbedColorImages = nlohmann::json::array();
    std::vector<size_t> AlbedoMarkers;
    for (size_t Index = 0; Index < ImageBindings.size(); Index++)
    {
        const uint32_t BindingId = ImageBindings[Index].value("binding_id", 0u);
        const uint32_t ImageFormat = ImageBindings[Index].value("image_format", 0u);
        const auto ScanName = ImageBindings[Index].value("resolved_name", std::string());
        const bool ScanIsSourceLayer = ScanName.empty()
            ? BindingId >= 15
            : ScanName.compare(0, 3, "i_t") == 0;
        if (ScanIsSourceLayer && (ImageFormat == 72 || ImageFormat == 99))
        {
            if (AlbedoMarkers.empty() || Index > AlbedoMarkers.back() + 1)
            {
                AlbedoMarkers.push_back(Index);
            }
            else
            {
                // Adjacent colour images fold into the family that precedes them. That
                // is right for the shared macro/micro noise textures and wrong for a
                // genuine variant, so record every one and let the counts be audited.
                AbsorbedColorImages.push_back({
                    {"binding_id", BindingId},
                    {"resolved_name", ScanName},
                    {"folded_into_family", AlbedoMarkers.empty() ? 0 : AlbedoMarkers.size() - 1}
                });
            }
        }
    }

    for (size_t LayerIndex = 0; LayerIndex < AlbedoMarkers.size(); LayerIndex++)
    {
        const size_t AlbedoIndex = AlbedoMarkers[LayerIndex];
        const size_t BeginIndex = AlbedoIndex > 0 ? AlbedoIndex - 1 : AlbedoIndex;
        const size_t EndIndex = LayerIndex + 1 < AlbedoMarkers.size()
            ? AlbedoMarkers[LayerIndex + 1] - 1 : ImageBindings.size();
        nlohmann::json LayerBindings = nlohmann::json::array();
        size_t StandardNormalIndex = SIZE_MAX;
        const uint32_t AlbedoWidth = ImageBindings[AlbedoIndex].value("width", 0u);
        const uint32_t AlbedoHeight = ImageBindings[AlbedoIndex].value("height", 0u);
        for (size_t BindingIndex = BeginIndex; BindingIndex < EndIndex; BindingIndex++)
        {
            LayerBindings.push_back({
                {"binding_id", ImageBindings[BindingIndex].value("binding_id", 0u)},
                {"resolved_name", ImageBindings[BindingIndex].value("resolved_name", std::string())},
                {"image_format", ImageBindings[BindingIndex].value("image_format", 0u)},
                {"width", ImageBindings[BindingIndex].value("width", 0u)},
                {"height", ImageBindings[BindingIndex].value("height", 0u)},
                {"png_file", ImageBindings[BindingIndex].value("layer_resource_png_file",
                    ImageBindings[BindingIndex].value("layer_png_file", std::string()))},
                {"standard_normal_png_file", ImageBindings[BindingIndex].value(
                    "standard_normal_png_file", std::string())}
            });
            const auto StandardNormal = ImageBindings[BindingIndex].value(
                "standard_normal_png_file", std::string());
            const auto ResourceName = ImageBindings[BindingIndex].value("resolved_name", std::string());
            if (!StandardNormal.empty() &&
                ImageBindings[BindingIndex].value("width", 0u) == AlbedoWidth &&
                ImageBindings[BindingIndex].value("height", 0u) == AlbedoHeight &&
                ResourceName.find("macro") == std::string::npos &&
                ResourceName.find("noise") == std::string::npos)
            {
                StandardNormalIndex = BindingIndex;
            }
        }

        // Strip the engine's "i_t<n>_" prefix and "_c" suffix to name the family.
        const auto AlbedoName = ImageBindings[AlbedoIndex].value("resolved_name", std::string());
        std::string FamilyName = AlbedoName;
        if (FamilyName.size() > 5 && FamilyName.compare(0, 3, "i_t") == 0)
        {
            const auto Underscore = FamilyName.find('_', 3);
            if (Underscore != std::string::npos)
                FamilyName.erase(0, Underscore + 1);
        }
        if (FamilyName.size() > 2 && FamilyName.compare(FamilyName.size() - 2, 2, "_c") == 0)
            FamilyName.erase(FamilyName.size() - 2);

        nlohmann::json Layer = {
            {"index", LayerIndex},
            {"albedo_binding_id", ImageBindings[AlbedoIndex].value("binding_id", 0u)},
            {"albedo_name_hash", ImageBindings[AlbedoIndex].value("name_hash", std::string())},
            {"albedo_resolved_name", AlbedoName},
            {"family", FamilyName},
            {"albedo_png_file", ImageBindings[AlbedoIndex].value("layer_png_file", std::string())},
            {"bindings", LayerBindings},
            {"interpretation", "source material layer bounded by repeating albedo markers"},
            {"confidence", "structural_pattern"}
        };
        if (AlbedoIndex + 1 < EndIndex && ImageBindings[AlbedoIndex + 1].value("image_format", 0u) == 98)
        {
            Layer["surface_or_normal_candidate_binding_id"] =
                ImageBindings[AlbedoIndex + 1].value("binding_id", 0u);
        }
        if (StandardNormalIndex != SIZE_MAX)
        {
            Layer["normal_binding_id"] = ImageBindings[StandardNormalIndex].value("binding_id", 0u);
            Layer["normal_resolved_name"] = ImageBindings[StandardNormalIndex].value(
                "resolved_name", std::string());
            Layer["normal_png_file"] = ImageBindings[StandardNormalIndex].value(
                "standard_normal_png_file", std::string());
            Layer["normal_decode"] =
                "named _n resource: signed XY in R/G with derived positive Z preview";
        }
        MaterialLayers.push_back(Layer);
    }

    // The local families occupy the top of the legal slot range, so the offset falls out
    // of the two counts rather than being assumed. On the captured map this gives 31 - 22 = 9,
    // which is also what terrain slope independently selects: the three cliff-wall families
    // land on the three steepest painted indices and the four asphalt families on the four
    // flat indices beside the roads.
    // Measure the offset rather than assert it. An earlier build derived it as
    // slot_count - layer_count from a single capture; three maps falsified that.
    // Scoring every offset by how much painted area lands on a slot with no local
    // family selects 0 on all three, and uses no colour, slope or name inference.
    nlohmann::json MaterialIndexMapping = {
        {"hypothesis", "material_index = source_layer_order + offset"},
        {"legal_slot_count", LegalMaterialSlotCount},
        {"layer_count", MaterialLayers.size()},
        {"basis", "measured: the offset minimising painted area whose slot has no local family"},
        {"known_discrepancy", "on the rural capture the slot painted over the road network resolves to a cliff-wall family; unexplained"}
    };
    if (!MaterialIndexSamples.empty() && !MaterialLayers.empty() && LegalMaterialSlotCount > 0)
    {
        constexpr size_t SlotHistogramSize = 256;
        std::vector<uint64_t> SlotHistogram(SlotHistogramSize, 0);
        for (const auto Value : MaterialIndexSamples)
            SlotHistogram[Value]++;

        const double Total = static_cast<double>(MaterialIndexSamples.size());
        const uint64_t FamilyCount = MaterialLayers.size();
        nlohmann::json Sweep = nlohmann::json::array();
        uint64_t BestOffset = 0;
        double BestFraction = 2.0;
        double RunnerUpFraction = 2.0;
        for (uint64_t Offset = 0; Offset <= LegalMaterialSlotCount; Offset++)
        {
            uint64_t Unexplained = 0;
            for (uint64_t Slot = 0; Slot < SlotHistogramSize; Slot++)
            {
                if (SlotHistogram[Slot] == 0)
                    continue;
                const bool HasFamily = Slot >= Offset && (Slot - Offset) < FamilyCount;
                if (!HasFamily)
                    Unexplained += SlotHistogram[Slot];
            }
            const double Fraction = static_cast<double>(Unexplained) / Total;
            Sweep.push_back({{"offset", Offset}, {"unexplained_area_fraction", Fraction}});
            if (Fraction < BestFraction)
            {
                RunnerUpFraction = BestFraction;
                BestFraction = Fraction;
                BestOffset = Offset;
            }
            else if (Fraction < RunnerUpFraction)
            {
                RunnerUpFraction = Fraction;
            }
        }

        MeasuredMaterialIndexOffset = BestOffset;
        MeasuredMaterialIndexOffsetValid = true;
        MaterialIndexMapping["measured_offset"] = BestOffset;
        MaterialIndexMapping["unexplained_area_fraction"] = BestFraction;
        MaterialIndexMapping["margin"] = RunnerUpFraction - BestFraction;
        MaterialIndexMapping["sweep"] = Sweep;
        for (uint64_t Slot = 0; Slot < SlotHistogramSize; Slot++)
        {
            if (SlotHistogram[Slot] != 0)
                SlotPaintedTexels[std::to_string(Slot)] = SlotHistogram[Slot];
        }
        for (auto& Layer : MaterialLayers)
            Layer["material_index"] = Layer.value("index", 0ull) + BestOffset;
    }
    else
    {
        MaterialIndexMapping["status"] = "no_index_map_captured";
    }

    nlohmann::json MaterialLayerModel = {
        {"status", MaterialLayers.empty() ? "not_identified" : "source_layers_identified"},
        {"layer_count", MaterialLayers.size()},
        {"material_index_mapping", MaterialIndexMapping},
        {"absorbed_color_images", AbsorbedColorImages},
        {"basis", "repeating BC1/BC7 albedo markers with adjacent BC4 masks and BC7 surface candidates; correlated with GDC slides 43-49 and 94-126"},
        {"runtime_note", "BOCW ships a virtual-texture composite; Greyhound exports source layers and emits no terrain mesh"},
        {"layers", MaterialLayers}
    };

    nlohmann::json ControlMaps = nlohmann::json::object();
    if (!MaterialIndexSamples.empty())
    {
        std::vector<uint64_t> Histogram(256, 0);
        for (const auto Value : MaterialIndexSamples)
            Histogram[Value]++;
        uint32_t DistinctValues = 0;
        nlohmann::json NonzeroHistogram = nlohmann::json::object();
        for (uint32_t Value = 0; Value < Histogram.size(); Value++)
        {
            if (Histogram[Value] == 0)
                continue;
            DistinctValues++;
            NonzeroHistogram[std::to_string(Value)] = Histogram[Value];
        }
        ControlMaps["material_index"] = {
            {"binding_id", MaterialIndexBindingId},
            {"format", "R8_UINT"},
            {"resolution", {MaterialIndexWidth, MaterialIndexHeight}},
            {"role", "material_index_map"},
            {"distinct_values", DistinctValues},
            {"histogram", NonzeroHistogram},
            {"documentation_correlation", "GDC slides 94-126 OMPV/index-map blending; BOCW VT removes the need for this classification at final runtime shading, but the source control map remains useful for reconstruction"}
        };
    }
    if (!TerrainControlSamples.empty())
    {
        auto SortedControls = TerrainControlSamples;
        std::sort(SortedControls.begin(), SortedControls.end());
        const auto UniqueEnd = std::unique(SortedControls.begin(), SortedControls.end());
        ControlMaps["packed_control_grid"] = {
            {"binding_id", TerrainControlBindingId},
            {"format", "R32_UINT"},
            {"resolution", {TerrainControlWidth, TerrainControlHeight}},
            {"role", "packed_257_control_grid"},
            {"unique_packed_values", std::distance(SortedControls.begin(), UniqueEnd)},
            {"channel_semantics", "unresolved"},
            {"evidence", "packed byte planes contain spatially coherent but different terrain features"}
        };
    }

    if (CaptureResearch && MaterialMappingProbe.find("decoded_arrays") != MaterialMappingProbe.end())
    {
        std::array<bool, 256> Observed{};
        for (const auto Value : MaterialIndexSamples)
            Observed[Value] = true;
        nlohmann::json ObservedIndices = nlohmann::json::array();
        nlohmann::json UnobservedLegalIndices = nlohmann::json::array();
        size_t ObservedCount = 0;
        // Walk this capture's own slot count. The loop used to stop at 30,
        // which is the rural map's legal slot count; on a capture with 51 the
        // probe then reported the rural map's numbers and quietly hid every
        // painted slot above 30 -- exactly the range that needed explaining.
        const uint32_t HighestLegalSlot = static_cast<uint32_t>(
            LegalMaterialSlotCount > 0 && LegalMaterialSlotCount <= 256
                ? LegalMaterialSlotCount - 1 : 255);
        for (uint32_t Index = 0; Index <= HighestLegalSlot; Index++)
        {
            if (Observed[Index])
            {
                ObservedIndices.push_back(Index);
                ObservedCount++;
            }
            else
            {
                UnobservedLegalIndices.push_back(Index);
            }
        }
        uint32_t ObservedAboveLegal = 0;
        for (uint32_t Index = HighestLegalSlot + 1; Index < 256; Index++)
            ObservedAboveLegal += Observed[Index] ? 1 : 0;
        const auto& DecodedArrays = MaterialMappingProbe["decoded_arrays"];
        const size_t KnownImageMatches =
            DecodedArrays.value("indices_slots_u64", nlohmann::json::object())
                .value("known_image_pointer_matches", 0u) +
            DecodedArrays.value("indices_slots_unknown_u64", nlohmann::json::object())
                .value("known_image_pointer_matches", 0u);
        MaterialMappingProbe["cross_checks"] = {
            {"observed_material_indices", ObservedIndices},
            {"observed_index_count", ObservedCount},
            {"unobserved_legal_indices", UnobservedLegalIndices},
            {"source_layer_sequence_count", MaterialLayers.size()},
            {"known_image_pointer_matches_in_slot_entry_candidates", KnownImageMatches},
            {"legal_slot_count", LegalMaterialSlotCount},
            {"observed_indices_above_legal_slot_count", ObservedAboveLegal},
            {"conclusion", Strings::Format(
                "the 256-record lookup maps indices to reveal priority, not "
                "source-layer sequence; none of the captured arrays resolves "
                "the %llu-slot to %llu-layer assignment on this capture",
                static_cast<uint64_t>(ObservedCount),
                static_cast<uint64_t>(MaterialLayers.size()))}
        };
    }

    const auto DataTextureDirectory = FileSystems::CombinePath(ExportPath, "terrain_images");
    if (!MaterialIndexSamples.empty())
    {
        DirectX::ScratchImage IndexTexture;
        const auto InitializeResult = IndexTexture.Initialize2D(DXGI_FORMAT_R8G8B8A8_UNORM,
            MaterialIndexWidth, MaterialIndexHeight, 1, 1);
        const auto IndexPixels = SUCCEEDED(InitializeResult) ? IndexTexture.GetImage(0, 0, 0) : nullptr;
        if (IndexPixels != nullptr)
        {
            for (uint32_t Row = 0; Row < MaterialIndexHeight; Row++)
            {
                auto TargetRow = IndexPixels->pixels + static_cast<size_t>(Row) * IndexPixels->rowPitch;
                for (uint32_t Column = 0; Column < MaterialIndexWidth; Column++)
                {
                    const auto Value = MaterialIndexSamples[static_cast<size_t>(Row) * MaterialIndexWidth + Column];
                    TargetRow[Column * 4 + 0] = Value;
                    TargetRow[Column * 4 + 1] = 0;
                    TargetRow[Column * 4 + 2] = 0;
                    TargetRow[Column * 4 + 3] = 255;
                }
            }
            const auto OutputPath = FileSystems::CombinePath(DataTextureDirectory,
                "terrain_material_index_data.png");
            const auto SaveResult = DirectX::SaveToWICFile(*IndexPixels,
                DirectX::WIC_FLAGS::WIC_FLAGS_NONE,
                DirectX::GetWICCodec(DirectX::WICCodecs::WIC_CODEC_PNG),
                Strings::ToUnicodeString(OutputPath).c_str());
            if (SUCCEEDED(SaveResult))
                MaterialIndexTextureUri = "terrain_images/terrain_material_index_data.png";
            ControlMaps["material_index"]["data_texture"] = MaterialIndexTextureUri.empty()
                ? nlohmann::json(nullptr) : nlohmann::json(MaterialIndexTextureUri);
            ControlMaps["material_index"]["texture_encoding"] = "index stored exactly in R; G/B=0, A=255; sample without interpolation";
        }
    }
    if (!TerrainControlSamples.empty())
    {
        DirectX::ScratchImage ControlTexture;
        const auto InitializeResult = ControlTexture.Initialize2D(DXGI_FORMAT_R8G8B8A8_UNORM,
            TerrainControlWidth, TerrainControlHeight, 1, 1);
        const auto ControlPixels = SUCCEEDED(InitializeResult) ? ControlTexture.GetImage(0, 0, 0) : nullptr;
        if (ControlPixels != nullptr)
        {
            for (uint32_t Row = 0; Row < TerrainControlHeight; Row++)
            {
                auto TargetRow = ControlPixels->pixels + static_cast<size_t>(Row) * ControlPixels->rowPitch;
                for (uint32_t Column = 0; Column < TerrainControlWidth; Column++)
                {
                    const auto Value = TerrainControlSamples[static_cast<size_t>(Row) * TerrainControlWidth + Column];
                    TargetRow[Column * 4 + 0] = static_cast<uint8_t>(Value);
                    TargetRow[Column * 4 + 1] = static_cast<uint8_t>(Value >> 8);
                    TargetRow[Column * 4 + 2] = static_cast<uint8_t>(Value >> 16);
                    TargetRow[Column * 4 + 3] = static_cast<uint8_t>(Value >> 24);
                }
            }
            const auto OutputPath = FileSystems::CombinePath(DataTextureDirectory,
                "terrain_control_rgba.png");
            const auto SaveResult = DirectX::SaveToWICFile(*ControlPixels,
                DirectX::WIC_FLAGS::WIC_FLAGS_NONE,
                DirectX::GetWICCodec(DirectX::WICCodecs::WIC_CODEC_PNG),
                Strings::ToUnicodeString(OutputPath).c_str());
            if (SUCCEEDED(SaveResult))
                TerrainControlTextureUri = "terrain_images/terrain_control_rgba.png";
            ControlMaps["packed_control_grid"]["data_texture"] = TerrainControlTextureUri.empty()
                ? nlohmann::json(nullptr) : nlohmann::json(TerrainControlTextureUri);
            ControlMaps["packed_control_grid"]["texture_encoding"] = "original little-endian R32_UINT bytes stored losslessly as RGBA";
            ControlMaps["packed_control_grid"]["documentation_candidate"] = "color-ramp or reveal control correlated with GDC slides 119-126; resolution mismatch prevents final assignment";
        }
    }

    // Greyhound preserves terrain inputs but deliberately produces no mesh.
    TerrainHoles = {
        {"source_binding_id", 10},
        {"encoding", "R32_UINT 8x4 bits per texel; LSB first; set bit means terrain present"},
        {"status", TerrainSolidMask.empty() ? "not_captured" : "decoded_source_mask"},
        {"mask_resolution", {TerrainSolidWidth, TerrainSolidHeight}},
        {"hole_texels", TerrainHoleTexels},
        {"applied_to_mesh", false}
    };
    if (TerrainHoleTexels)
        TerrainHoles["texel_bounds"] = {
            {"minimum", {TerrainHoleMinimumX, TerrainHoleMinimumY}},
            {"maximum", {TerrainHoleMaximumX, TerrainHoleMaximumY}}};
    nlohmann::json GeometryMetadata = {
        {"status", "source_only_no_mesh_generated"},
        {"source_binding_id", HeightBindingId},
        {"source_resolution", {HeightWidth, HeightHeight}},
        {"height_decode", RuntimeHeightDecodeValidated
            ? "runtime_unorm_mad" : "fallback_provisional_linear_unorm_to_bounds"},
        {"height_decode_validated", RuntimeHeightDecodeValidated},
        {"height_bias", RuntimeHeightBias},
        {"height_range", RuntimeHeightRange},
        {"terrain_origin_xy", {RuntimeTerrainOriginX, RuntimeTerrainOriginY}},
        {"runtime_cell_size", RuntimeTerrainCellSize},
        {"runtime_height_dimensions", {RuntimeHeightWidth, RuntimeHeightHeight}},
        {"base_color_texture", BaseColorTextureUri},
        {"base_color_binding_id", BaseColorBindingId},
        {"material_index_texture", MaterialIndexTextureUri},
        {"material_index_binding_id", MaterialIndexBindingId},
        {"terrain_control_texture", TerrainControlTextureUri},
        {"terrain_control_binding_id", TerrainControlBindingId},
        {"holes", TerrainHoles.value<std::string>("status", "not_decoded")}
    };

    // Inventory named map-wide terrain images loaded outside the TerrainGfx binding
    // table. These are candidates for VT color/combined tiles and renderer resources.
    if (CoDAssets::GameAssets != nullptr)
    {
        for (const auto Asset : CoDAssets::GameAssets->LoadedAssets)
        {
            if (Asset == nullptr || Asset->AssetType != WraithAssetType::Image)
                continue;
            std::string Name = Asset->AssetName;
            const auto Image = static_cast<const CoDImage_t*>(Asset);
            const auto Header = CoDAssets::GameInstance->Read<BOCWGfxImage>(Image->AssetPointer);
            const uint64_t NameHash = Header.NamePtr & 0x0FFFFFFFFFFFFFFFull;
            const auto Resolved = GameBlackOpsCW::AssetNameCache.NameDatabase.find(NameHash);
            if (Resolved != GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                Name = Resolved->second;
            const bool Candidate =
                Name.find("terrain_color_map_") != std::string::npos ||
                Name.find("terrain_combined_maps_") != std::string::npos ||
                Name.find("terrain_height_maps_") != std::string::npos ||
                Name.find("superterrain") != std::string::npos;
            if (!Candidate)
                continue;
            LoadedTerrainImageCandidates.push_back({
                {"name", Name},
                {"name_hash", Strings::Format("0x%llX", NameHash)},
                {"asset_pointer", Strings::Format("0x%llX", Image->AssetPointer)},
                {"width", Image->Width}, {"height", Image->Height},
                {"format", Image->Format}
            });
        }
    }
    if (LoadedTerrainImageCandidates.empty() && CoDAssets::GameOffsetInfos.size() > 2 &&
        CoDAssets::GamePoolSizes.size() > 2)
    {
        const uint64_t ImagePoolBytes =
            static_cast<uint64_t>(CoDAssets::GamePoolSizes[2]) * sizeof(BOCWGfxImage);
        if (ImagePoolBytes != 0 && ImagePoolBytes <= 512ull * 1024ull * 1024ull)
        {
            uintptr_t PoolBytesRead = 0;
            auto Pool = CoDAssets::GameInstance->Read(
                static_cast<uintptr_t>(CoDAssets::GameOffsetInfos[2]),
                static_cast<uintptr_t>(ImagePoolBytes), PoolBytesRead);
            if (Pool != nullptr && PoolBytesRead == ImagePoolBytes)
            {
                for (uint32_t Index = 0; Index < CoDAssets::GamePoolSizes[2]; Index++)
                {
                    BOCWGfxImage Image{};
                    std::memcpy(&Image, Pool + static_cast<size_t>(Index) * sizeof(Image), sizeof(Image));
                    const uint64_t NameHash = Image.NamePtr & 0x0FFFFFFFFFFFFFFFull;
                    const auto Resolved = GameBlackOpsCW::AssetNameCache.NameDatabase.find(NameHash);
                    if (Resolved == GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                        continue;
                    const auto& Name = Resolved->second;
                    const bool Candidate =
                        Name.find("terrain_color_map_") != std::string::npos ||
                        Name.find("terrain_combined_maps_") != std::string::npos ||
                        Name.find("terrain_height_maps_") != std::string::npos ||
                        Name.find("superterrain") != std::string::npos;
                    if (!Candidate)
                        continue;
                    LoadedTerrainImageCandidates.push_back({
                        {"name", Name}, {"name_hash", Strings::Format("0x%llX", NameHash)},
                        {"asset_pointer", Strings::Format("0x%llX",
                            CoDAssets::GameOffsetInfos[2] + static_cast<uint64_t>(Index) * sizeof(Image))},
                        {"width", Image.LoadedMipWidth}, {"height", Image.LoadedMipHeight},
                        {"format", Image.ImageFormat}, {"pool_index", Index},
                        {"loaded_mip_pointer", Strings::Format("0x%llX", Image.LoadedMipPtr)},
                        {"mip_table_pointer", Strings::Format("0x%llX", Image.GfxMipsPtr)}
                    });
                }
            }
            delete[] Pool;
        }
    }

    // TerrainGfx itself does not own its draw material. Bridge that gap by
    // scanning the live BOCW material pool and retaining only materials whose
    // image table points at one of this TerrainGfx asset's known images. From
    // those materials we can walk techset -> pass -> shader and reflect the
    // resource bindings used by the renderer (including VT resources).
    nlohmann::json TerrainMaterialShaderProbe = {
        {"status", CaptureResearch ? "not_attempted" : "disabled"},
        {"purpose", "bridge TerrainGfx images to live material techniques and shader resource bindings"},
        {"matched_materials", nlohmann::json::array()},
        {"matched_material_count", 0},
        {"selection", "materials binding four or more of this capture's terrain "
                      "images, or any map-wide terrain image"},
        {"captured_shader_count", 0}
    };
    if (CaptureResearch && CoDAssets::GameOffsetInfos.size() > 3 &&
        CoDAssets::GamePoolSizes.size() > 3 && !TerrainImagePointers.empty())
    {
        constexpr uint64_t MaterialStride = 0x158;
        constexpr uint64_t MaterialImageStride = 0x18;
        constexpr uint64_t MaximumMaterialPoolBytes = 512ull * 1024ull * 1024ull;
        constexpr uint64_t MaximumShaderBytes = 16ull * 1024ull * 1024ull;
        constexpr uint64_t MaximumTotalShaderBytes = 128ull * 1024ull * 1024ull;
        constexpr size_t MaximumMatchedMaterials = 256;
        constexpr size_t MaximumCapturedShaders = 128;
        const uint64_t MaterialPoolPointer = CoDAssets::GameOffsetInfos[3];
        const uint32_t MaterialPoolCount = CoDAssets::GamePoolSizes[3];
        const uint64_t MaterialPoolBytes = static_cast<uint64_t>(MaterialPoolCount) * MaterialStride;
        TerrainMaterialShaderProbe["material_pool_pointer"] = Strings::Format("0x%llX", MaterialPoolPointer);
        TerrainMaterialShaderProbe["material_pool_count"] = MaterialPoolCount;
        TerrainMaterialShaderProbe["material_pool_bytes"] = MaterialPoolBytes;

        std::unordered_map<uint64_t, uint32_t> TerrainImageByPointer;
        for (size_t Index = 0; Index < TerrainImagePointers.size() &&
            Index < TerrainImageBindingIds.size(); Index++)
        {
            TerrainImageByPointer[TerrainImagePointers[Index]] = TerrainImageBindingIds[Index];
        }

        auto IsLikelyUserPointer = [](uint64_t Value) -> bool
        {
            return Value >= 0x100000000ull && Value < 0x800000000000ull;
        };

        // Terrain layer materials are named mc/t<generation>_<family> with an
        // optional _dsp or _blend variant. Not one of them contains the word
        // "terrain", which is why the old substring test matched nothing on
        // any capture -- the probe has been reporting scanned_no_matches for
        // materials that were sitting right there.
        auto LooksLikeTerrainLayerMaterial = [](const std::string& Name) -> bool
        {
            if (Name.find("terrain") != std::string::npos)
                return true;
            if (Name.size() < 7 || Name.compare(0, 4, "mc/t") != 0)
                return false;
            return Name[4] >= '0' && Name[4] <= '9' && Name[5] == '_';
        };

        // The map-wide images are the ones a terrain material must bind to be
        // the terrain rather than a prop that happens to share a detail
        // texture. Their binding ids are not stable across maps -- 7/8/11/12
        // on the rural capture, 14 through 19 on mp_dune -- so take them from
        // what this capture actually resolved.
        std::unordered_set<uint32_t> DefiningTerrainBindings;
        for (const uint32_t DefiningId : { HeightBindingId, BaseColorBindingId,
            TerrainNormalBindingId, MaterialIndexBindingId, TerrainControlBindingId })
        {
            if (DefiningId != 0)
                DefiningTerrainBindings.insert(DefiningId);
        }
        TerrainMaterialShaderProbe["defining_binding_ids"] = DefiningTerrainBindings;
        TerrainMaterialShaderProbe["layer_material_name_convention"] =
            "mc/t<generation>_<family>[_dsp|_blend]";
        auto ReadUInt64 = [](const int8_t* Bytes, size_t Offset) -> uint64_t
        {
            uint64_t Value = 0;
            std::memcpy(&Value, Bytes + Offset, sizeof(Value));
            return Value;
        };

        auto ReflectShaderResources = [](const int8_t* ShaderBytes, uint64_t ShaderSize) -> nlohmann::json
        {
            nlohmann::json Result = {
                {"status", "reflection_failed"},
                {"bound_resources", nlohmann::json::array()}
            };
            IDxcLibrary* Library = nullptr;
            IDxcContainerReflection* Container = nullptr;
            IDxcBlobEncoding* Blob = nullptr;
            ID3D12ShaderReflection* Reflection = nullptr;
            UINT32 ShaderIndex = 0;
            D3D12_SHADER_DESC ShaderDescription{};
            const bool Reflected =
                !FAILED(DXCDLLSupport.Initialize()) &&
                !FAILED(DXCDLLSupport.CreateInstance(CLSID_DxcContainerReflection, &Container)) &&
                !FAILED(DXCDLLSupport.CreateInstance(CLSID_DxcLibrary, &Library)) &&
                !FAILED(Library->CreateBlobWithEncodingFromPinned(
                    const_cast<int8_t*>(ShaderBytes), static_cast<UINT32>(ShaderSize), 0, &Blob)) &&
                !FAILED(Container->Load(Blob)) &&
                !FAILED(Container->FindFirstPartKind(hlsl::DFCC_ShaderStatistics, &ShaderIndex)) &&
                !FAILED(Container->GetPartReflection(ShaderIndex,
                    __uuidof(ID3D12ShaderReflection), reinterpret_cast<void**>(&Reflection))) &&
                !FAILED(Reflection->GetDesc(&ShaderDescription));
            if (Reflected)
            {
                Result["status"] = "reflected";
                Result["bound_resource_count"] = ShaderDescription.BoundResources;
                Result["constant_buffer_count"] = ShaderDescription.ConstantBuffers;
                Result["instruction_count"] = ShaderDescription.InstructionCount;
                for (UINT ResourceIndex = 0; ResourceIndex < ShaderDescription.BoundResources; ResourceIndex++)
                {
                    D3D12_SHADER_INPUT_BIND_DESC Binding{};
                    if (FAILED(Reflection->GetResourceBindingDesc(ResourceIndex, &Binding)))
                        continue;
                    Result["bound_resources"].push_back({
                        {"name", Binding.Name == nullptr ? "" : Binding.Name},
                        {"type", static_cast<uint32_t>(Binding.Type)},
                        {"bind_point", Binding.BindPoint},
                        {"bind_count", Binding.BindCount},
                        {"space", Binding.Space},
                        {"dimension", static_cast<uint32_t>(Binding.Dimension)},
                        {"return_type", static_cast<uint32_t>(Binding.ReturnType)},
                        {"flags", static_cast<uint32_t>(Binding.uFlags)},
                        {"sample_count", Binding.NumSamples}
                    });
                }
            }
            if (Reflection != nullptr) Reflection->Release();
            if (Blob != nullptr) Blob->Release();
            if (Library != nullptr) Library->Release();
            if (Container != nullptr) Container->Release();
            return Result;
        };

        if (MaterialPoolBytes == 0 || MaterialPoolBytes > MaximumMaterialPoolBytes)
        {
            TerrainMaterialShaderProbe["status"] = "rejected_material_pool_bounds";
        }
        else
        {
            uintptr_t MaterialPoolBytesRead = 0;
            auto MaterialPool = CoDAssets::GameInstance->Read(
                static_cast<uintptr_t>(MaterialPoolPointer),
                static_cast<uintptr_t>(MaterialPoolBytes), MaterialPoolBytesRead);
            if (MaterialPool == nullptr || MaterialPoolBytesRead != MaterialPoolBytes)
            {
                TerrainMaterialShaderProbe["status"] = "material_pool_read_failed";
            }
            else
            {
                TerrainMaterialShaderProbe["status"] = "scanned_no_matches";
                std::unordered_map<uint64_t, nlohmann::json> ShaderByDescriptorPointer;
                uint64_t TotalCapturedShaderBytes = 0;
                size_t CapturedShaderCount = 0;
                const uint64_t MaterialPoolEnd = MaterialPoolPointer + MaterialPoolBytes;
                const char* ShaderStageNames[4] = {"vertex", "hull", "domain", "pixel"};
                for (uint32_t MaterialIndex = 0; MaterialIndex < MaterialPoolCount &&
                    TerrainMaterialShaderProbe["matched_materials"].size() < MaximumMatchedMaterials;
                    MaterialIndex++)
                {
                    const int8_t* Material = MaterialPool + static_cast<size_t>(MaterialIndex) * MaterialStride;
                    const uint64_t FirstValue = ReadUInt64(Material, 0x00);
                    if ((FirstValue > MaterialPoolPointer && FirstValue < MaterialPoolEnd) || FirstValue == 0)
                        continue;
                    const uint64_t MaterialNameHash = FirstValue & 0x0FFFFFFFFFFFFFFFull;
                    const uint64_t TechsetPointer = ReadUInt64(Material, 0x28);
                    const uint64_t ImageTablePointer = ReadUInt64(Material, 0x30);
                    const uint8_t ImageCount = Material[0x148];
                    if (MaterialNameHash == 0 || !IsLikelyUserPointer(TechsetPointer) ||
                        !IsLikelyUserPointer(ImageTablePointer) || ImageCount == 0 || ImageCount > 128)
                        continue;

                    const uint64_t ImageTableBytes = static_cast<uint64_t>(ImageCount) * MaterialImageStride;
                    uintptr_t ImageTableBytesRead = 0;
                    auto ImageTable = CoDAssets::GameInstance->Read(
                        static_cast<uintptr_t>(ImageTablePointer),
                        static_cast<uintptr_t>(ImageTableBytes), ImageTableBytesRead);
                    if (ImageTable == nullptr || ImageTableBytesRead != ImageTableBytes)
                    {
                        delete[] ImageTable;
                        continue;
                    }
                    nlohmann::json TerrainImageMatches = nlohmann::json::array();
                    nlohmann::json MaterialImages = nlohmann::json::array();
                    for (uint8_t ImageIndex = 0; ImageIndex < ImageCount; ImageIndex++)
                    {
                        const int8_t* ImageEntry = ImageTable + static_cast<size_t>(ImageIndex) * MaterialImageStride;
                        const uint64_t ImagePointer = ReadUInt64(ImageEntry, 0x00);
                        uint32_t SemanticHash = 0;
                        std::memcpy(&SemanticHash, ImageEntry + 0x08, sizeof(SemanticHash));
                        const auto TerrainImage = TerrainImageByPointer.find(ImagePointer);
                        const bool InTerrainTable = TerrainImage != TerrainImageByPointer.end();
                        nlohmann::json Entry = {
                            {"material_image_index", ImageIndex},
                            {"image_pointer", Strings::Format("0x%llX", ImagePointer)},
                            {"semantic_hash", Strings::Format("0x%08X", SemanticHash)},
                            {"in_terrain_binding_table", InTerrainTable}
                        };
                        if (InTerrainTable)
                            Entry["binding_id"] = TerrainImage->second;
                        // Name it. A layer texture the TerrainGfx array never
                        // lists is exactly what this probe exists to surface,
                        // and without the name it is only a pointer.
                        if (IsLikelyUserPointer(ImagePointer))
                        {
                            uintptr_t ImageHeaderRead = 0;
                            auto ImageHeader = CoDAssets::GameInstance->Read(
                                static_cast<uintptr_t>(ImagePointer), sizeof(BOCWGfxImage), ImageHeaderRead);
                            if (ImageHeader != nullptr && ImageHeaderRead == sizeof(BOCWGfxImage))
                            {
                                BOCWGfxImage BoundImage{};
                                std::memcpy(&BoundImage, ImageHeader, sizeof(BoundImage));
                                const uint64_t BoundNameHash = BoundImage.NamePtr & 0x0FFFFFFFFFFFFFFFull;
                                Entry["image_name_hash"] = Strings::Format("0x%llX", BoundNameHash);
                                Entry["width"] = BoundImage.LoadedMipWidth;
                                Entry["height"] = BoundImage.LoadedMipHeight;
                                const auto BoundName =
                                    GameBlackOpsCW::AssetNameCache.NameDatabase.find(BoundNameHash);
                                if (BoundName != GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                                    Entry["resolved_name"] = BoundName->second;
                            }
                            delete[] ImageHeader;
                        }
                        MaterialImages.push_back(Entry);
                        if (InTerrainTable)
                            TerrainImageMatches.push_back(Entry);
                    }
                    delete[] ImageTable;

                    const auto ResolvedMaterialName = GameBlackOpsCW::AssetNameCache.NameDatabase.find(MaterialNameHash);
                    const bool NameLooksTerrain = ResolvedMaterialName !=
                        GameBlackOpsCW::AssetNameCache.NameDatabase.end() &&
                        LooksLikeTerrainLayerMaterial(ResolvedMaterialName->second);
                    if (TerrainImageMatches.empty() && !NameLooksTerrain)
                        continue;

                    bool MatchesDefiningTerrainResource = false;
                    std::unordered_set<uint32_t> DistinctTerrainBindings;
                    for (const auto& Match : TerrainImageMatches)
                    {
                        const uint32_t BindingId = Match.value("binding_id", UINT32_MAX);
                        DistinctTerrainBindings.insert(BindingId);
                        MatchesDefiningTerrainResource = MatchesDefiningTerrainResource ||
                            DefiningTerrainBindings.count(BindingId) != 0;
                    }
                    // Tiny defaults and even source detail images are shared by many
                    // unrelated materials, and the mc/t<n>_ name convention covers
                    // every asset material in the game, not just terrain. What
                    // separates them is how many terrain images they bind: measured
                    // over 58368 materials the distribution is bimodal -- 167 bind
                    // none, 53 bind exactly one shared default, then nothing until
                    // the 15 layer materials that bind four to seven. Cut there.
                    constexpr size_t MinimumLayerTerrainImages = 4;
                    const bool BindsLayerTextureSet =
                        TerrainImageMatches.size() >= MinimumLayerTerrainImages;
                    if (!BindsLayerTextureSet && !MatchesDefiningTerrainResource)
                        continue;

                    nlohmann::json MaterialResult = {
                        {"pool_index", MaterialIndex},
                        {"pointer", Strings::Format("0x%llX",
                            MaterialPoolPointer + static_cast<uint64_t>(MaterialIndex) * MaterialStride)},
                        {"name_hash", Strings::Format("0x%llX", MaterialNameHash)},
                        {"techset_pointer", Strings::Format("0x%llX", TechsetPointer)},
                        {"image_count", ImageCount},
                        {"matches_defining_terrain_resource", MatchesDefiningTerrainResource},
                        {"name_looks_terrain", NameLooksTerrain},
                        {"binds_layer_texture_set", BindsLayerTextureSet},
                        {"distinct_terrain_binding_count", DistinctTerrainBindings.size()},
                        {"terrain_image_matches", TerrainImageMatches},
                        {"images", MaterialImages},
                        {"passes", nlohmann::json::array()}
                    };
                    if (ResolvedMaterialName != GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                        MaterialResult["resolved_name"] = ResolvedMaterialName->second;

                    constexpr size_t TechniqueSetSize = 3 * sizeof(uint64_t) + 18 * sizeof(uint64_t);
                    uintptr_t TechniqueSetBytesRead = 0;
                    auto TechniqueSet = CoDAssets::GameInstance->Read(
                        static_cast<uintptr_t>(TechsetPointer), TechniqueSetSize, TechniqueSetBytesRead);
                    if (TechniqueSet != nullptr && TechniqueSetBytesRead == TechniqueSetSize)
                    {
                        MaterialResult["techset_hash"] = Strings::Format("0x%llX", ReadUInt64(TechniqueSet, 0x00));
                        for (uint32_t PassIndex = 0; PassIndex < 18; PassIndex++)
                        {
                            const uint64_t TechniquePointer = ReadUInt64(TechniqueSet,
                                3 * sizeof(uint64_t) + static_cast<size_t>(PassIndex) * sizeof(uint64_t));
                            if (!IsLikelyUserPointer(TechniquePointer))
                                continue;
                            constexpr size_t TechniqueSize = 0x30;
                            uintptr_t TechniqueBytesRead = 0;
                            auto Technique = CoDAssets::GameInstance->Read(
                                static_cast<uintptr_t>(TechniquePointer), TechniqueSize, TechniqueBytesRead);
                            if (Technique == nullptr || TechniqueBytesRead != TechniqueSize)
                            {
                                delete[] Technique;
                                continue;
                            }
                            const uint64_t ShaderTablePointer = ReadUInt64(Technique, 0x28);
                            nlohmann::json PassResult = {
                                {"pass_index", PassIndex},
                                {"technique_pointer", Strings::Format("0x%llX", TechniquePointer)},
                                {"technique_hash", Strings::Format("0x%llX", ReadUInt64(Technique, 0x00))},
                                {"shader_table_pointer", Strings::Format("0x%llX", ShaderTablePointer)},
                                {"shaders", nlohmann::json::array()}
                            };
                            delete[] Technique;
                            if (!IsLikelyUserPointer(ShaderTablePointer))
                            {
                                MaterialResult["passes"].push_back(PassResult);
                                continue;
                            }
                            for (uint32_t StageIndex = 0; StageIndex < 4; StageIndex++)
                            {
                                const uint64_t ShaderDescriptorPointer = CoDAssets::GameInstance->Read<uint64_t>(
                                    ShaderTablePointer + static_cast<uint64_t>(StageIndex) * sizeof(uint64_t));
                                if (!IsLikelyUserPointer(ShaderDescriptorPointer))
                                    continue;
                                const auto ExistingShader = ShaderByDescriptorPointer.find(ShaderDescriptorPointer);
                                if (ExistingShader != ShaderByDescriptorPointer.end())
                                {
                                    auto ShaderReference = ExistingShader->second;
                                    ShaderReference["stage"] = ShaderStageNames[StageIndex];
                                    ShaderReference["reused_capture"] = true;
                                    PassResult["shaders"].push_back(ShaderReference);
                                    continue;
                                }

                                constexpr size_t ShaderDescriptorSize = 0x18;
                                uintptr_t ShaderDescriptorBytesRead = 0;
                                auto ShaderDescriptor = CoDAssets::GameInstance->Read(
                                    static_cast<uintptr_t>(ShaderDescriptorPointer), ShaderDescriptorSize,
                                    ShaderDescriptorBytesRead);
                                if (ShaderDescriptor == nullptr || ShaderDescriptorBytesRead != ShaderDescriptorSize)
                                {
                                    delete[] ShaderDescriptor;
                                    continue;
                                }
                                const uint64_t ShaderHash = ReadUInt64(ShaderDescriptor, 0x00);
                                const uint64_t ShaderPointer = ReadUInt64(ShaderDescriptor, 0x08);
                                const uint64_t ShaderSize = ReadUInt64(ShaderDescriptor, 0x10);
                                delete[] ShaderDescriptor;
                                if (!IsLikelyUserPointer(ShaderPointer) || ShaderSize == 0 ||
                                    ShaderSize > MaximumShaderBytes ||
                                    TotalCapturedShaderBytes + ShaderSize > MaximumTotalShaderBytes ||
                                    CapturedShaderCount >= MaximumCapturedShaders)
                                    continue;
                                uintptr_t ShaderBytesRead = 0;
                                auto ShaderBytes = CoDAssets::GameInstance->Read(
                                    static_cast<uintptr_t>(ShaderPointer), static_cast<uintptr_t>(ShaderSize),
                                    ShaderBytesRead);
                                if (ShaderBytes == nullptr || ShaderBytesRead != ShaderSize)
                                {
                                    delete[] ShaderBytes;
                                    continue;
                                }
                                const auto ShaderFileName = Strings::Format(
                                    "terrain_shader_%016llx.dxil.bin", ShaderHash);
                                const auto ShaderPath = FileSystems::CombinePath(ExportPath, ShaderFileName);
                                auto ShaderWriter = BinaryWriter();
                                const bool ShaderWritten = ShaderWriter.Create(ShaderPath);
                                if (ShaderWritten)
                                {
                                    ShaderWriter.Write(ShaderBytes, static_cast<uint32_t>(ShaderSize));
                                    ShaderWriter.Close();
                                }
                                nlohmann::json ShaderResult = {
                                    {"stage", ShaderStageNames[StageIndex]},
                                    {"descriptor_pointer", Strings::Format("0x%llX", ShaderDescriptorPointer)},
                                    {"hash", Strings::Format("0x%llX", ShaderHash)},
                                    {"pointer", Strings::Format("0x%llX", ShaderPointer)},
                                    {"size", ShaderSize},
                                    {"file", ShaderWritten ? nlohmann::json(ShaderFileName) : nlohmann::json(nullptr)},
                                    {"reflection", ReflectShaderResources(ShaderBytes, ShaderSize)}
                                };
                                delete[] ShaderBytes;
                                ShaderByDescriptorPointer[ShaderDescriptorPointer] = ShaderResult;
                                PassResult["shaders"].push_back(ShaderResult);
                                TotalCapturedShaderBytes += ShaderSize;
                                CapturedShaderCount++;
                            }
                            MaterialResult["passes"].push_back(PassResult);
                        }
                    }
                    delete[] TechniqueSet;
                    TerrainMaterialShaderProbe["matched_materials"].push_back(MaterialResult);
                    TerrainMaterialShaderProbe["status"] = "captured";
                }
                TerrainMaterialShaderProbe["captured_shader_count"] = CapturedShaderCount;
                TerrainMaterialShaderProbe["captured_shader_bytes"] = TotalCapturedShaderBytes;
            }
            delete[] MaterialPool;
        }
        TerrainMaterialShaderProbe["matched_material_count"] =
            TerrainMaterialShaderProbe["matched_materials"].size();
    }

    // Decode the slot table. Every stage downstream has been inferring which
    // source family each painted slot uses from colour and slope; the engine
    // states it outright, one XMaterial* per slot, and the material's own image
    // table names the family. The inference stays in the pipeline as a fallback
    // for captures where this table is absent or its material is not resident.
    nlohmann::json SlotMaterials = {
        {"status", CaptureResearch ? "not_attempted" : "disabled"},
        {"table_pointer", Strings::Format("0x%llX", SlotMaterialTablePointer)},
        {"slot_count", LegalMaterialSlotCount},
        {"record_stride", SlotMaterialRecordStride},
        {"basis", "mapping root 0x110: one XMaterial* at offset 0 of each "
                  "0x130-byte record; validated against the shipped virtual "
                  "texture at p = 0.0005 over 2000 permutations"},
        {"slots", nlohmann::json::array()}
    };
    if (CaptureResearch && SlotMaterialTablePointer != 0 &&
        LegalMaterialSlotCount > 0 && LegalMaterialSlotCount <= 256 &&
        CoDAssets::GameOffsetInfos.size() > 3 && CoDAssets::GamePoolSizes.size() > 3)
    {
        constexpr uint64_t PoolMaterialStride = 0x158;
        constexpr uint64_t MaterialImageStride = 0x18;
        const uint64_t PoolBase = CoDAssets::GameOffsetInfos[3];
        const uint64_t PoolCount = CoDAssets::GamePoolSizes[3];
        const uint64_t TableBytes = LegalMaterialSlotCount * SlotMaterialRecordStride;
        uintptr_t TableRead = 0;
        auto Table = CoDAssets::GameInstance->Read(
            static_cast<uintptr_t>(SlotMaterialTablePointer),
            static_cast<uintptr_t>(TableBytes), TableRead);
        if (Table != nullptr && TableRead == TableBytes)
        {
            std::unordered_map<uint32_t, size_t> LayerByAlbedoBinding;
            for (size_t LayerIndex = 0; LayerIndex < MaterialLayers.size(); LayerIndex++)
            {
                const uint32_t AlbedoBinding =
                    MaterialLayers[LayerIndex].value("albedo_binding_id", UINT32_MAX);
                if (AlbedoBinding != UINT32_MAX)
                    LayerByAlbedoBinding[AlbedoBinding] = LayerIndex;
            }
            std::unordered_map<uint64_t, uint32_t> BindingByImagePointer;
            for (size_t Index = 0; Index < TerrainImagePointers.size() &&
                Index < TerrainImageBindingIds.size(); Index++)
            {
                BindingByImagePointer[TerrainImagePointers[Index]] = TerrainImageBindingIds[Index];
            }

            uint32_t ResolvedSlots = 0;
            uint32_t NamedSlots = 0;
            for (uint64_t Slot = 0; Slot < LegalMaterialSlotCount; Slot++)
            {
                uint64_t MaterialPointer = 0;
                std::memcpy(&MaterialPointer,
                    Table + static_cast<size_t>(Slot * SlotMaterialRecordStride),
                    sizeof(MaterialPointer));
                nlohmann::json Entry = {
                    {"slot", Slot},
                    {"material_pointer", Strings::Format("0x%llX", MaterialPointer)}
                };
                const uint64_t PoolOffset =
                    MaterialPointer > PoolBase ? MaterialPointer - PoolBase : 0;
                const bool InPool = MaterialPointer > PoolBase &&
                    PoolOffset % PoolMaterialStride == 0 &&
                    PoolOffset / PoolMaterialStride < PoolCount;
                if (!InPool)
                {
                    Entry["status"] = MaterialPointer == 0 ? "null" : "outside_material_pool";
                    SlotMaterials["slots"].push_back(Entry);
                    continue;
                }
                Entry["material_pool_index"] = PoolOffset / PoolMaterialStride;
                uintptr_t MaterialRead = 0;
                auto MaterialBytes = CoDAssets::GameInstance->Read(
                    static_cast<uintptr_t>(MaterialPointer),
                    static_cast<uintptr_t>(PoolMaterialStride), MaterialRead);
                if (MaterialBytes != nullptr && MaterialRead == PoolMaterialStride)
                {
                    ResolvedSlots++;
                    Entry["status"] = "captured";
                    uint64_t MaterialNamePointer = 0;
                    std::memcpy(&MaterialNamePointer, MaterialBytes, sizeof(MaterialNamePointer));
                    const uint64_t MaterialNameHash = MaterialNamePointer & 0x0FFFFFFFFFFFFFFFull;
                    Entry["material_name_hash"] = Strings::Format("0x%llX", MaterialNameHash);
                    const auto MaterialName =
                        GameBlackOpsCW::AssetNameCache.NameDatabase.find(MaterialNameHash);
                    if (MaterialName != GameBlackOpsCW::AssetNameCache.NameDatabase.end())
                        Entry["material_name"] = MaterialName->second;
                    uint64_t ImageTablePointer = 0;
                    std::memcpy(&ImageTablePointer, MaterialBytes + 0x30, sizeof(ImageTablePointer));
                    const uint8_t ImageCount = static_cast<uint8_t>(MaterialBytes[0x148]);
                    if (ImageTablePointer != 0 && ImageCount > 0 && ImageCount <= 128)
                    {
                        const uint64_t ImageBytes =
                            static_cast<uint64_t>(ImageCount) * MaterialImageStride;
                        uintptr_t ImagesRead = 0;
                        auto Images = CoDAssets::GameInstance->Read(
                            static_cast<uintptr_t>(ImageTablePointer),
                            static_cast<uintptr_t>(ImageBytes), ImagesRead);
                        if (Images != nullptr && ImagesRead == ImageBytes)
                        {
                            for (uint8_t ImageIndex = 0; ImageIndex < ImageCount; ImageIndex++)
                            {
                                uint64_t ImagePointer = 0;
                                std::memcpy(&ImagePointer,
                                    Images + static_cast<size_t>(ImageIndex) * MaterialImageStride,
                                    sizeof(ImagePointer));
                                const auto Binding = BindingByImagePointer.find(ImagePointer);
                                if (Binding == BindingByImagePointer.end())
                                    continue;
                                const auto Layer = LayerByAlbedoBinding.find(Binding->second);
                                if (Layer == LayerByAlbedoBinding.end())
                                    continue;
                                Entry["source_layer"] = Layer->second;
                                Entry["albedo_binding_id"] = Binding->second;
                                const auto Family = MaterialLayers[Layer->second].value(
                                    "albedo_resolved_name", std::string());
                                if (!Family.empty())
                                {
                                    Entry["family"] = Family;
                                    NamedSlots++;
                                }
                                break;
                            }
                        }
                        delete[] Images;
                    }
                }
                else
                {
                    Entry["status"] = "material_read_failed";
                }
                delete[] MaterialBytes;
                SlotMaterials["slots"].push_back(Entry);
            }
            SlotMaterials["status"] = "captured";
            SlotMaterials["slots_resolved_to_a_material"] = ResolvedSlots;
            SlotMaterials["slots_named_to_a_family"] = NamedSlots;
        }
        else
        {
            SlotMaterials["status"] = "table_read_failed";
        }
        delete[] Table;
    }

    nlohmann::json MaterialExports = {
        {"enabled", ExportMaterialDependencies},
        {"source_only_required", SourceOnly},
        {"purpose", "material TXT semantics and referenced images for offline reconstruction"}
    };
    if (ExportMaterialDependencies)
    {
        const auto Relative = Strings::Format("terrain_material_exports/run_%lu_%llu",
            GetCurrentProcessId(), GetTickCount64());
        const auto Root = FileSystems::CombinePath(ExportPath, Relative);
        MaterialExports["directory"] = Relative;
        MaterialExports["patch_normals"] = SettingsManager::GetSetting("patchnormals", "true") == "true";
        MaterialExports["image_format"] = SettingsManager::GetSetting("exportimg", "PNG");
        MaterialExports["materials"] = nlohmann::json::array();
        FileSystems::CreateDirectory(Root);
        std::unordered_map<std::string, bool> ExportedHashes;
        const auto Extension = "." + Strings::ToLower(SettingsManager::GetSetting("exportimg", "PNG"));
        for (const auto& Entry : SlotMaterials["slots"])
        {
            if (Entry.value("status", std::string()) != "captured" || !Entry.contains("material_name_hash"))
                continue;
            const auto Hash = Entry["material_name_hash"].get<std::string>();
            if (ExportedHashes[Hash])
                continue;
            ExportedHashes[Hash] = true;
            // The recovered Cold War material name is the dependency identity
            // whenever the slot table carries one, so the exported TXT and its
            // images land under that exact name. The deterministic hash form
            // stands in only when no name was recovered.
            auto Directory = "xmaterial_" + Strings::ToLower(Hash.substr(2));
            std::string NameStatus = "unresolved";
            if (Entry.contains("material_name") && Entry["material_name"].is_string())
            {
                const auto Recovered = Entry["material_name"].get<std::string>();
                bool Safe = !Recovered.empty() && Recovered.front() != '/'
                    && Recovered.back() != '/'
                    && Recovered.find("..") == std::string::npos
                    && Recovered.find("//") == std::string::npos;
                // Explicit ranges rather than std::isalnum: no <cctype>
                // dependency, and no locale sensitivity in an asset path.
                for (const auto Character : Recovered)
                {
                    const bool Allowed =
                        (Character >= 'a' && Character <= 'z') ||
                        (Character >= 'A' && Character <= 'Z') ||
                        (Character >= '0' && Character <= '9') ||
                        Character == '_' || Character == '.' ||
                        Character == '-' || Character == '/';
                    if (!Allowed)
                        Safe = false;
                }
                // An unsafe name is reported, never rewritten into a new one.
                NameStatus = Safe ? "resolved" : "unresolved_unsafe";
                if (Safe)
                    Directory = Recovered;
            }
            const auto Destination = FileSystems::CombinePath(Root, Directory);
            // A recovered name may carry the Cold War "mc/" prefix, so the
            // parent has to exist before the leaf directory is created.
            FileSystems::CreateDirectory(FileSystems::GetDirectoryName(Destination));
            FileSystems::CreateDirectory(Destination);
            CoDMaterial_t Dependency;
            Dependency.AssetPointer = std::stoull(Entry["material_pointer"].get<std::string>(), nullptr, 16);
            // The asset name becomes the TXT stem, so it must be the leaf of a
            // path-style name rather than the path itself.
            const auto Separator = Directory.find_last_of('/');
            Dependency.AssetName = Separator == std::string::npos
                ? Directory : Directory.substr(Separator + 1);
            // The normal material path owns naming, image decoding/patching,
            // TXT semantics and format settings. Asset-list visibility is
            // deliberately unrelated to dependency export.
            const auto Result = ExportMaterialAsset(&Dependency, Destination, Destination, "", Extension);
            MaterialExports["materials"].push_back({{"hash", Hash}, {"directory", Directory},
                {"material_name", NameStatus == "resolved"
                    ? nlohmann::json(Directory) : nlohmann::json(nullptr)},
                {"name_status", NameStatus},
                {"export_call_succeeded", Result == ExportGameResult::Success}});
        }
        // ExportMaterialAsset may succeed with missing image data. Its result
        // is not a completeness claim; inspect/import the files in the HTML
        // creator. Do not turn missing GDT inputs into a terrain export error.
    }

    bool AdditionalEvidenceWritten = false;
    if (SourceOnly)
    {
        std::vector<uint64_t> ProbeMaterials;
        for (const auto& M : TerrainMaterialShaderProbe["matched_materials"])
            ProbeMaterials.push_back(std::stoull(M["pointer"].get<std::string>(), nullptr, 16));
        AdditionalEvidenceWritten = GameBlackOpsCW::ExportTerrainResearch(Terrain, ExportPath, ProbeMaterials, ReportProgress);
    }
    nlohmann::json Metadata = {
        {"schema", "superterrain-research-v32"},
        {"source_only", SourceOnly},
        {"additional_evidence_written", AdditionalEvidenceWritten},
        {"additional_evidence_manifest", SourceOnly ? nlohmann::json("research/evidence.json") : nlohmann::json(nullptr)},
        {"game", "black_ops_cold_war"},
        {"asset_type", "TerrainGfx"},
        {"name", Terrain->AssetName},
        {"asset_pointer", Strings::Format("0x%llX", Terrain->AssetPointer)},
        {"header_size", Terrain->AssetSize},
        {"header_file", "header.terraingfx.bin"},
        {"research_capture_enabled", CaptureResearch},
        {"bounds", {
            {"minimum", {ReadHeaderFloat(0x18), ReadHeaderFloat(0x1C), ReadHeaderFloat(0x20)}},
            {"maximum", {ReadHeaderFloat(0x24), ReadHeaderFloat(0x28), ReadHeaderFloat(0x2C)}}
        }},
        {"verified_layout_fields", {
            {"grid_dimension_0050", ReadHeaderUInt32(0x50)},
            {"cell_size_0054_0058", {ReadHeaderFloat(0x54), ReadHeaderFloat(0x58)}},
            {"xy_extent_005c_0060", {ReadHeaderFloat(0x5C), ReadHeaderFloat(0x60)}},
            {"half_cell_0064_0068", {ReadHeaderFloat(0x64), ReadHeaderFloat(0x68)}},
            {"unknown_z_reference_006c", ReadHeaderFloat(0x6C)}
        }},
        {"candidate_fields", {
            {"pointer_0010", Strings::Format("0x%llX", Pointer0010)},
            {"count_0030", Count0030},
            {"pointer_0038", Strings::Format("0x%llX", Pointer0038)},
            {"count_0040", Count0040},
            {"pointer_0048", Strings::Format("0x%llX", Pointer0048)},
            {"pointer_0108", Strings::Format("0x%llX", Pointer0108)},
            {"count_0110", Count0110},
            {"pointer_0118", Strings::Format("0x%llX", Pointer0118)},
            {"value_0120", ReadHeaderFloat(0x120)},
            {"value_0124", ReadHeaderFloat(0x124)}
        }},
        {"captures", Captures},
        {"descriptor_probe", EntityProbe},
        {"material_mapping_probe", MaterialMappingProbe},
        {"image_bindings_status", ImageBindingsStatus},
        {"image_binding_names_resolved", ResolvedBindingNameCount},
        {"image_binding_name_source", "package_index/fnv1a_ximages.wni via GameBlackOpsCW::AssetNameCache"},
        {"terrain_holes", TerrainHoles},
        {"terrain_quadtree", TerrainQuadtree},
        {"image_bindings", ImageBindings},
        {"loaded_terrain_image_candidates", LoadedTerrainImageCandidates},
        {"terrain_material_shader_probe", TerrainMaterialShaderProbe},
        {"material_layer_model", MaterialLayerModel},
        {"terrain_slot_materials", SlotMaterials},
        {"terrain_material_exports", MaterialExports},
        {"terrain_layer_material_images", LayerMaterialImages},
        {"control_maps", ControlMaps},
        {"consumer_contract", {
            {"producer", "Greyhound"},
            {"mode", "source_data_only"},
            {"capture_root", "capture"},
            {"immutable_after_seal", true},
            {"reconstruction_started", false},
            {"consumer", "external terrain reconstruction tool"}
        }},
        {"documented_material_model", {
            {"material_layers", "GDC slides 43-49: reveal maps and alpha rules; only final alpha ships"},
            {"index_map", "GDC slides 94-126: most-prominent-layer index texel replaces alpha-map collection"},
            {"filtering", "gather four neighboring indices, combine duplicates, sort for reveal order, blend referenced layers"},
            {"unified_height_scope", "GDC slide 139: unified height does not replace layer alpha or index maps"},
            {"bocw_runtime", "GDC slides 155-157: VT plus unified height removes runtime surface-index/classification need"},
            {"consumer_note", "downstream tools can reconstruct materials from the shipped VT and preserved authoring/index/control resources"}
        }},
        {"geometry", GeometryMetadata},
        {"reference_validation", {
            {"t9_main", {
                {"asset_type_terraingfx", "0xB1"},
                {"xasset_pool_layout_confirmed", true},
                {"terrain_member_layout_present", false},
                {"scope", "pool/type confirmation only; not evidence for nested TerrainGfx fields"}
            }}
        }},
        {"decoded", false}
    };

    delete[] Header;

    auto MetadataWriter = TextWriter();
    if (!MetadataWriter.Create(MetadataPath))
    {
        return ExportGameResult::UnknownError;
    }
    MetadataWriter.Write(Metadata.dump(2));
    MetadataWriter.NewLine();

    return ExportGameResult::Success;
}

ExportGameResult CoDAssets::ExportMaterialAsset(const CoDMaterial_t* Material, const std::string& ExportPath, const std::string& ImagesPath, const std::string& ImageRelativePath, const std::string& ImageExtension)
{
    // Grab the image format type
    auto ImageFormatType = ImageFormat::Standard_PNG;
    // Check setting
    auto ImageSetting = SettingsManager::GetSetting("exportimg", "PNG");

    // Check it
    if (ImageSetting == "DDS")
    {
        ImageFormatType = ImageFormat::DDS_WithHeader;
    }
    else if (ImageSetting == "TGA")
    {
        ImageFormatType = ImageFormat::Standard_TGA;
    }
    else if (ImageSetting == "TIFF")
    {
        ImageFormatType = ImageFormat::Standard_TIFF;
    }

    XMaterial_t XMaterial(0);

    // Attempt to load it based on game
    switch (CoDAssets::GameID)
    {
    case SupportedGames::ModernWarfareRemastered:
        XMaterial = GameModernWarfareRM::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::BlackOps4:
        XMaterial = GameBlackOps4::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::ModernWarfare4:
        XMaterial = GameModernWarfare4::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::ModernWarfare5:
        XMaterial = GameModernWarfare5::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::ModernWarfare6:
        XMaterial = GameModernWarfare6::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::BlackOpsCW:
        XMaterial = GameBlackOpsCW::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::Vanguard:
        XMaterial = GameVanguard::ReadXMaterial(Material->AssetPointer);
        break;
    case SupportedGames::WorldWar2:
        XMaterial = GameWorldWar2::ReadXMaterial(Material->AssetPointer);
        break;
    }

    // Process Image Names
    ExportMaterialImageNames(XMaterial, ExportPath);
    // Process the material
    ExportMaterialImages(XMaterial, ExportPath, ImageExtension, ImageFormatType);

    // Success, unless specific error
    return ExportGameResult::Success;
}

void CoDAssets::ExportWraithModel(const std::unique_ptr<WraithModel>& Model, const std::string& ExportPath, bool CastOnly)
{
    // The source name was shortened before appending the generated LOD suffix.
    Model->AssetName = ModelExportNaming::Escape(Model->AssetName);
    if (CastOnly)
    {
        Model->ScaleModel(2.54f);
        Cast::ExportCastModel(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".cast"));
        return;
    }
    // MEL is a Maya helper, not a dependency of CAST or the other formats.
    if (SettingsManager::GetSetting("export_ma") == "true")
    {
        TextWriter Cosmetics;
        bool Created = false;
        for (auto& Bone : Model->Bones)
        {
            if (Bone.IsCosmetic)
            {
                if (!Created)
                {
                    Cosmetics.Create(FileSystems::CombinePath(ExportPath, Model->AssetName + "_cosmetics.mel"));
                    Created = true;
                }
                Cosmetics.WriteLineFmt("select -add %s;", Bone.TagName.c_str());
            }
        }
    }

    // Prepare to export to the formats specified in settings

    // Check for XME format
    if (SettingsManager::GetSetting("export_xmexport") == "true")
    {
        // Export a XME file
        CodXME::ExportXME(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".XMODEL_EXPORT"));
    }
    // Check for XMB format
    if (SettingsManager::GetSetting("export_xmbin") == "true")
    {
        // Export a XMB file
        CodXMB::ExportXMB(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".XMODEL_BIN"));
    }
    // Check for SMD format
    if (SettingsManager::GetSetting("export_smd") == "true")
    {
        // Export a SMD file
        ValveSMD::ExportSMD(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".smd"));
    }

    // The following formats are scaled
    Model->ScaleModel(2.54f);

    // Check for Obj format
    if (SettingsManager::GetSetting("export_obj") == "true")
    {
        // Export a Obj file
        WavefrontOBJ::ExportOBJ(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".obj"));
    }
    // Check for Maya format
    if (SettingsManager::GetSetting("export_ma") == "true")
    {
        // Export a Maya file
        Maya::ExportMaya(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".ma"));
    }
    // Check for XNALara format
    if (SettingsManager::GetSetting("export_xna") == "true")
    {
        // Export a XNALara file
        XNALara::ExportXNA(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".mesh.ascii"));
    }
    // Check for GLTF format
    if (SettingsManager::GetSetting("export_gltf") == "true")
    {
        // Export a GLTF file
        GLTF::ExportGLTF(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".gltf"));
    }
    // Check for GLB format
    if (SettingsManager::GetSetting("export_glb") == "true")
    {
        // Export a GLB file
        GLTF::ExportGLTF(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".glb"), false, true);
    }
    // Check for SEModel format
    if (SettingsManager::GetSetting("export_semodel") == "true")
    {
        // Export a SEModel file
        SEModel::ExportSEModel(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".semodel"));
    }
    // Check for Cast format
    if (SettingsManager::GetSetting("export_castmdl") == "true")
    {
        // Export a Cast file
        Cast::ExportCastModel(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".cast"));
    }
    // Check for FBX format
    if (SettingsManager::GetSetting("export_fbx") == "true")
    {
        // Export an FBX file
        // FBX::ExportFBX(*Model.get(), FileSystems::CombinePath(ExportPath, Model->AssetName + ".fbx"));
    }
}

void CoDAssets::CleanupPackageCache()
{
    // Check if even loaded
    if (GamePackageCache != nullptr)
    {
        // Wait until load completes
        GamePackageCache->WaitForPackageCacheLoad();

        // Clean up
        GamePackageCache.reset();
    }

    // Check if even loaded
    if (OnDemandCache != nullptr)
    {
        // Wait until load completes
        OnDemandCache->WaitForPackageCacheLoad();

        // Clean up
        OnDemandCache.reset();
    }
}

void CoDAssets::CleanUpGame()
{
    // Aquire a lock
    std::lock_guard<std::mutex> Lock(CodMutex);

    // Prepare to clean up game resources
    CleanupPackageCache();

    // Clean up assets cache
    if (GameAssets != nullptr)
    {
        GameAssets.reset();
    }

    // Clean up offsets
    GameOffsetInfos.clear();
    GamePoolSizes.clear();

    // Clean up Bo4 Asset Cache
    GameBlackOps4::AssetNameCache.NameDatabase.clear();

    // Clear global lists
    AssetNameCache.NameDatabase.clear();
    StringCache.NameDatabase.clear();

    // Set load handler
    GameXImageHandler = nullptr;

    // Set flags
    GameFlags = SupportedGameFlags::None;
    GameID = SupportedGames::None;

    // Clean up game instance
    if (GameInstance != nullptr)
    {
        GameInstance.reset();
    }

    // Clean Up log
    if (XAssetLogWriter != nullptr)
    {
        XAssetLogWriter.reset();
    }

    // Clean up Parasyte
    ps::state = nullptr;
}

void CoDAssets::LogXAsset(const std::string& Type, const std::string& Name)
{
    if (XAssetLogWriter != nullptr && XAssetLogWriter->IsOpen())
    {
        XAssetLogWriter->WriteLineFmt("%s,%s", Type.c_str(), Name.c_str());
    }
}

void CoDAssets::ExportMaterialImageNames(const XMaterial_t& Material, const std::string& ExportPath)
{
    // Global material folders may be shared by concurrent model exports.
    static std::mutex MaterialMetadataMutex;
    std::lock_guard<std::mutex> MetadataLock(MaterialMetadataMutex);
    // Try write the image name
    try
    {
        // Image Names Output
        TextWriter ImageNames;

        // Get File Name
        auto ImageNamesPath = FileSystems::CombinePath(ExportPath, Material.MaterialName + "_images.txt");

        // Create File
        ImageNames.Create(ImageNamesPath);
        // Write header
        //ImageNames.WriteLineFmt("# Material: %s", Material.MaterialName.c_str());
        //ImageNames.WriteLineFmt("# Techset/Type: %s", Material.TechsetName.c_str());
        ImageNames.WriteLine("semantic,image_name");
        // Write each name
        for (auto& Image : Material.Images)
        {
            if (SemanticHashes.find(Image.SemanticHash) != SemanticHashes.end())
            {
                ImageNames.WriteLineFmt("%s,%s", SemanticHashes[Image.SemanticHash].c_str(), Image.ImageName.c_str());
            }
            else
            {
                ImageNames.WriteLineFmt("unk_semantic_0x%X,%s", Image.SemanticHash, Image.ImageName.c_str());
            }
        }

        // Check if we have settings
        if (Material.Settings.size() > 0)
        {
            // Image Names Output
            TextWriter Settings;

            // Get File Name
            auto SettingsPath = FileSystems::CombinePath(ExportPath, Material.MaterialName + "_settings.txt");

            // Create File
            Settings.Create(SettingsPath);

            // Write header
            Settings.WriteLineFmt("# Material: %s", Material.MaterialName.c_str());
            Settings.WriteLineFmt("# Techset/Type: %s", Material.TechsetName.c_str());
            Settings.WriteLine("name,type,x,y,z,w");

            // Write each name
            for (auto& Setting : Material.Settings)
            {
                Settings.WriteLineFmt("%s,%s,%f,%f,%f,%f",
                    Setting.Name.c_str(),
                    Setting.Type.c_str(),
                    Setting.Data[0],
                    Setting.Data[1],
                    Setting.Data[2],
                    Setting.Data[3]);
            }
        }
    }
    catch (...)
    {
        // Failed
    }
}

void CoDAssets::ExportMaterialImages(const XMaterial_t& Material, const std::string& ImagesPath, const std::string& ImageExtension, ImageFormat ImageFormatType, const std::string& ReportsPath)
{
    // Images this material binds that could not be written.  _images.txt carries
    // a row for every bound semantic, so an image missing from disk used to be
    // invisible: nothing recorded that it had been attempted, or why it failed.
    std::vector<std::string> FailedImages;

    // Prepare to export material images
    for (auto& Image : Material.Images)
    {
        // Grab the full image path, if it doesn't exist convert it!
        auto FullImagePath = FileSystems::CombinePath(ImagesPath, Image.ImageName + ImageExtension);
        // Check if we want to skip previous images
        auto SkipPrevImages = SettingsManager::GetSetting("skipprevimg") == "true";
        // Check if it exists
        if (!FileSystems::FileExists(FullImagePath) || !SkipPrevImages)
        {
            // Buffer for the image (Loaded via the global game handler)
            std::unique_ptr<XImageDDS> ImageData = GameXImageHandler(Image);

            // Check if we got it
            if (ImageData != nullptr)
            {
                // Convert it to a file or just write the DDS data raw
                if (ImageFormatType == ImageFormat::DDS_WithHeader)
                {
                    // Since this can throw, wrap it in an exception handler
                    try
                    {
                        // Just write the buffer
                        auto Writer = BinaryWriter();
                        // Make the file
                        if (Writer.Create(FullImagePath))
                        {
                            // Write the DDS buffer
                            Writer.Write((const int8_t*)ImageData->DataBuffer, ImageData->DataSize);
                        }
                        else
                        {
                            FailedImages.push_back(Image.ImageName + ",dds_file_not_created");
                        }
                    }
                    catch (...)
                    {
                        // Nothing, this means that something is already accessing the image
                        FailedImages.push_back(Image.ImageName + ",dds_write_failed");
                    }
                }
                else
                {
                    // Convert it, this method is a nothrow
                    if (!Image::ConvertImageMemory(ImageData->DataBuffer, ImageData->DataSize, ImageFormat::DDS_WithHeader, FullImagePath, ImageFormatType, ImageData->ImagePatchType))
                    {
                        FailedImages.push_back(Image.ImageName + ",conversion_failed");
                    }
                }
            }
            else
            {
                // No mip could be served from the packages and none was resident
                FailedImages.push_back(Image.ImageName + ",image_data_unavailable");
            }
        }
    }

    // Only written when something failed, so a clean export stays clean
    if (!FailedImages.empty())
    {
        try
        {
            TextWriter Report;

            if (Report.Create(FileSystems::CombinePath(ReportsPath.empty() ? ImagesPath : ReportsPath, Material.MaterialName + "_images_failed.txt")))
            {
                Report.WriteLine("image_name,reason");

                for (auto& Failure : FailedImages)
                {
                    Report.WriteLine(Failure);
                }
            }
        }
        catch (...)
        {
            // Failed
        }
    }
}

void CoDAssets::ExportAllAssets(void* Caller)
{
    // Prepare to export all available assets
    auto AssetsToExport = std::make_unique<std::vector<CoDAsset_t*>>();

    // Grab the parent window and check mode
    auto MainView = (MainWindow*)Caller;
    // Resolve the asset list
    auto& LoadedAssets = (MainView->SearchMode) ? MainView->SearchResults : CoDAssets::GameAssets->LoadedAssets;

    // An index for the element position
    uint32_t AssetPosition = 0;
    // Load up the assets, just passing the array
    for (auto& Asset : LoadedAssets)
    {
        // Add and set
        Asset->AssetLoadedIndex = AssetPosition;
        AssetsToExport->emplace_back(Asset);

        // Advance
        AssetPosition++;
    }

    // Setup export logic
    AssetsToExportCount = (uint32_t)AssetsToExport->size();
    ExportedAssetsCount = 0;
    CanExportContinue = true;

    // Pass off to the export logic thread
    ExportSelectedAssets(Caller, AssetsToExport);

    // Force clean up
    AssetsToExport->shrink_to_fit();
    AssetsToExport.reset();
}

void CoDAssets::ExportSelection(const std::vector<uint32_t>& Indicies, void* Caller)
{
    // Prepare to export all available assets
    auto AssetsToExport = std::make_unique<std::vector<CoDAsset_t*>>();

    // Grab the parent window and check mode
    auto MainView = (MainWindow*)Caller;
    // Resolve the asset list
    auto& LoadedAssets = (MainView->SearchMode) ? MainView->SearchResults : CoDAssets::GameAssets->LoadedAssets;

    // Load up the assets, just passing the array
    for (auto& AssetIndex : Indicies)
    {
        // Grab and set
        auto& AssetUse = LoadedAssets[AssetIndex];

        // Set
        AssetUse->AssetLoadedIndex = AssetIndex;
        AssetsToExport->emplace_back(AssetUse);
    }

    // Setup export logic
    AssetsToExportCount = (uint32_t)AssetsToExport->size();
    ExportedAssetsCount = 0;
    CanExportContinue = true;

    // Pass off to the export logic thread
    ExportSelectedAssets(Caller, AssetsToExport);

    // Force clean up
    AssetsToExport->shrink_to_fit();
    AssetsToExport.reset();
}

void CoDAssets::ExportSelectedAssets(void* Caller, const std::unique_ptr<std::vector<CoDAsset_t*>>& Assets)
{
    // We must wait until the package cache is fully loaded before exporting
    if (GamePackageCache != nullptr)
    {
        // Wait for it to finish
        GamePackageCache->WaitForPackageCacheLoad();
    }

    // At this point, all of the assets are loaded into the queue, we can do this in async
    // We are gonna set the popup directory here, either the game's export path, or single export path.

    // Make sure we have one asset
    if (Assets->size() == 1)
    {
        // Set from this one asset
        LatestExportPath = BuildExportPath(Assets->at(0));
    }
    else if (Assets->size() > 0)
    {
        // Build the game specific path
        if (Assets->at(0)->AssetType == WraithAssetType::Model)
        {
            // Go back two
            LatestExportPath = FileSystems::GetDirectoryName(FileSystems::GetDirectoryName(BuildExportPath(Assets->at(0))));
        }
        else
        {
            // Go back one
            LatestExportPath = FileSystems::GetDirectoryName(BuildExportPath(Assets->at(0)));
        }
    }

    // The asset index we're on
    std::atomic<uint32_t> AssetIndex = 0;
    // The assets we need to convert
    uint32_t AssetsToConvert = (uint32_t)Assets->size();

    // Detect the number of conversion threads
    SYSTEM_INFO SystemInfo;
    // Fetch system info
    GetSystemInfo(&SystemInfo);
    // Get count
    auto NumberOfCores = SystemInfo.dwNumberOfProcessors;

#if _DEBUG
    // Clamp it, no less than 1, no more than 3
    auto DegreeOfConverter = 1;
#else
    // Clamp it, no less than 1, no more than 3
    auto DegreeOfConverter = VectorMath::Clamp<uint32_t>(NumberOfCores, 1, 3);
#endif
    // Terrain post-processing owns one shared progress bar and can run for
    // several minutes. Keep terrain batches ordered so concurrent workers do
    // not make the bar jump backwards between assets.
    if (std::any_of(Assets->begin(), Assets->end(), [](const CoDAsset_t* Asset)
        { return Asset != nullptr && Asset->AssetType == WraithAssetType::Terrain; }))
        DegreeOfConverter = 1;
    // Prepare to convert the assets in async
    CoDXConverter([&AssetIndex, &Caller, &Assets, &AssetsToConvert]
    {
        // Begin the image thread
        Image::SetupConversionThread();

        // Loop until we've done all assets or, until we cancel
        while (AssetIndex < AssetsToConvert && CoDAssets::CanExportContinue)
        {
            // Grab our index
            auto AssetToConvert = AssetIndex++;

            // Ensure still valid
            if (AssetToConvert >= Assets->size())
                continue;

            // Get the asset we need
            auto& Asset = Assets->at(AssetToConvert);
            // Make sure it's not a placeholder
#ifndef DEBUG
            if (Asset->AssetStatus != WraithAssetStatus::Placeholder)
#endif
            {
                // Set the status
                Asset->AssetStatus = WraithAssetStatus::Processing;
                // Report asset status
                if (OnExportStatus != nullptr)
                {
                    OnExportStatus(Caller, Asset->AssetLoadedIndex);
                }

                // Export it
                auto Result = ExportGameResult::UnknownError;

                // Export it
                try
                {
                    CoDAssets::Log->info("Exporting: {0}...", Asset->AssetName);
                    const uint32_t ProgressStart = static_cast<uint32_t>(
                        (100ull * AssetToConvert) / AssetsToConvert);
                    const uint32_t ProgressEnd = static_cast<uint32_t>(
                        (100ull * (AssetToConvert + 1)) / AssetsToConvert);
                    Result = CoDAssets::ExportAsset(Asset, Caller, ProgressStart,
                        ProgressEnd - ProgressStart);
                    CoDAssets::Log->info("Successfully exported: {0}", Asset->AssetName);
                }
                catch (std::exception& ex)
                {
                    CoDAssets::Log->error(ex.what());
                }


                // Set the status
                Asset->AssetStatus = (Result == ExportGameResult::Success) ? WraithAssetStatus::Exported : WraithAssetStatus::Error;
                // Report asset status
                if (OnExportStatus != nullptr)
                {
                    OnExportStatus(Caller, Asset->AssetLoadedIndex);
                }
            }

            // Advance
            CoDAssets::ExportedAssetsCount++;

            // Report
            if (OnExportProgress != nullptr)
            {
                OnExportProgress(Caller, (uint32_t)(((float)CoDAssets::ExportedAssetsCount / (float)CoDAssets::AssetsToExportCount) * 100.f));
            }
        }

        // End image conversion thread
        Image::DisableConversionThread();

        // We are spinning up a maximum of 3 threads for conversion
    }, DegreeOfConverter);
}
