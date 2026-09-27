#include "stdafx.h"

// The class we are implementing
#include "ui/native/UiBridge.h"

#include <algorithm>
#include <cctype>
#include <sstream>
#include <thread>
#include <shlobj.h>
#include <shobjidl.h>
#include "assets/CoDAssets.h"
#include "assets/AssetSearch.h"
#include "assets/preview/PreviewData.h"
#include "games/black_ops_4/capture/BO4CaptureModes.h"
#include "assets/SalukiNameDatabase.h"
#include "SettingsManager.h"
#include "FileSystems.h"
#include "Strings.h"
#include "WraithFileDialogs.h"

using nlohmann::json;

namespace
{
    // CoDAssets reports export progress through plain function pointers. Only
    // one v2 window exists, so they reach it here instead of through Caller,
    // which ExportJobs sometimes passes as null.
    UiBridge* Active = nullptr;

    std::string Dump(const json& Value)
    {
        // Asset names are not guaranteed to be UTF-8.
        return Value.dump(-1, ' ', false, json::error_handler_t::replace);
    }

    const char* TypeKey(const CoDAsset_t* Asset)
    {
        if (Asset->AssetType == WraithAssetType::Material && static_cast<const CoDMaterial_t*>(Asset)->IsVolumeDecal)
            return "decal";
        switch (Asset->AssetType)
        {
        case WraithAssetType::Model: return "model";
        case WraithAssetType::Animation: return "anim";
        case WraithAssetType::Image: return "image";
        case WraithAssetType::Sound: return "sound";
        case WraithAssetType::Material: return "material";
        case WraithAssetType::RawFile: return "rawfile";
        case WraithAssetType::Effect: return "effect";
        case WraithAssetType::Terrain: return "terrain";
        }
        return "unknown";
    }

    const char* StatusKey(WraithAssetStatus Status)
    {
        switch (Status)
        {
        case WraithAssetStatus::Loaded: return "loaded";
        case WraithAssetStatus::Exported: return "exported";
        case WraithAssetStatus::Processing: return "processing";
        case WraithAssetStatus::Placeholder: return "placeholder";
        case WraithAssetStatus::Error: return "error";
        case WraithAssetStatus::NotLoaded: return "notloaded";
        }
        return "unknown";
    }

    // Same text as the classic list's Details column.
    std::string Details(const CoDAsset_t* Asset)
    {
        switch (Asset->AssetType)
        {
        case WraithAssetType::Model:
        {
            auto Model = (const CoDModel_t*)Asset;
            if (Model->CosmeticBoneCount == 0)
                return Strings::Format("Bones: %d, LODs: %d", Model->BoneCount, Model->LodCount);
            return Strings::Format("Bones: %d, Cosmetics: %d, LODs: %d", Model->BoneCount, Model->CosmeticBoneCount, Model->LodCount);
        }
        case WraithAssetType::Animation:
        {
            auto Anim = (const CoDAnim_t*)Asset;
            return Strings::Format("Framerate: %.2f, Frames: %d, Bones: %d", Anim->Framerate, Anim->FrameCount, Anim->BoneCount);
        }
        case WraithAssetType::Image:
        {
            auto Image = (const CoDImage_t*)Asset;
            return Image->Width > 0 ? Strings::Format("Width: %d, Height: %d", Image->Width, Image->Height) : "N/A";
        }
        case WraithAssetType::Sound:
        {
            auto Sound = (const CoDSound_t*)Asset;
            return Sound->Length > 0 ? Strings::DurationToReadableTime(std::chrono::milliseconds(Sound->Length)) : "N/A";
        }
        case WraithAssetType::Material:
        {
            const auto Material = static_cast<const CoDMaterial_t*>(Asset);
            if (Material->IsVolumeDecal)
                return Strings::Format("Placements: %u | %s", Material->VolumeDecalInstances,
                    Material->VolumeDecalSupported ? "BO3 color/reveal" : "BO3 shader unsupported");
            return Strings::Format("Images: %llu", (unsigned long long)Material->ImageCount);
        }
        case WraithAssetType::RawFile:
            return Strings::Format("Size: 0x%llx", (unsigned long long)Asset->AssetSize);
        case WraithAssetType::Terrain:
            return Strings::Format("Header: 0x%llx bytes", (unsigned long long)Asset->AssetSize);
        }
        return {};
    }

    // Case-insensitive, with digit runs compared by value, so lod2 < lod10.
    int NaturalCompare(const std::string& A, const std::string& B)
    {
        size_t i = 0, j = 0;
        while (i < A.size() && j < B.size())
        {
            const unsigned char Ca = A[i], Cb = B[j];
            if (isdigit(Ca) && isdigit(Cb))
            {
                size_t Ea = i, Eb = j;
                while (Ea < A.size() && A[Ea] == '0') Ea++;
                while (Eb < B.size() && B[Eb] == '0') Eb++;
                size_t Da = Ea, Db = Eb;
                while (Da < A.size() && isdigit((unsigned char)A[Da])) Da++;
                while (Db < B.size() && isdigit((unsigned char)B[Db])) Db++;
                if (Da - Ea != Db - Eb) return Da - Ea < Db - Eb ? -1 : 1;
                const int Digits = A.compare(Ea, Da - Ea, B, Eb, Db - Eb);
                if (Digits != 0) return Digits;
                i = Da; j = Db;
                continue;
            }
            const int La = tolower(Ca), Lb = tolower(Cb);
            if (La != Lb) return La < Lb ? -1 : 1;
            i++; j++;
        }
        if (i < A.size()) return 1;
        if (j < B.size()) return -1;
        return 0;
    }

    const char* GameName(SupportedGames Game)
    {
        switch (Game)
        {
        case SupportedGames::WorldAtWar: return "World at War";
        case SupportedGames::BlackOps: return "Black Ops";
        case SupportedGames::BlackOps2: return "Black Ops II";
        case SupportedGames::BlackOps3: return "Black Ops III";
        case SupportedGames::BlackOps4: return "Black Ops 4";
        case SupportedGames::BlackOpsCW: return "Black Ops Cold War";
        case SupportedGames::ModernWarfare: return "Modern Warfare";
        case SupportedGames::ModernWarfare2: return "Modern Warfare 2";
        case SupportedGames::ModernWarfare3: return "Modern Warfare 3";
        case SupportedGames::ModernWarfare4: return "Modern Warfare (2019)";
        case SupportedGames::ModernWarfare5: return "Modern Warfare II (2022)";
        case SupportedGames::ModernWarfare6: return "Modern Warfare III (2023)";
        case SupportedGames::QuantumSolace: return "Quantum of Solace";
        case SupportedGames::ModernWarfareRemastered: return "Modern Warfare Remastered";
        case SupportedGames::ModernWarfare2Remastered: return "Modern Warfare 2 Remastered";
        case SupportedGames::Ghosts: return "Ghosts";
        case SupportedGames::InfiniteWarfare: return "Infinite Warfare";
        case SupportedGames::AdvancedWarfare: return "Advanced Warfare";
        case SupportedGames::WorldWar2: return "WWII";
        case SupportedGames::Vanguard: return "Vanguard";
        }
        return "Call of Duty";
    }

