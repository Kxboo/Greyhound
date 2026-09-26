#pragma once

#include <Windows.h>
#include <atomic>
#include <cstdint>
#include <functional>
#include <future>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <vector>
#include "json.hpp"
#include "exporters/ExportJobs.h"
#include "ui/native/PreviewService.h"

class CoDAsset_t;

// The command side of the v2 UI. Lives on the window's thread: every page
// message and every public call happens there. Worker threads reach it only
// through Invoke, the job sink and the static export callbacks.
class UiBridge
{
public:
    // Post sends one JSON message to the page; Invoke runs a function on the
    // window thread later; Theme recolours the native title bar.
    struct Host
    {
        HWND Window = NULL;
        std::function<void(const std::string&)> Post;
        std::function<void(std::function<void()>)> Invoke;
        std::function<void(bool)> Theme;
        std::function<void()> Ready;
        std::function<void()> Close;
        std::function<void(const std::string&)> PostPopup;
        std::function<void(const std::string&)> PostPreview;
        std::function<bool(const std::vector<uint8_t>&, const std::string&)> SharePreview;
        std::function<bool()> PopOut;
        std::function<void()> Dock;
    };

    explicit UiBridge(Host Target);
    ~UiBridge();

    // One {id, cmd, args} message, with the paths of any dropped files.
    void OnMessage(const std::string& Json, const std::vector<std::string>& Files, bool FromPopup = false);
    void PreviewDocked();
    // Flushes throttled job progress and row status changes.
    void OnTimer();
    // The window was asked to close. Returns true when it may close now;
    // otherwise work is cancelled and Host::Close runs once it has stopped.
    bool RequestClose();

private:
    Host Target;

    // Loaded asset view, in page row order.
    std::vector<CoDAsset_t*> View;
    uint32_t ViewGeneration = 0;
    std::string LastLoadedFile;
    std::string GameIcon;
    bool Loading = false;
    std::string LoadingText;
    bool Busy = false;
    std::atomic<bool> CloseRequested{ false };
    std::map<std::string, std::string> SettingDefaults;

    // Shared by preview, load/unload and export workers. An obsolete preview
    // checks its token while holding this lock before using its asset pointer.
    std::mutex DataAccess;
    LatestPreviewWorker PreviewWorker;
    std::shared_ptr<std::atomic<bool>> Alive = std::make_shared<std::atomic<bool>>(true);
    bool PopupReply = false, PoppedOut = false, PreviewTargetReady = true;
    uint64_t PreviewSequence = 0;
    struct PreviewPacket
    {
        nlohmann::json Metadata;
        std::vector<uint8_t> Bytes;
    };
    std::shared_ptr<PreviewPacket> CurrentPreview;
    std::shared_ptr<PreviewPacket> SendingPreview;
    size_t PreviewOffset = 0;
    uint64_t TransferSequence = 0;
    nlohmann::json ActivePreviewStatus;
    nlohmann::json PreviewDockState();
    nlohmann::json RequestPreview(const nlohmann::json& Args);
    void CancelPreview(bool Clear);
    void SendPreview();
    void PumpPreview();
    void PreviewEvent(const std::string& Name, const nlohmann::json& Data);

    // Job progress written by the worker, flushed by OnTimer.
    struct JobState
    {
        std::string Title, Status;
        int Progress = -1;
        bool Cancellable = false;
        bool AssetExport = false;
        uint32_t Generation = 0;
        bool Dirty = false;
        std::set<uint32_t> Rows;
    };
    std::mutex JobLock;
    JobState Job;

    std::mutex AskLock;
    uint32_t NextAsk = 0;
    std::map<uint32_t, std::promise<int>> Asks;

    friend struct WebSink;
    static void OnExportProgress(void* Caller, uint32_t Progress);
    static void OnExportStatus(void* Caller, uint32_t Index);

    nlohmann::json Dispatch(const std::string& Command, const nlohmann::json& Args, const std::vector<std::string>& Files);
    void Reply(const nlohmann::json& Id, bool Ok, const nlohmann::json& Value);
    void Emit(const std::string& Name, const nlohmann::json& Data);
    void Toast(const std::string& Text, bool Error = false);
    void Notice(const std::string& Title, const std::string& Text);

    nlohmann::json State(bool Reset = false);
    nlohmann::json Settings();
    void EmitState(bool Reset = false) { Emit("state", State(Reset)); }

    void StartLoad(const std::string& File);
    void Query(const nlohmann::json& Args);
    nlohmann::json Rows(size_t Start, size_t Count);
    std::vector<CoDAsset_t*> Selection(const nlohmann::json& Args);

    bool CanStart();
    void StartJob(const std::string& Title, const std::string& Initial, bool Cancellable,
        std::function<JobResult(JobSink&)> Work, bool AssetExport = false,
        std::function<void(const JobResult&)> Done = {});
    void RunTool(const std::string& Tool);
    // Downloads names when Folder is empty, otherwise validates that folder.
    void UpdateNames(const std::string& Folder);
    void NamesChanged();
    int Ask(const std::string& Title, const std::string& Text);
    void AnswerAll(int Answer);

    std::string PickFile(const std::string& Title, const std::string& Filter);
    std::string PickFolder(const std::string& Title, const std::string& Initial);
};