    std::string Base64(const std::vector<uint8_t>& Data)
    {
        static const char* Table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        std::string Out;
        Out.reserve((Data.size() + 2) / 3 * 4);
        for (size_t i = 0; i < Data.size(); i += 3)
        {
            const uint32_t N = (Data[i] << 16) | ((i + 1 < Data.size() ? Data[i + 1] : 0) << 8) | (i + 2 < Data.size() ? Data[i + 2] : 0);
            Out += Table[(N >> 18) & 63];
            Out += Table[(N >> 12) & 63];
            Out += i + 1 < Data.size() ? Table[(N >> 6) & 63] : '=';
            Out += i + 2 < Data.size() ? Table[N & 63] : '=';
        }
        return Out;
    }

    bool PngEncoder(CLSID& Id)
    {
        UINT Count = 0, Size = 0;
        if (Gdiplus::GetImageEncodersSize(&Count, &Size) != Gdiplus::Ok || Size == 0) return false;
        std::vector<uint8_t> Buffer(Size);
        auto Codecs = (Gdiplus::ImageCodecInfo*)Buffer.data();
        if (Gdiplus::GetImageEncoders(Count, Size, Codecs) != Gdiplus::Ok) return false;
        for (UINT i = 0; i < Count; i++)
            if (wcscmp(Codecs[i].MimeType, L"image/png") == 0) { Id = Codecs[i].Clsid; return true; }
        return false;
    }

    // The game's own icon as a PNG data URL, alpha intact.
    std::string IconDataUrl(const std::string& Path)
    {
        HICON Icon = FileSystems::ExtractFileIcon(Path);
        if (Icon == NULL) return {};
        std::string Result;
        ICONINFO Info{};
        if (GetIconInfo(Icon, &Info) && Info.hbmColor != NULL)
        {
            BITMAP Bm{};
            GetObject(Info.hbmColor, sizeof(Bm), &Bm);
            const int W = Bm.bmWidth, H = Bm.bmHeight;
            std::vector<uint32_t> Pixels((size_t)W * H), Mask((size_t)W * H);
            BITMAPINFO Bi{};
            Bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
            Bi.bmiHeader.biWidth = W;
            Bi.bmiHeader.biHeight = -H;
            Bi.bmiHeader.biPlanes = 1;
            Bi.bmiHeader.biBitCount = 32;
            Bi.bmiHeader.biCompression = BI_RGB;
            HDC Dc = GetDC(NULL);
            const bool Read = W > 0 && H > 0 && GetDIBits(Dc, Info.hbmColor, 0, H, Pixels.data(), &Bi, DIB_RGB_COLORS) == H;
            if (Read && std::none_of(Pixels.begin(), Pixels.end(), [](uint32_t P) { return (P >> 24) != 0; }) &&
                Info.hbmMask != NULL && GetDIBits(Dc, Info.hbmMask, 0, H, Mask.data(), &Bi, DIB_RGB_COLORS) == H)
            {
                for (size_t i = 0; i < Pixels.size(); i++)
                    if ((Mask[i] & 0xFFFFFF) == 0) Pixels[i] |= 0xFF000000;
            }
            ReleaseDC(NULL, Dc);

            CLSID Png;
            if (Read && PngEncoder(Png))
            {
                Gdiplus::Bitmap Bitmap(W, H, W * 4, PixelFormat32bppARGB, (BYTE*)Pixels.data());
                IStream* Stream = SHCreateMemStream(nullptr, 0);
                if (Stream != nullptr)
                {
                    if (Bitmap.Save(Stream, &Png, nullptr) == Gdiplus::Ok)
                    {
                        STATSTG Stat{};
                        Stream->Stat(&Stat, STATFLAG_NONAME);
                        std::vector<uint8_t> Bytes((size_t)Stat.cbSize.QuadPart);
                        LARGE_INTEGER Zero{};
                        Stream->Seek(Zero, STREAM_SEEK_SET, nullptr);
                        ULONG Got = 0;
                        if (!Bytes.empty() && SUCCEEDED(Stream->Read(Bytes.data(), (ULONG)Bytes.size(), &Got)) && Got == Bytes.size())
                            Result = "data:image/png;base64," + Base64(Bytes);
                    }
                    Stream->Release();
                }
            }
        }
        if (Info.hbmColor) DeleteObject(Info.hbmColor);
        if (Info.hbmMask) DeleteObject(Info.hbmMask);
        DestroyIcon(Icon);
        return Result;
    }

    std::string WithCommas(uint64_t Value)
    {
        auto Text = std::to_string(Value);
        for (int i = (int)Text.size() - 3; i > 0; i -= 3) Text.insert((size_t)i, ",");
        return Text;
    }

    // "C:\x" or "\\server\share", never "C:x" or "\x".
    bool IsFullPath(const std::string& Path)
    {
        if (Path.size() >= 3 && isalpha((unsigned char)Path[0]) && Path[1] == ':' && (Path[2] == '\\' || Path[2] == '/')) return true;
        return Path.size() >= 3 && Path[0] == '\\' && Path[1] == '\\';
    }

    bool IsDirectory(const std::string& Path)
    {
        const auto Attributes = GetFileAttributesA(Path.c_str());
        return Attributes != INVALID_FILE_ATTRIBUTES && (Attributes & FILE_ATTRIBUTE_DIRECTORY);
    }
}

// Forwards a shared export job to the page. Status and progress are
// throttled by UiBridge::OnTimer; questions block the worker until answered.
struct WebSink : JobSink
{
    UiBridge& Bridge;
    explicit WebSink(UiBridge& Target) : Bridge(Target) {}
    void Status(const std::string& Text) override
    {
        std::lock_guard<std::mutex> Lock(Bridge.JobLock);
        Bridge.Job.Status = Text;
        Bridge.Job.Dirty = true;
    }
    void Progress(uint32_t Percent) override
    {
        std::lock_guard<std::mutex> Lock(Bridge.JobLock);
        Bridge.Job.Progress = (int)std::min<uint32_t>(Percent, 100);
        Bridge.Job.Dirty = true;
    }
    int Ask(const std::string& Title, const std::string& Text) override { return Bridge.Ask(Title, Text); }
};

UiBridge::UiBridge(Host Target) : Target(std::move(Target))
{
    Active = this;
    CoDAssets::OnExportProgress = OnExportProgress;
    CoDAssets::OnExportStatus = OnExportStatus;
}

UiBridge::~UiBridge()
{
    *Alive = false;
    PreviewWorker.Cancel();
    AnswerAll(IDCANCEL);
    if (Active == this) Active = nullptr;
}

void UiBridge::OnExportProgress(void*, uint32_t Progress)
{
    if (Active == nullptr) return;
    std::lock_guard<std::mutex> Lock(Active->JobLock);
    Active->Job.Progress = (int)std::min<uint32_t>(Progress, 100);
    Active->Job.Dirty = true;
}

void UiBridge::OnExportStatus(void*, uint32_t Index)
{
    if (Active == nullptr) return;
    std::lock_guard<std::mutex> Lock(Active->JobLock);
    Active->Job.Rows.insert(Index);
    Active->Job.Dirty = true;
}

// ---------------------------------------------------------------- messages

void UiBridge::OnMessage(const std::string& Text, const std::vector<std::string>& Files, bool FromPopup)
{
    const auto Message = json::parse(Text, nullptr, false);
    if (Message.is_discarded() || !Message.is_object()) return;
    const auto Id = Message.contains("id") ? Message["id"] : json();
    const auto Command = Message.value("cmd", std::string());
    const auto Args = Message.contains("args") && Message["args"].is_object() ? Message["args"] : json::object();
    PopupReply = FromPopup;
    try
    {
        if (FromPopup && Command != "app.init" && Command != "app.ready" && Command != "app.theme" &&
            Command != "preview.ready" && Command != "preview.dock")
            throw std::runtime_error("This action belongs to the Library window.");
        const auto Result = Dispatch(Command, Args, Files);
        if (!Id.is_null()) Reply(Id, true, Result);
    }
    catch (const std::exception& E)
    {
        if (!Id.is_null()) Reply(Id, false, E.what());
    }
    PopupReply = false;
}

void UiBridge::Reply(const json& Id, bool Ok, const json& Value)
{
    json Message = { {"type", "reply"}, {"id", Id}, {"ok", Ok} };
    Message[Ok ? "result" : "error"] = Value;
    if (PopupReply && Target.PostPopup) Target.PostPopup(Dump(Message));
    else Target.Post(Dump(Message));
}

void UiBridge::Emit(const std::string& Name, const json& Data)
{
    Target.Post(Dump({ {"type", "event"}, {"name", Name}, {"data", Data} }));
    // Export questions belong to the Library. A preview-only popup cannot
    // answer them and must never cover its canvas with an unanswerable modal.
    if (Target.PostPopup && (Name.compare(0, 8, "preview.") == 0 || Name == "state" || Name == "settings"))
        Target.PostPopup(Dump({ {"type", "event"}, {"name", Name}, {"data", Data} }));
}

void UiBridge::Toast(const std::string& Text, bool Error)
{
    Emit("toast", { {"text", Text}, {"kind", Error ? "err" : ""} });
}

void UiBridge::Notice(const std::string& Title, const std::string& Text)
{
    Emit("notice", { {"title", Title}, {"text", Text} });
}

json UiBridge::Dispatch(const std::string& Command, const json& Args, const std::vector<std::string>& Files)
{
    // ---- app
    if (Command == "app.init")
    {
        if (!PopupReply) { CancelPreview(true); SettingDefaults.clear(); }
        if (!PopupReply && Args.contains("defaults") && Args["defaults"].is_object())
            for (auto& Item : Args["defaults"].items())
                if (Item.value().is_string()) SettingDefaults[Item.key()] = Item.value().get<std::string>();
        return { {"version", "v2.0"}, {"settings", Settings()}, {"state", State()}, {"poppedOut", PoppedOut} };
    }
    if (Command == "app.ready") { if (!PopupReply && Target.Ready) Target.Ready(); return true; }
    if (Command == "app.theme") { if (Target.Theme) Target.Theme(Args.value("dark", true)); return true; }
    if (Command == "app.exportRoot") return { {"path", CoDAssets::ExportRoot()} };
    if (Command == "app.about")
    {
        const auto Text = "Greyhound v2.0\n\nA Call of Duty asset exporter. Based on Greyhound by Scobalula and "
            "Wraith by DTZxPorter.\n\nSettings: " + FileSystems::CombinePath(FileSystems::GetApplicationPath(), "greyhound.json") +
            "\nLog: " + FileSystems::CombinePath(FileSystems::GetApplicationPath(), "TheHoundsLog.txt") +
            "\n\nThe previous interface is still available: start Greyhound with --classic.";
        return { {"text", Text} };
    }
    if (Command == "settings.set")
    {
        if (!Args.contains("values") || !Args["values"].is_object()) return false;
        for (auto& Item : Args["values"].items())
        {
            if (!Item.value().is_string() || SettingDefaults.find(Item.key()) == SettingDefaults.end()) continue;
            const auto Value = Item.value().get<std::string>();
            // A drive-relative path such as "D:exports" would scatter output
            // into whatever folder that drive last used.
            if (Item.key() == "exportroot" && !Value.empty() && !IsFullPath(Value))
                throw std::runtime_error("The export folder must be a full path, like D:\\exports.");
            SettingsManager::SetSetting(Item.key(), Value);
        }
        return true;
    }

    // ---- preview (on demand; row selection and export remain independent)
    if (Command == "preview.request") return RequestPreview(Args);
    if (Command == "preview.cancel") { CancelPreview(false); return true; }
    if (Command == "preview.ready")
    {
        Emit("preview.dockState", PreviewDockState());
        if (PopupReply == PoppedOut) { PreviewTargetReady = true; SendPreview(); }
        return true;
    }
    if (Command == "preview.popout")
    {
        if (!PoppedOut)
        {
            PoppedOut = true;
            PreviewTargetReady = false;
            SendingPreview.reset();
            if (!Target.PopOut || !Target.PopOut()) { PoppedOut = false; PreviewTargetReady = true; SendPreview(); return false; }
        }
        Emit("preview.dockState", PreviewDockState());
        return true;
    }
    if (Command == "preview.dock")
    {
        // The window close callback performs the state change and replay.
        // Defer closing until after replying to the originating page.
        if (PoppedOut && Target.Dock) Target.Dock();
        return true;
    }

    // ---- game
    if (Command == "game.load") { StartLoad(""); return true; }
    if (Command == "game.loadFile")
    {
        if (Busy || Loading) return false;
        const auto File = PickFile("Select a game file to load",
            "All files (*.*)|*.*;|Image Package Files (*.iwd, *.ipak, *.xpak)|*.iwd;*.ipak;*.xpak|Sound Package Files (*.sabs, *.sabl)|*.sabs;*.sabl;");
        if (!File.empty()) StartLoad(File);
        return !File.empty();
    }
    if (Command == "game.dropFile")
    {
        if (Files.empty()) return false;
        if (Busy || Loading) { Toast("Wait for the current job to finish.", true); return false; }
        StartLoad(Files[0]);
        return true;
    }
    if (Command == "game.clear")
    {
        if (Busy || Loading) return false;
        CancelPreview(true);
        Loading = true;
        LoadingText = "Unloading...";
        View.clear();
        ViewGeneration++;
        EmitState();
        std::thread([this]
        {
            std::lock_guard<std::mutex> Access(DataAccess);
            CoDAssets::CleanUpGame();
            Target.Invoke([this]
            {
                Loading = false;
                LastLoadedFile.clear();
                GameIcon.clear();
                EmitState(true);
                if (CloseRequested) Target.Close();
            });
        }).detach();
        return true;
    }

    // ---- assets
    if (Command == "assets.query") { Query(Args); return { {"count", View.size()}, {"generation", ViewGeneration} }; }
    if (Command == "assets.rows")
    {
        const auto Start = Args.value("start", (size_t)0);
        const auto Count = std::min<size_t>(Args.value("count", (size_t)0), 1000);
        return Rows(Start, Count);
    }
    if (Command == "assets.copyNames")
    {
        const auto Assets = Selection(Args);
        const auto Separator = Args.value("sep", std::string("\n"));
        std::string Text;
        for (auto Asset : Assets) { Text += Asset->AssetName; Text += Separator; }
        const auto Wide = Strings::ToUnicodeString(Text);
        if (!Assets.empty() && OpenClipboard(Target.Window))
        {
            EmptyClipboard();
            auto Handle = GlobalAlloc(GMEM_MOVEABLE, (Wide.size() + 1) * sizeof(wchar_t));
            if (Handle != NULL)
            {
                auto Buffer = (wchar_t*)GlobalLock(Handle);
                memcpy(Buffer, Wide.c_str(), (Wide.size() + 1) * sizeof(wchar_t));
                GlobalUnlock(Handle);
                if (SetClipboardData(CF_UNICODETEXT, Handle) == NULL) GlobalFree(Handle);
            }
            CloseClipboard();
        }
        return Assets.size();
    }
    if (Command == "export.selection")
    {
        if (!CanStart()) return false;
        const auto Assets = Selection(Args);
        if (Assets.empty()) return false;
        if (Assets.size() == 1 && Assets[0]->AssetType == WraithAssetType::Material &&
            static_cast<const CoDMaterial_t*>(Assets[0])->IsVolumeDecal)
        {
            const auto Problem = CoDAssets::DecalExportProblem(static_cast<const CoDMaterial_t*>(Assets[0]));
            if (!Problem.empty()) { Notice("Decal export", Problem); return false; }
        }
        if (std::all_of(Assets.begin(), Assets.end(), [](const CoDAsset_t* Asset) {
            return Asset->AssetType == WraithAssetType::Terrain;
        }))
        {
            const auto Problem = CoDAssets::TerrainExportProblem(false);
            if (!Problem.empty()) { Notice("Terrain export", Problem); return false; }
        }
        const auto Title = Assets.size() == 1 ? std::string("Exporting ") + Assets[0]->AssetName : "Exporting " + WithCommas(Assets.size()) + " assets";
        StartJob(Title, "Preparing...", true, [Assets](JobSink&)
        {
            CoDAssets::ExportAssetList(Assets);
            JobResult Result;
            size_t Failed = 0;
            for (auto Asset : Assets) if (Asset->AssetStatus == WraithAssetStatus::Error) Failed++;
            const uint64_t Done = CoDAssets::ExportedAssetsCount;
            Result.Cancelled = !CoDAssets::CanExportContinue;
            Result.Ok = !Result.Cancelled && Failed < Assets.size();
            Result.Status = Result.Cancelled
                ? "Stopped after " + WithCommas(Done) + " of " + WithCommas(Assets.size()) + "."
                : Assets.size() == 1 ? (Failed ? "The asset failed to export." : "Exported.")
                : "Exported " + WithCommas(Assets.size() - Failed) + " assets" + (Failed ? ", " + WithCommas(Failed) + " failed." : ".");
            const auto GamePath = FileSystems::CombinePath(CoDAssets::ExportRoot(), CoDAssets::GameFolderName());
            Result.Path = IsDirectory(GamePath) ? GamePath : CoDAssets::ExportRoot();
            if (Assets.size() == 1 && Assets[0]->AssetType == WraithAssetType::Material &&
                static_cast<const CoDMaterial_t*>(Assets[0])->IsVolumeDecal && !Result.Cancelled)
            {
                Result.Status = Failed ? "Decal conversion incomplete. Open the output folder for its log and report."
                    : "Exported BO3 package. Copy bo3_root contents into BO3, then convert the assets in APE.";
                if (IsDirectory(CoDAssets::LatestExportPath)) Result.Path = CoDAssets::LatestExportPath;
            }
            return Result;
        }, true);
        return true;
    }
    if (Command == "job.cancel") { CoDAssets::CanExportContinue = false; return true; }
    if (Command == "ask.answer")
    {
        const auto Answer = Args.value("answer", std::string("cancel"));
        const int Code = Answer == "yes" ? IDYES : Answer == "no" ? IDNO : IDCANCEL;
        std::lock_guard<std::mutex> Lock(AskLock);
        auto Found = Asks.find(Args.value("id", 0u));
        if (Found != Asks.end()) { Found->second.set_value(Code); Asks.erase(Found); }
        return true;
    }

    // ---- dialogs and shell
    if (Command == "dialog.folder") return PickFolder(Args.value("title", std::string("Choose a folder")), Args.value("initial", std::string()));
    if (Command == "shell.openExportRoot")
    {
        const auto Root = CoDAssets::ExportRoot();
        FileSystems::CreateDirectory(Root);
        ShellExecuteA(Target.Window, "open", Root.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        return true;
    }
    if (Command == "shell.openPath")
    {
        const auto Path = Args.value("path", std::string());
        if (IsDirectory(Path)) ShellExecuteA(Target.Window, "open", Path.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        else if (FileSystems::FileExists(Path))
        {
            const auto Select = "/select,\"" + Path + "\"";
            ShellExecuteA(Target.Window, "open", "explorer.exe", Select.c_str(), nullptr, SW_SHOWNORMAL);
        }
        else Toast("That folder no longer exists.", true);
        return true;
    }
    if (Command == "shell.url")
    {
        const auto Which = Args.value("which", std::string());
        const char* Url = Which == "wiki" ? "https://github.com/Scobalula/Greyhound/wiki" : Which == "saluki" ? SalukiNameDatabase::ProjectUrl : nullptr;
        if (Url != nullptr) ShellExecuteA(Target.Window, "open", Url, nullptr, nullptr, SW_SHOWNORMAL);
        return Url != nullptr;
    }

    // ---- tools
    if (Command == "tools.run") { RunTool(Args.value("tool", std::string())); return true; }
    if (Command == "tools.bo4Modes")
    {
        char Override[16]{};
        const bool Overridden = GetEnvironmentVariableA("GREYHOUND_BO4_WORLD_PROBE", Override, sizeof(Override)) > 0;
        int Selected = atoi(Overridden ? Override : SettingsManager::GetSetting("bo4capturemode", "0").c_str());
        if (Selected < 0 || Selected >= BO4Diagnostics::BO4CaptureModeCount) Selected = 0;
        json Modes = json::array();
        for (auto& Mode : BO4Diagnostics::BO4CaptureModes)
            Modes.push_back({ {"label", Strings::ToNormalString(Mode.Label)}, {"hint", Strings::ToNormalString(Mode.Hint)} });
        return { {"selected", Selected}, {"overridden", Overridden}, {"modes", Modes} };
    }

    // ---- asset names
    if (Command == "names.download") { UpdateNames(""); return true; }
    if (Command == "names.folder")
    {
        const auto Folder = PickFolder("Choose cod-name-db (CSV) or Saluki names (CDB) folder", SettingsManager::GetSetting("salukinamefolder", ""));
        if (!Folder.empty()) UpdateNames(Folder);
        return !Folder.empty();
    }
    if (Command == "names.disable")
    {
        SettingsManager::SetSetting("salukinamefolder", "");
        SettingsManager::SetSetting("salukiautoupdate", "false");
        NamesChanged();
        return true;
    }

    throw std::runtime_error("Unknown command: " + Command);
}

// ---------------------------------------------------------------- preview

void UiBridge::PreviewEvent(const std::string& Name, const json& Data)
{
    const auto Message = Dump({{"type", "event"}, {"name", Name}, {"data", Data}});
    if (Target.PostPreview) Target.PostPreview(Message);
    else Target.Post(Message);
}

void UiBridge::CancelPreview(bool Clear)
{
    ++PreviewSequence;
    PreviewWorker.Cancel();
    SendingPreview.reset();
    if (!Clear && ActivePreviewStatus.is_object())
    {
        ActivePreviewStatus["status"] = "cancelled";
        Emit("preview.status", ActivePreviewStatus);
    }
    ActivePreviewStatus = nullptr;
    if (Clear)
    {
        CurrentPreview.reset();
        Emit("preview.status", {{"status", "cleared"}});
    }
}

json UiBridge::RequestPreview(const json& Args)
{
    const uint32_t Generation = Args.value("generation", UINT32_MAX);
    const uint64_t Request = Args.value("requestId", uint64_t(0));
    const size_t Index = Args.value("index", SIZE_MAX);
    if (Busy || Loading || CloseRequested)
        return {{"status", "unavailable"}, {"message", "Wait for the current job to finish."}, {"requestId", Request}};
    if (Generation != ViewGeneration || Index >= View.size())
        return {{"status", "stale"}, {"requestId", Request}};
    auto Asset = View[Index];
    if (Asset->AssetType != WraithAssetType::Model && Asset->AssetType != WraithAssetType::Image &&
        Asset->AssetType != WraithAssetType::Terrain)
        return {{"status", "unsupported"}, {"message", "Preview supports models, images, and terrain."}, {"requestId", Request}};

    CancelPreview(false);
    const uint64_t Sequence = PreviewSequence;
    const std::string Name = Asset->AssetName;
    const auto Life = Alive;
    ActivePreviewStatus = {{"status", "loading"}, {"requestId", Request}, {"generation", Generation}, {"name", Name}};
    Emit("preview.status", ActivePreviewStatus);
    PreviewWorker.Submit([this, Asset, Life, Sequence, Request, Generation, Name](const LatestPreviewWorker::Cancelled& Cancelled)
    {
        auto Packet = std::make_shared<PreviewPacket>();
        std::string Error;
        {
            std::lock_guard<std::mutex> Access(DataAccess);
            // The loader/unloader may have won this lock while we waited.
            if (Cancelled()) return;
            const HRESULT Com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
            try
            {
                auto Result = PreviewData::Build(Asset, PreviewData::Options{}, Cancelled);
                Packet->Metadata = std::move(Result.metadata);
                Packet->Bytes = std::move(Result.bytes);
                Error = Result.error;
                if (Result.cancelled || Cancelled()) { if (SUCCEEDED(Com)) CoUninitialize(); return; }
            }
            catch (const std::exception& E) { Error = E.what(); }
            catch (...) { Error = "The game reader could not preview this asset."; }
            if (SUCCEEDED(Com)) CoUninitialize();
        }
        if (Cancelled()) return;
        Target.Invoke([this, Life, Sequence, Request, Generation, Name, Packet, Error]
        {
            if (!Life->load() || Sequence != PreviewSequence || Generation != ViewGeneration || CloseRequested) return;
            ActivePreviewStatus = nullptr;
            if (!Error.empty() || Packet->Bytes.empty())
            {
                Emit("preview.status", {{"status", "error"}, {"requestId", Request}, {"generation", Generation},
                    {"name", Name}, {"message", Error.empty() ? "No usable preview data was found." : Error}});
                return;
            }
            Packet->Metadata["requestId"] = Request;
            Packet->Metadata["generation"] = Generation;
            Packet->Metadata["byteLength"] = Packet->Bytes.size();
            CurrentPreview = Packet;
            SendPreview();
        });
    });
    return {{"status", "loading"}, {"requestId", Request}, {"generation", Generation}};
}

void UiBridge::SendPreview()
{
    SendingPreview.reset();
    if (!CurrentPreview || !PreviewTargetReady) return;
    auto Metadata = CurrentPreview->Metadata;
    Metadata["transferId"] = ++TransferSequence;
    const auto Additional = Dump({{"type", "preview"}, {"manifest", Metadata}});
    if (Target.SharePreview && Target.SharePreview(CurrentPreview->Bytes, Additional)) return;
    PreviewEvent("preview.begin", Metadata);
    SendingPreview = CurrentPreview;
    PreviewOffset = 0;
}

void UiBridge::PumpPreview()
{
    if (!SendingPreview) return;
    const auto Packet = SendingPreview;
    const auto Request = Packet->Metadata["requestId"];
    const auto Generation = Packet->Metadata["generation"];
    // Small messages and a bounded burst keep WebView and native input responsive.
    for (size_t Batch = 0; Batch < 8 && PreviewOffset < Packet->Bytes.size(); ++Batch)
    {
        const size_t Count = std::min<size_t>(48 * 1024, Packet->Bytes.size() - PreviewOffset);
        std::vector<uint8_t> Chunk(Packet->Bytes.begin() + PreviewOffset, Packet->Bytes.begin() + PreviewOffset + Count);
        PreviewEvent("preview.chunk", {{"requestId", Request}, {"generation", Generation}, {"transferId", TransferSequence},
            {"offset", PreviewOffset}, {"data", Base64(Chunk)}});
        PreviewOffset += Count;
    }
    if (PreviewOffset == Packet->Bytes.size())
    {
        PreviewEvent("preview.end", {{"requestId", Request}, {"generation", Generation}, {"transferId", TransferSequence}});
        SendingPreview.reset();
    }
}

void UiBridge::PreviewDocked()
{
    PoppedOut = false;
    PreviewTargetReady = true;
    Emit("preview.dockState", PreviewDockState());
    SendPreview();
}

json UiBridge::PreviewDockState()
{
    json Retained = nullptr;
    if (CurrentPreview) Retained = {{"requestId", CurrentPreview->Metadata["requestId"]}, {"generation", CurrentPreview->Metadata["generation"]}};
    return {{"poppedOut", PoppedOut}, {"retained", Retained}};
}

// ---------------------------------------------------------------- state

json UiBridge::Settings()
{
    json Values = json::object();
    for (auto& Item : SettingDefaults)
        Values[Item.first] = SettingsManager::GetSetting(Item.first, Item.second);
    return Values;
}

json UiBridge::State(bool Reset)
{
    const bool Loaded = !Loading && CoDAssets::GameAssets != nullptr;
    json Counts = json::object();
    size_t Total = 0;
    json Game = nullptr;
    if (Loaded)
    {
        std::map<std::string, size_t> Tally;
        for (auto Asset : CoDAssets::GameAssets->LoadedAssets) Tally[TypeKey(Asset)]++;
        for (auto& Item : Tally) Counts[Item.first] = Item.second;
        Total = CoDAssets::GameAssets->LoadedAssets.size();

        std::string Path = LastLoadedFile;
        if (Path.empty() && CoDAssets::GameInstance != nullptr && CoDAssets::GameInstance->IsRunning())
            Path = CoDAssets::GameInstance->GetProcessPath();
        const bool File = !LastLoadedFile.empty();
        Game = {
            {"id", CoDAssets::GameFolderName()},
            {"name", File ? FileSystems::GetFileName(LastLoadedFile) : std::string(GameName(CoDAssets::GameID))},
            {"path", Path}, {"icon", GameIcon}, {"file", File},
            {"terrain", {{"modelPackages", !File && CoDAssets::TerrainExportProblem(false).empty()},
                         {"sourceCapture", !File && CoDAssets::TerrainExportProblem(true).empty()}}},
        };
    }
    json Result = {
        {"loaded", Loaded}, {"loading", Loading}, {"busy", Busy}, {"total", Total},
        {"typeCounts", Counts}, {"exportRoot", CoDAssets::ExportRoot()}, {"game", Game},
        {"generation", ViewGeneration},
    };
    if (Loading) Result["loadingText"] = LoadingText;
    if (Reset) Result["reset"] = true;
    return Result;
}

void UiBridge::StartLoad(const std::string& File)
{
    if (Busy || Loading) return;
    CancelPreview(true);
    Loading = true;
    LoadingText = File.empty() ? "Looking for a running game..." : "Reading " + FileSystems::GetFileName(File) + "...";
    View.clear();
    ViewGeneration++;
    GameIcon.clear();
    EmitState();

    std::thread([this, File]
    {
        std::lock_guard<std::mutex> Access(DataAccess);
        std::string Error;
        bool Ok = false;
        try
        {
            CoDAssets::CleanUpGame();
            SalukiNameDatabase::AutoUpdate();
            if (File.empty())
            {
                const auto Result = CoDAssets::BeginGameMode();
                Ok = Result == FindGameResult::Success;
                if (Result == FindGameResult::NoGamesRunning)
                    Error = "No supported game is running. Start the game, wait until it reaches the menu or a map, then load again.";
                else if (Result == FindGameResult::FailedToLocateInfo)
                    Error = "This game is supported, but its current update is not yet. Wait for a Greyhound update.";
            }
            else
            {
                const auto Result = CoDAssets::BeginGameFileMode(File);
                Ok = Result == LoadGameFileResult::Success;
                if (Result == LoadGameFileResult::InvalidFile) Error = "Greyhound can't read that file. It isn't a supported package.";
                else if (!Ok) Error = "Something went wrong while reading the file.";
            }
        }
        catch (const std::exception& E) { Error = E.what(); Ok = Ok && CoDAssets::GameAssets != nullptr; }
        if (Ok && CoDAssets::GameAssets == nullptr) { Ok = false; if (Error.empty()) Error = "No assets were found."; }

        std::string Icon;
        if (Ok && File.empty() && CoDAssets::GameInstance != nullptr)
            Icon = IconDataUrl(CoDAssets::GameInstance->GetProcessPath());

        Target.Invoke([this, Ok, Error, File, Icon]
        {
            Loading = false;
            LastLoadedFile = Ok ? File : "";
            GameIcon = Icon;
            if (Ok) View = CoDAssets::GameAssets->LoadedAssets;
            ViewGeneration++;
            EmitState(true);
            if (!Error.empty()) Notice(File.empty() ? "Load game" : "Open file", Error);
            if (CloseRequested) Target.Close();
        });
    }).detach();
}

void UiBridge::Query(const json& Args)
{
    CancelPreview(true);
    View.clear();
    ViewGeneration++;
    if (Loading || CoDAssets::GameAssets == nullptr) return;

    const auto Text = Args.value("text", std::string());
    const auto Type = Args.value("type", std::string("all"));
    const auto Sort = Args.value("sort", std::string());
    const bool Descending = Args.value("desc", false);

    auto& All = CoDAssets::GameAssets->LoadedAssets;
    std::vector<CoDAsset_t*> Found = Strings::IsNullOrWhiteSpace(Text) ? All : AssetSearch::Filter(Text, All);
    if (Type != "all")
        Found.erase(std::remove_if(Found.begin(), Found.end(), [&](CoDAsset_t* A) { return Type != TypeKey(A); }), Found.end());

    if (!Sort.empty())
    {
        // Sort by a precomputed key so Details isn't formatted per comparison.
        std::vector<std::pair<std::string, CoDAsset_t*>> Keyed;
        Keyed.reserve(Found.size());
        for (auto Asset : Found)
        {
            std::string Key = Sort == "type" ? TypeKey(Asset)
                : Sort == "status" ? StatusKey(Asset->AssetStatus)
                : Sort == "details" ? Details(Asset) : Asset->AssetName;
            Keyed.emplace_back(std::move(Key), Asset);
        }
        std::stable_sort(Keyed.begin(), Keyed.end(), [Descending](const std::pair<std::string, CoDAsset_t*>& A, const std::pair<std::string, CoDAsset_t*>& B)
        {
            const int C = NaturalCompare(A.first, B.first);
            return Descending ? C > 0 : C < 0;
        });
        for (size_t i = 0; i < Keyed.size(); i++) Found[i] = Keyed[i].second;
    }
    View = std::move(Found);
}

json UiBridge::Rows(size_t Start, size_t Count)
{
    json Out = json::array();
    if (Loading) return Out;
    for (size_t i = Start; i < View.size() && i < Start + Count; i++)
    {
        auto Asset = View[i];
        Out.push_back({ {"name", Asset->AssetName}, {"type", TypeKey(Asset)},
            {"status", StatusKey(Asset->AssetStatus)}, {"details", Details(Asset)} });
    }
    return Out;
}

std::vector<CoDAsset_t*> UiBridge::Selection(const json& Args)
{
    // AssetLoadedIndex is what OnExportStatus reports, so it becomes the row.
    std::vector<CoDAsset_t*> Assets;
    if (Loading) return Assets;
    if (Args.value("all", false))
    {
        Assets = View;
        for (size_t i = 0; i < Assets.size(); i++) Assets[i]->AssetLoadedIndex = (uint32_t)i;
    }
    else if (Args.contains("indices") && Args["indices"].is_array())
    {
        for (auto& Index : Args["indices"])
        {
            if (!Index.is_number_unsigned() || Index.get<size_t>() >= View.size()) continue;
            const auto i = Index.get<size_t>();
            View[i]->AssetLoadedIndex = (uint32_t)i;
            Assets.push_back(View[i]);
        }
    }
    return Assets;
}

// ---------------------------------------------------------------- jobs

bool UiBridge::CanStart()
{
    if (!Busy && !Loading) return true;
    Toast("Wait for the current job to finish.", true);
    return false;
}

void UiBridge::StartJob(const std::string& Title, const std::string& Initial, bool Cancellable,
    std::function<JobResult(JobSink&)> Work, bool AssetExport, std::function<void(const JobResult&)> Done)
{
    CancelPreview(false);
    Busy = true;
    CoDAssets::CanExportContinue = true;
    {
        std::lock_guard<std::mutex> Lock(JobLock);
        Job = JobState();
        Job.Title = Title;
        Job.Status = Initial;
        Job.Cancellable = Cancellable;
        Job.AssetExport = AssetExport;
        Job.Generation = ViewGeneration;
    }
    Emit("job", { {"title", Title}, {"status", Initial}, {"progress", -1}, {"state", "running"}, {"cancellable", Cancellable} });
    EmitState();

    std::thread([this, Title, Work, Done]
    {
        std::lock_guard<std::mutex> Access(DataAccess);
        WebSink Sink(*this);
        JobResult Result;
        try { Result = Work(Sink); }
        catch (const std::exception& E) { Result.Ok = false; Result.Status = std::string("Failed: ") + E.what(); }
        Target.Invoke([this, Title, Result, Done]
        {
            OnTimer();
            Busy = false;
            const char* State = Result.Cancelled ? "cancelled" : Result.Ok ? "done" : "failed";
            Emit("job", { {"title", Title}, {"status", Result.Status}, {"progress", 100}, {"state", State}, {"path", Result.Path} });
            EmitState();
            if (Done) Done(Result);
            if (CloseRequested) Target.Close();
        });
    }).detach();
}

void UiBridge::OnTimer()
{
    PumpPreview();
    if (CloseRequested && !Busy && !Loading && !PreviewWorker.Busy()) { Target.Close(); return; }
    if (!Busy) return;
    JobState Copy;
    {
        std::lock_guard<std::mutex> Lock(JobLock);
        if (!Job.Dirty) return;
        Copy = Job;
        Job.Rows.clear();
        Job.Dirty = false;
    }
    if (Copy.AssetExport)
    {
        const uint64_t Done = CoDAssets::ExportedAssetsCount, Total = CoDAssets::AssetsToExportCount;
        Copy.Status = CoDAssets::CanExportContinue
            ? "Exported " + WithCommas(Done) + " of " + WithCommas(Total)
            : "Stopping after the current asset...";
    }
    Emit("job", { {"title", Copy.Title}, {"status", Copy.Status}, {"progress", Copy.Progress}, {"state", "running"}, {"cancellable", Copy.Cancellable} });

    if (Copy.Rows.empty()) return;
    // Row numbers are only meaningful for the view the export started from.
    if (Copy.Generation != ViewGeneration || Copy.Rows.size() > 64) { Emit("rows-dirty", json::object()); return; }
    for (auto i : Copy.Rows)
        if (i < View.size()) Emit("row", { {"i", i}, {"status", StatusKey(View[i]->AssetStatus)} });
}

void UiBridge::RunTool(const std::string& Tool)
{
    if (!CanStart()) return;
    if (Tool == "placements")
        StartJob("Placements", "Reading placements...", false, ExportJobs::ModelPlacements);
    else if (Tool == "brushes")
    {
        const auto Problem = ExportJobs::CheckRadiantBrushes();
        if (!Problem.empty()) { Notice("Radiant brushes", Problem); return; }
        StartJob("Radiant brushes", "Capturing verified brush data...", false, ExportJobs::RadiantBrushes);
    }
    else if (Tool == "modelsFromJson")
    {
        const auto Problem = ExportJobs::CheckModelsFromJson();
        if (!Problem.empty()) { Notice("Models from JSON", Problem); return; }
        const auto File = PickFile("Select static or non-static model placement JSON", "JSON (*.json)|*.json;");
        if (File.empty()) return;
        StartJob("Models from JSON", "Preparing unique models...", true, [File](JobSink& Sink) { return ExportJobs::ModelsFromJson(File, Sink); });
    }
    else if (Tool == "splineModels")
    {
        const auto Problem = ExportJobs::CheckSplineModels();
        if (!Problem.empty()) { Notice("Spline models", Problem); return; }
        const auto Placements = PickFile("Select the matching spline/static model placements JSON", "JSON (*.json)|*.json;");
        if (Placements.empty()) return;
        const auto Controls = PickFile("Select splined_models.json captured from this map/session", "JSON (*.json)|*.json;");
        if (Controls.empty()) return;
        StartJob("Spline models", "Baking spline models in your selected export formats...", false,
            [Placements, Controls](JobSink& Sink) { return ExportJobs::SplineModels(Placements, Controls, Sink); });
    }
    else if (Tool == "terrainSource")
    {
        const auto Problem = ExportJobs::CheckTerrainSource();
        if (!Problem.empty()) { Notice("Terrain source capture", Problem); return; }
        StartJob("Terrain source capture", "Capturing raw terrain source data...", false, ExportJobs::TerrainSource);
    }
    else if (Tool == "bo4Diagnostic")
    {
        int Mode = 0;
        const auto Problem = ExportJobs::CheckBo4Diagnostic(Mode);
        if (!Problem.empty()) { Notice("BO4 capture", Problem); return; }
        if (Mode == 5) { RunTool("brushes"); return; }
        StartJob("BO4 capture", "Capturing selected diagnostic...", false, [Mode](JobSink& Sink) { return ExportJobs::Bo4Diagnostic(Mode, Sink); });
    }
    else if (Tool == "verifyRuntime")
        StartJob("Export runtime check", "Checking installed tools and dependencies...", false, [](JobSink& Sink) { return ExportJobs::VerifyRuntime("", Sink); });
    else if (Tool == "verifyExport")
    {
        const auto File = PickFile("Select a brush export_report.json or terrain research_capture.report.json", "JSON (*.json)|*.json;");
        if (File.empty()) return;
        StartJob("Saved export check", "Checking published file integrity...", false, [File](JobSink& Sink) { return ExportJobs::VerifyRuntime(File, Sink); });
    }
    else Toast("Unknown tool: " + Tool, true);
}

void UiBridge::UpdateNames(const std::string& Folder)
{
    if (!CanStart()) return;
    const bool Download = Folder.empty();
    StartJob("Asset names", Download ? "Downloading the name database..." : "Reading name database...", false, [Folder, Download](JobSink& Sink)
    {
        JobResult Result;
        try
        {
            Result.Path = Download ? SalukiNameDatabase::Update(true, [&Sink](const std::string& Text) { Sink.Status(Text); }) : Folder;
            if (!Download) SalukiNameDatabase::Validate(Result.Path);
            Result.Ok = true;
            Result.Status = Download ? "Names downloaded and turned on." : "Names folder checked and turned on.";
        }
        catch (const std::exception& E)
        {
            Result.Path.clear();
            Result.Status = std::string(E.what()) + "\n\nYour previous name database is still selected.";
        }
        return Result;
    }, false, [this, Download](const JobResult& Result)
    {
        if (!Result.Ok) { Emit("settings", Settings()); return; }
        SettingsManager::SetSetting("salukinamefolder", Result.Path);
        SettingsManager::SetSetting("salukiautoupdate", Download ? "true" : "false");
        SettingsManager::SetSetting("salukirevision", std::to_string(GetTickCount64()));
        NamesChanged();
    });
}

void UiBridge::NamesChanged()
{
    Emit("settings", Settings());
    // Names are applied while loading, so a loaded list needs a reload.
    if (CoDAssets::GameAssets != nullptr && !Loading && !Busy)
    {
        Toast("Reloading with the new names...");
        StartLoad(LastLoadedFile);
    }
}

int UiBridge::Ask(const std::string& Title, const std::string& Text)
{
    std::future<int> Answer;
    uint32_t Id = 0;
    {
        std::lock_guard<std::mutex> Lock(AskLock);
        if (CloseRequested) return IDCANCEL;
        Id = ++NextAsk;
        Answer = Asks[Id].get_future();
    }
    const bool Resume = Title.find("Resume") != std::string::npos;
    const json Buttons = json::array({
        { {"id", "cancel"}, {"label", "Cancel"} },
        { {"id", "no"}, {"label", Resume ? "New export" : "No"} },
        { {"id", "yes"}, {"label", Resume ? "Resume" : "Yes"}, {"primary", true} },
    });
    Target.Invoke([this, Id, Title, Text, Buttons] { Emit("ask", { {"id", Id}, {"title", Title}, {"text", Text}, {"buttons", Buttons} }); });
    return Answer.get();
}

void UiBridge::AnswerAll(int Answer)
{
    std::lock_guard<std::mutex> Lock(AskLock);
    for (auto& Item : Asks) Item.second.set_value(Answer);
    Asks.clear();
}

bool UiBridge::RequestClose()
{
    CancelPreview(true);
    if (!Busy && !Loading && !PreviewWorker.Busy()) return true;
    CloseRequested = true;
    CoDAssets::CanExportContinue = false;
    AnswerAll(IDCANCEL);
    Toast("Greyhound will close when the current job stops.");
    return false;
}

// ---------------------------------------------------------------- native dialogs

std::string UiBridge::PickFile(const std::string& Title, const std::string& Filter)
{
    return WraithFileDialogs::OpenFileDialog(Title, "", Filter, Target.Window);
}

std::string UiBridge::PickFolder(const std::string& Title, const std::string& Initial)
{
    std::string Result;
    IFileOpenDialog* Dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&Dialog)))) return Result;
    DWORD Options = 0;
    Dialog->GetOptions(&Options);
    Dialog->SetOptions(Options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
    Dialog->SetTitle(Strings::ToUnicodeString(Title).c_str());
    if (!Initial.empty())
    {
        IShellItem* Folder = nullptr;
        if (SUCCEEDED(SHCreateItemFromParsingName(Strings::ToUnicodeString(Initial).c_str(), nullptr, IID_PPV_ARGS(&Folder))))
        {
            Dialog->SetFolder(Folder);
            Folder->Release();
        }
    }
    if (SUCCEEDED(Dialog->Show(Target.Window)))
    {
        IShellItem* Item = nullptr;
        if (SUCCEEDED(Dialog->GetResult(&Item)))
        {
            PWSTR Path = nullptr;
            if (SUCCEEDED(Item->GetDisplayName(SIGDN_FILESYSPATH, &Path)))
            {
                Result = Strings::ToNormalString(Path);
                CoTaskMemFree(Path);
            }
            Item->Release();
        }
    }
    Dialog->Release();
    return Result;
}
