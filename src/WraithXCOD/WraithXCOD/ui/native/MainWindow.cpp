#include "stdafx.h"
#include "assets/SalukiNameDatabase.h"
#include "shared/CWRadiantExport.h"

// The class we are implementing
#include "ui/native/MainWindow.h"

// We need the following Wraith classes
#include "Strings.h"
#include "FileSystems.h"
#include "WraithApp.h"
#include "WraithFileDialogs.h"
#include "SettingsManager.h"
#include "WraithTheme.h"

// The custom windows
#include "settings/SettingsWindow.h"
#include "ui/native/AboutWindow.h"

// String View
#include <string_view>
#include <charconv>
#include <fstream>
#include <set>
#include "json.hpp"
#include "Image.h"
#include "games/cold_war/reader/GameBlackOpsCW.h"
#include "games/black_ops_4/reader/GameBlackOps4.h"
#include "exporters/ModelBatchSelection.h"
#include "exporters/ModelBatchResume.h"
#include "exporters/ModelExportNaming.h"
#include "games/cold_war/placements/CWStaticPlacementFilter.h"
#include "exporters/ExportRun.h"
#include "assets/AssetSearch.h"
#include "exporters/ExportJobs.h"

// Update cube icon callback
#define UPDATE_CUBE_ICON (WM_USER + 137)

BEGIN_MESSAGE_MAP(MainWindow, WraithWindow)
    ON_COMMAND(IDC_LOADGAME, OnLoadGame)
    ON_COMMAND(IDC_LOADFILE, OnLoadFile)
    ON_COMMAND(IDC_CLEARALL, OnClearAll)
    ON_COMMAND(IDC_EXPORTALL, OnExportAll)
    ON_COMMAND(IDC_EXPORT_JSON_MODELS, OnExportJsonModels)
    ON_COMMAND(IDC_EXPORT_SPLINE_MODELS, OnExportSplineModels)
    ON_COMMAND(IDC_EXPORT_PLACEMENTS, OnExportPlacements)
    ON_COMMAND(IDC_EXPORT_BRUSHES, OnExportBrushes)
    ON_COMMAND(IDC_DEV_BO4_RUN, OnRunBO4Diagnostic)
    ON_COMMAND(IDC_DEV_VERIFY_RUNTIME, OnVerifyRuntime)
    ON_COMMAND(IDC_DEV_VERIFY_EXPORT, OnVerifyExport)
    ON_COMMAND(IDC_DEV_TERRAIN_SOURCE, OnTerrainSource)
    ON_COMMAND(IDC_EXPORTSELECTED, OnExportSelected)
    ON_COMMAND(IDC_SEARCH, OnSearch)
    ON_COMMAND(IDC_CLEARSEARCH, OnClearSearch)
    ON_COMMAND(IDC_MORE, OnMore)
    ON_COMMAND(ID_SETTINGS_ABOUT, OnAbout)
    ON_COMMAND(ID_SETTINGS_SUPPORT, OnSupport)
    ON_MESSAGE(UPDATE_CUBE_ICON, UpdateCubeIcon)
    ON_WM_DESTROY()
    ON_NOTIFY(NM_DBLCLK, IDC_ASSETLIST, OnAssetListDoubleClick)
END_MESSAGE_MAP()

void MainWindow::OnBeforeLoad()
{
    // Setup dialog
    ProgressDialog = std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG, this);

    // Setup popup
    PopupDialog = std::make_unique<WraithPopup>(IDD_POPUPDLG, this);
    // Prepare the popup
    PopupDialog->PreparePopup();

    // Hook it
    AssetListView.OnGetListViewInfo = GetListViewInfo;

    // Adjust layout
    ShiftControl(IDC_ASSETCOUNT, CRect(1, 1, 0, 0));
    // Set anchors
    SetControlAnchor(IDC_ASSETLIST, 0, 0, 100, 100);
    SetControlAnchor(IDC_LOADGAME, 0, 100, 0, 0);
    SetControlAnchor(IDC_LOADFILE, 0, 100, 0, 0);
    SetControlAnchor(IDC_EXPORTSELECTED, 0, 100, 0, 0);
    SetControlAnchor(IDC_EXPORTALL, 0, 100, 0, 0);
    SetControlAnchor(IDC_CLEARALL, 0, 100, 0, 0);
    SetControlAnchor(IDC_MORE, 100, 100, 0, 0);
    SetControlAnchor(IDC_ASSETCOUNT, 0, 100, 0, 0);
    SetControlAnchor(IDC_SEARCHTEXT, 0, 0, 100, 0);
    SetControlAnchor(IDC_SEARCH, 100, 0, 0, 0);
    SetControlAnchor(IDC_CLEARSEARCH, 100, 0, 0, 0);

    // Add list columns
    AssetListView.AddHeader("Asset name", 280);
    AssetListView.AddHeader("Status", 120);
    AssetListView.AddHeader("Type", 100);
    AssetListView.AddHeader("Details", 220);
}

void MainWindow::OnLoad()
{
    // Set the asset count text
    CString AssetCountFmt;
    // Format
    AssetCountFmt.Format(L"Assets loaded: 0");
    // Apply
    SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

    // Setup the game-cube display (Aligned)
    GameCube.Create(NULL, L"", WS_VISIBLE, CRect(725, 4, 759, 36), this, 133);

    // Setup the control anchor for the cube
    SetControlAnchor(133, 100, 0, 0, 0);

    // Load icon in sync
    this->SendMessage(UPDATE_CUBE_ICON, 0, 0);
}

void MainWindow::DoDataExchange(CDataExchange* pDX)
{
    // Handle base
    WraithWindow::DoDataExchange(pDX);
    // Map our list control to a WraithListView
    DDX_Control(pDX, IDC_ASSETLIST, AssetListView);
    DDX_Control(pDX, IDC_MORE, ExtraSplitMenu);
    DDX_Control(pDX, IDC_SEARCHTEXT, SearchTextBox);
    // Initialize the view
    AssetListView.InitializeListView();
    // Load our menu
    ExtraSplitMenu.SetDropDownMenu(IDR_EXTRAMENU, 0);
}

void MainWindow::OnFilesDrop(const std::vector<std::wstring> Files)
{
    // Ensure that the load file button is currently enabled
    if (this->GetDlgItem(IDC_LOADFILE)->IsWindowEnabled() && Files.size() > 0)
    {
        // We can proceed to load the file
        auto Result = Strings::ToNormalString(Files[0]);
        // Ensure result is ok
        if (!Strings::IsNullOrWhiteSpace(Result))
        {
            // Disable control states
            GetDlgItem(IDC_LOADGAME)->EnableWindow(false);
            GetDlgItem(IDC_LOADFILE)->EnableWindow(false);
            GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
            GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
            GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
            GetDlgItem(IDC_SEARCH)->EnableWindow(false);
            GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

            // Clear all assets
            AssetListView.SetVirtualCount(0);
            // Set the display
            CString AssetCountFmt;
            // Format
            AssetCountFmt.Format(L"Assets loaded: 0");
            // Apply
            SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

            // Prepare to pass it off
            std::thread LoadAsync([this, Result]
            {
                // Run it
                this->LoadGameFileAsync(Result);
            });

            // Detatch
            LoadAsync.detach();
        }
    }
}

void MainWindow::OnAssetListDoubleClick(NMHDR* pNMHDR, LRESULT* pResult)
{
    // The cursor location
    CPoint CursorPos;
    // Fetch it
    GetCursorPos(&CursorPos);
    // Convert to client points
    this->AssetListView.ScreenToClient(&CursorPos);
    // Flag result
    UINT Flags = 0;
    // The item index, if selected
    int hItem = this->AssetListView.HitTest(CursorPos, &Flags);

    // Check if we're on an item
    if (Flags & LVHT_ONITEMLABEL)
    {
        // Handle exporting hItem
        if (hItem > -1)
        {
            // Prepare the dialog
            ProgressDialog = std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG, this);
            // Setup the dialog
            ProgressDialog->SetupDialog("Greyhound | Exporting...", "Exporting...", false, true);
            // Hook buttons
            ProgressDialog->OnCancelClick = CancelProgress;
            ProgressDialog->OnOkClick = FinishProgress;

            // Hook callbacks
            CoDAssets::OnExportProgress = OnProgressCallback;
            CoDAssets::OnExportStatus = OnStatusCallback;

            // Export in async
            std::thread ExportAsync([this, hItem]
            {
                // Wait
                this->ProgressDialog->WaitTillReady();
                // Buttons
                this->ProgressDialog->UpdateButtons(false, false);
                // Close
                this->ProgressDialog->UpdateWindowClose(false);

                // Export the one item
                CoDAssets::ExportSelection({ (uint32_t)hItem }, this);

                // Close it
                this->ProgressDialog->UpdateWindowClose(true);
                this->ProgressDialog->CloseProgress();

                // Get the asset list
                auto& LoadedAssets = (SearchMode) ? SearchResults : CoDAssets::GameAssets->LoadedAssets;
                // Get the unique name for this asset
                auto& AssetName = LoadedAssets[(uint32_t)hItem]->AssetName;
                // Show popup
                this->PopupDialog->ShowPopup(Strings::Format("%s was exported", AssetName.c_str()).c_str(), CoDAssets::ExportRoot().c_str(), 6000);
            });
            // Detatch
            ExportAsync.detach();

            // Launch
            ProgressDialog->DoModal();
        }
    }
}

void MainWindow::GetListViewInfo(LV_ITEM* ListItem, CWnd* Owner)
{
    // This is our main window instance
    auto Window = (MainWindow*)Owner;

    // Fetch if we can
    if (CoDAssets::GameAssets != nullptr)
    {
        // This is the list object we want to use
        auto& LoadedAssets = (Window->SearchMode) ? Window->SearchResults : CoDAssets::GameAssets->LoadedAssets;

        // Ensure we are in the object bounds
        if (ListItem->iItem < LoadedAssets.size())
        {
            // Grab the asset
            auto Asset = LoadedAssets[ListItem->iItem];

            // Check which value to get
            if (ListItem->iSubItem == 0)
            {
                // Buffer for name
                auto NameBuffer = Strings::ToUnicodeString(Asset->AssetName);
                // Name is copied from the buffer
                _tcscpy_s(ListItem->pszText, ListItem->cchTextMax, NameBuffer.c_str());
            }
            else if (ListItem->iSubItem == 1)
            {
                // Desired status
                auto AssetStatusStr = L"^3Unknown";

                // Asset status
                switch (Asset->AssetStatus)
                {
                case WraithAssetStatus::Loaded: AssetStatusStr = L"^0Loaded"; break;
                case WraithAssetStatus::Exported: AssetStatusStr = L"^2Exported"; break;
                case WraithAssetStatus::Processing: AssetStatusStr = L"^5Processing"; break;
                case WraithAssetStatus::Placeholder: AssetStatusStr = L"^4Placeholder"; break;
                case WraithAssetStatus::Error: AssetStatusStr = L"^1Error"; break;
                }

                // Set the status
                _tcscpy_s(ListItem->pszText, ListItem->cchTextMax, AssetStatusStr);
            }
            else if (ListItem->iSubItem == 2)
            {
                // Desired type
                auto AssetTypeStr = L"Unknown";

                // Type
                switch (Asset->AssetType)
                {
                case WraithAssetType::Model: AssetTypeStr = L"Model"; break;
                case WraithAssetType::Animation: AssetTypeStr = L"Anim"; break;
                case WraithAssetType::Image: AssetTypeStr = L"Image"; break;
                case WraithAssetType::Sound: AssetTypeStr = L"Sound"; break;
                case WraithAssetType::RawFile: AssetTypeStr = L"Rawfile"; break;
                case WraithAssetType::Effect: AssetTypeStr = L"Effect"; break;
                case WraithAssetType::Material: AssetTypeStr = L"Material"; break;
                case WraithAssetType::Terrain: AssetTypeStr = L"TerrainGfx"; break;
                }

                // Set the type
                _tcscpy_s(ListItem->pszText, ListItem->cchTextMax, AssetTypeStr);
            }
            else if (ListItem->iSubItem == 3)
            {
                // Details, these differ per-asset type (Model "Bones, Lods", Anim "Frames, Framerate", Image "Width, Height")
                CString DetailsFmt;

                // Check type and format it
                switch (Asset->AssetType)
                {
                case WraithAssetType::Model:
                    // Model info
                    if(((CoDModel_t*)Asset)->CosmeticBoneCount == 0)
                        DetailsFmt.Format(L"Bones: %d, LODs: %d", ((CoDModel_t*)Asset)->BoneCount, ((CoDModel_t*)Asset)->LodCount);
                    else
                        DetailsFmt.Format(L"Bones: %d, Cosmetics: %d, LODs: %d", ((CoDModel_t*)Asset)->BoneCount, ((CoDModel_t*)Asset)->CosmeticBoneCount, ((CoDModel_t*)Asset)->LodCount);
                    break;
                case WraithAssetType::Animation:
                    // Anim info
                    DetailsFmt.Format(L"Framerate: %.2f, Frames: %d, Bones: %d", ((CoDAnim_t*)Asset)->Framerate, ((CoDAnim_t*)Asset)->FrameCount, ((CoDAnim_t*)Asset)->BoneCount);
                    break;
                case WraithAssetType::Image:
                    // Validate info (Some image resources may not have information available)
                    if (((CoDImage_t*)Asset)->Width > 0)
                    {
                        // Image info
                        DetailsFmt.Format(L"Width: %d, Height: %d", ((CoDImage_t*)Asset)->Width, ((CoDImage_t*)Asset)->Height);
                    }
                    else
                    {
                        // Image info not available
                        DetailsFmt = "N/A";
                    }
                    break;
                case WraithAssetType::Sound:
                {
                    // Validate info (Some image resources may not have information available)
                    if (((CoDSound_t*)Asset)->Length > 0)
                    {
                        // Sound info
                        auto Time = Strings::ToUnicodeString(Strings::DurationToReadableTime(std::chrono::milliseconds(((CoDSound_t*)Asset)->Length)));
                        // Formatted time
                        DetailsFmt.Format(L"%s", Time.c_str());
                    }
                    else
                    {
                        // Sound info not available
                        DetailsFmt = "N/A";
                    }
                    break;
                }
                case WraithAssetType::Material:
                    // Rawfile info
                    DetailsFmt.Format(L"Images: %llu", ((CoDMaterial_t*)Asset)->ImageCount);
                    break;
                case WraithAssetType::RawFile:
                    // Rawfile info
                    DetailsFmt.Format(L"Size: 0x%llx", Asset->AssetSize);
                    break;
                case WraithAssetType::Terrain:
                    DetailsFmt.Format(L"Header: 0x%llx bytes", Asset->AssetSize);
                    break;
                }

                // Copy
                _tcscpy_s(ListItem->pszText, ListItem->cchTextMax, DetailsFmt);
            }
        }
    }
}

void MainWindow::OnLoadGame()
{
    StartAssetLoad("");
}

void MainWindow::StartAssetLoad(const std::string& File)
{
    GetDlgItem(IDC_MORE)->EnableWindow(false);
    GetDlgItemText(IDC_SEARCHTEXT, SearchAfterLoad);
    // Disable control states
    GetDlgItem(IDC_LOADGAME)->EnableWindow(false);
    GetDlgItem(IDC_LOADFILE)->EnableWindow(false);
    GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
    GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
    GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
    GetDlgItem(IDC_SEARCH)->EnableWindow(false);
    GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

    // Clear search
    this->ClearSearch(true);

    // Clear all assets
    AssetListView.SetVirtualCount(0);
    // Set the display
    CString AssetCountFmt;
    // Format
    AssetCountFmt.Format(L"Assets loaded: 0");
    // Apply
    SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

    // Load in async
    std::thread LoadAsync([this, File]
    {
        if (File.empty()) this->LoadGameAsync();
        else this->LoadGameFileAsync(File);
    });

    // Detatch
    LoadAsync.detach();
}

void MainWindow::LoadGameAsync()
{
    LastLoadedFile.clear();
    // Rebuild name caches as well as the list when the selected database changes.
    CoDAssets::CleanUpGame();
    SalukiNameDatabase::AutoUpdate();
    // Prepare to load the game, and report back if need be
    auto LoadGameResult = FindGameResult::FailedToLocateInfo;
    try { LoadGameResult = CoDAssets::BeginGameMode(); }
    catch (const std::exception& E)
    { MessageBoxA(GetSafeHwnd(), E.what(), "Loading names / assets", MB_OK | MB_ICONWARNING); }

    // Check if we had success
    if (LoadGameResult == FindGameResult::Success)
    {
        // Setup the controls for game loaded, setup game cube
        GetDlgItem(IDC_LOADGAME)->EnableWindow(true);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(true);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(true);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(true);
        GetDlgItem(IDC_SEARCH)->EnableWindow(true);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(true);

        // Get size
        auto AssetsCount = (uint32_t)CoDAssets::GameAssets->LoadedAssets.size();

        // Set size
        AssetListView.SetVirtualCount(AssetsCount);
        // Refresh the list
        AssetListView.Invalidate();

        // Set the asset count text
        CString AssetCountFmt;
        // Format
        AssetCountFmt.Format(L"Assets loaded: %d", AssetsCount);
        // Apply
        SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

        // Load icon in sync
        this->SendMessage(UPDATE_CUBE_ICON, 0, 0);
        FinishNameRefresh();
    }
    else if (LoadGameResult == FindGameResult::NoGamesRunning)
    {
        // Setup default controls
        GetDlgItem(IDC_LOADGAME)->EnableWindow(true);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(true);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
        GetDlgItem(IDC_SEARCH)->EnableWindow(false);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

        // Notify the user about the issue
        MessageBoxA(this->GetSafeHwnd(), "No instances of any supported game were found. Please make sure the game is running first.", "Greyhound", MB_OK | MB_ICONWARNING);
    }
    else if (LoadGameResult == FindGameResult::FailedToLocateInfo)
    {
        // Setup default controls
        GetDlgItem(IDC_LOADGAME)->EnableWindow(true);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(true);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
        GetDlgItem(IDC_SEARCH)->EnableWindow(false);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

        // Notify the user about the issue
        MessageBoxA(this->GetSafeHwnd(), "This game is supported, but the current update is not. Please wait for an upcoming patch for support.", "Greyhound", MB_OK | MB_ICONWARNING);
    }
    if (LoadGameResult != FindGameResult::Success) { ActionAfterLoad = 0; SearchAfterLoad.Empty(); }
    GetDlgItem(IDC_MORE)->EnableWindow(true);
}

void MainWindow::OnClearAll()
{
    // Enable defaults
    GetDlgItem(IDC_LOADGAME)->EnableWindow(true);
    GetDlgItem(IDC_LOADFILE)->EnableWindow(true);
    GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
    GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
    GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
    GetDlgItem(IDC_SEARCH)->EnableWindow(false);
    GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

    // Clear search
    this->ClearSearch(true);

    // Clear all assets
    AssetListView.SetVirtualCount(0);
    // Set the display
    CString AssetCountFmt;
    // Format
    AssetCountFmt.Format(L"Assets loaded: 0");
    // Apply
    SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

    // Unload in async
    std::thread LoadAsync([this]
    {
        // Unload all
        this->ClearAllAsync();
    });

    // Detatch
    LoadAsync.detach();
}

void MainWindow::ClearAllAsync()
{
    // Tell the assets pool to clean up everything
    CoDAssets::CleanUpGame();

    // Load icon in sync
    this->SendMessage(UPDATE_CUBE_ICON, 0, 0);
}

void MainWindow::OnSettings()
{
    const auto Before = SettingsManager::GetSetting("salukinamefolder", "") + SettingsManager::GetSetting("salukirevision", "");
    // Show the settings dialog
    SettingsWindow SettingsDialog(this);
    // Show it
    const auto Action = SettingsDialog.DoModal();
    const auto After = SettingsManager::GetSetting("salukinamefolder", "") + SettingsManager::GetSetting("salukirevision", "");
    const bool ExportAction = Action == IDC_EXPORT_PLACEMENTS || Action == IDC_EXPORT_JSON_MODELS || Action == IDC_EXPORT_SPLINE_MODELS || Action == IDC_EXPORT_BRUSHES ||
        Action == IDC_DEV_TERRAIN_SOURCE || Action == IDC_DEV_BO4_RUN || Action == IDC_DEV_VERIFY_RUNTIME || Action == IDC_DEV_VERIFY_EXPORT;
    if (Before != After && CoDAssets::GameAssets)
    {
        ActionAfterLoad = ExportAction ? static_cast<int>(Action) : 0;
        StartAssetLoad(LastLoadedFile);
        return;
    }
    if (Action == IDC_EXPORT_PLACEMENTS || Action == IDC_EXPORT_JSON_MODELS || Action == IDC_EXPORT_SPLINE_MODELS || Action == IDC_EXPORT_BRUSHES ||
        Action == IDC_DEV_TERRAIN_SOURCE || Action == IDC_DEV_BO4_RUN || Action == IDC_DEV_VERIFY_RUNTIME || Action == IDC_DEV_VERIFY_EXPORT)
        PostMessage(WM_COMMAND, Action);
}

void MainWindow::FinishNameRefresh()
{
    if (!SearchAfterLoad.IsEmpty())
    {
        SetDlgItemText(IDC_SEARCHTEXT, SearchAfterLoad);
        SearchAfterLoad.Empty();
        SendMessage(WM_COMMAND, IDC_SEARCH);
    }
    if (ActionAfterLoad) { PostMessage(WM_COMMAND, ActionAfterLoad); ActionAfterLoad = 0; }
}

void MainWindow::OnExportAll()
{
    // Prepare the dialog
    ProgressDialog = std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG, this);
    // Setup the dialog
    ProgressDialog->SetupDialog("Greyhound | Exporting...", "Exporting...", true, true);
    // Hook buttons
    ProgressDialog->OnCancelClick = CancelProgress;
    ProgressDialog->OnOkClick = FinishProgress;

    // Hook callbacks
    CoDAssets::OnExportProgress = OnProgressCallback;
    CoDAssets::OnExportStatus = OnStatusCallback;

    // Export in async
    std::thread ExportAsync([this]
    {
        // Wait for progress dialog to open fully
        this->ProgressDialog->WaitTillReady();
        // Setup progress dialog features
        this->ProgressDialog->UpdateWindowClose(false);
        this->ProgressDialog->UpdateButtons(false, true);

        // Export All
        CoDAssets::ExportAllAssets(this);

        // Check if we got canceled
        if (CoDAssets::CanExportContinue)
        {
            // Once we get here, we can allow people to close it
            this->ProgressDialog->UpdateWindowClose(true);
            this->ProgressDialog->UpdateButtons(true, false);

            // Update status
            this->ProgressDialog->UpdateStatus("Export complete");
            // Show popup
            this->PopupDialog->ShowPopup("Bulk export has finished", CoDAssets::ExportRoot().c_str(), 6000);
        }
        else
        {
            // Just close, we canceled
            this->ProgressDialog->UpdateWindowClose(true);
            this->ProgressDialog->CloseProgress();
        }
    });
    // Detatch
    ExportAsync.detach();

    // Show the dialog
    ProgressDialog->DoModal();
}

void MainWindow::OnExportSelected()
{
    // Grab the list of objects
    auto SelectedIndicies = AssetListView.GetSelectedItems();

    // Continue if we got some
    if (SelectedIndicies.size() > 0)
    {
        // Prepare the dialog
        ProgressDialog = std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG, this);
        // Setup the dialog
        ProgressDialog->SetupDialog("Greyhound | Exporting...", "Exporting...", true, true);
        // Hook buttons
        ProgressDialog->OnCancelClick = CancelProgress;
        ProgressDialog->OnOkClick = FinishProgress;

        // Hook callbacks
        CoDAssets::OnExportProgress = OnProgressCallback;
        CoDAssets::OnExportStatus = OnStatusCallback;

        // Export in async
        std::thread ExportAsync([this, SelectedIndicies]
        {
            // Wait for progress dialog to open fully
            this->ProgressDialog->WaitTillReady();
            // Setup progress dialog features
            this->ProgressDialog->UpdateWindowClose(false);
            this->ProgressDialog->UpdateButtons(false, true);

            // Export All
            CoDAssets::ExportSelection(SelectedIndicies, this);

            // Check if we got canceled
            if (CoDAssets::CanExportContinue)
            {
                // Once we get here, we can allow people to close it
                this->ProgressDialog->UpdateWindowClose(true);
                this->ProgressDialog->UpdateButtons(true, false);

                // Update status
                this->ProgressDialog->UpdateStatus("Export complete");
                // Show popup
                this->PopupDialog->ShowPopup("Bulk export has finished", CoDAssets::ExportRoot().c_str(), 6000);
            }
            else
            {
                // Just close, we canceled
                this->ProgressDialog->UpdateWindowClose(true);
                this->ProgressDialog->CloseProgress();
            }
        });
        // Detatch
        ExportAsync.detach();

        // Show the dialog
        ProgressDialog->DoModal();
    }
}

void MainWindow::OnProgressCallback(void* Caller, uint32_t Progress)
{
    // Grab us
    auto Window = (MainWindow*)Caller;

    // Call the progress updater
    Window->ProgressDialog->UpdateProgress(Progress);
}

void MainWindow::OnStatusCallback(void* Caller, uint32_t Index)
{
    // Grab us
    auto Window = (MainWindow*)Caller;

    // Refresh out list
    Window->AssetListView.Update(Index);
}

void MainWindow::CancelProgress(CWnd* Owner)
{
    // Grab us
    auto Window = (MainWindow*)Owner;

    // Cancel it
    CoDAssets::CanExportContinue = false;
}

void MainWindow::FinishProgress(CWnd* Owner)
{
    // Grab us
    auto Window = (MainWindow*)Owner;

    // Close
    Window->ProgressDialog->CloseProgress();
}

void MainWindow::OnDestroy()
{
}

void MainWindow::OnSupport()
{
    // Spawn wiki post
    ShellExecuteA(NULL, "open", "https://github.com/Scobalula/Greyhound/wiki", NULL, NULL, SW_SHOWNORMAL);
}

void MainWindow::OnLoadFile()
{
    // Prepare to load a file, first, ask for one
    auto Result = WraithFileDialogs::OpenFileDialog("Select a game file to load", "", "All files (*.*)|*.*;|Image Package Files (*.iwd, *.ipak, *.xpak)|*.iwd;*.ipak;*.xpak|Sound Package Files (*.sabs, *.sabl)|*.sabs;*.sabl;", this->GetSafeHwnd());
    // Make sure
    if (!Strings::IsNullOrWhiteSpace(Result))
    {
        // Disable control states
        GetDlgItem(IDC_LOADGAME)->EnableWindow(false);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
        GetDlgItem(IDC_SEARCH)->EnableWindow(false);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

        // Clear all assets
        AssetListView.SetVirtualCount(0);
        // Set the display
        CString AssetCountFmt;
        // Format
        AssetCountFmt.Format(L"Assets loaded: 0");
        // Apply
        SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

        // Prepare to pass it off
        std::thread LoadAsync([this, Result]
        {
            // Run it
            this->LoadGameFileAsync(Result);
        });

        // Detatch
        LoadAsync.detach();
    }
}

void MainWindow::LoadGameFileAsync(const std::string& FilePath)
{
    GetDlgItem(IDC_MORE)->EnableWindow(false);
    SalukiNameDatabase::AutoUpdate();
    // Prepare to load the file, and report back if need be
    auto LoadFileResult = LoadGameFileResult::UnknownError;
    try { LoadFileResult = CoDAssets::BeginGameFileMode(FilePath); }
    catch (const std::exception& E)
    { MessageBoxA(GetSafeHwnd(), E.what(), "Loading names / assets", MB_OK | MB_ICONWARNING); }

    // Check if we had success
    if (LoadFileResult == LoadGameFileResult::Success)
    {
        LastLoadedFile = FilePath;
        // Setup the controls for game loaded, setup game cube
        GetDlgItem(IDC_LOADGAME)->EnableWindow(false);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(true);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(true);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(true);
        GetDlgItem(IDC_SEARCH)->EnableWindow(true);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(true);

        // Get size
        auto AssetsCount = (uint32_t)CoDAssets::GameAssets->LoadedAssets.size();

        // Set size
        AssetListView.SetVirtualCount(AssetsCount);
        // Refresh the list
        AssetListView.Invalidate();

        // Set the asset count text
        CString AssetCountFmt;
        // Format
        AssetCountFmt.Format(L"Assets loaded: %d", AssetsCount);
        // Apply
        SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);
    }
    else if (LoadFileResult == LoadGameFileResult::InvalidFile)
    {
        // Setup default controls
        GetDlgItem(IDC_LOADGAME)->EnableWindow(true);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(true);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
        GetDlgItem(IDC_SEARCH)->EnableWindow(false);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

        // Notify the user about the issue
        MessageBoxA(this->GetSafeHwnd(), "The file you have provided was invalid.", "Greyhound", MB_OK | MB_ICONWARNING);
    }
    else if (LoadFileResult == LoadGameFileResult::UnknownError)
    {
        // Setup default controls
        GetDlgItem(IDC_LOADGAME)->EnableWindow(true);
        GetDlgItem(IDC_LOADFILE)->EnableWindow(true);
        GetDlgItem(IDC_EXPORTSELECTED)->EnableWindow(false);
        GetDlgItem(IDC_EXPORTALL)->EnableWindow(false);
        GetDlgItem(IDC_CLEARALL)->EnableWindow(false);
        GetDlgItem(IDC_SEARCH)->EnableWindow(false);
        GetDlgItem(IDC_SEARCHTEXT)->EnableWindow(false);

        // Notify the user about the issue
        MessageBoxA(this->GetSafeHwnd(), "An unknown error has occured while loading the file.", "Greyhound", MB_OK | MB_ICONWARNING);
    }
    if (LoadFileResult == LoadGameFileResult::Success) FinishNameRefresh();
    else { ActionAfterLoad = 0; SearchAfterLoad.Empty(); }
    GetDlgItem(IDC_MORE)->EnableWindow(true);
}

LRESULT MainWindow::UpdateCubeIcon(WPARAM wParam, LPARAM lParam)
{
    // Not needed
    UNREFERENCED_PARAMETER(wParam);
    UNREFERENCED_PARAMETER(lParam);

    // Update it to the game, or the default wraith icon
    if (CoDAssets::GameInstance != nullptr && CoDAssets::GameInstance->IsRunning())
    {
        // Extract the icon, cancel on failure
        auto GameIcon = FileSystems::ExtractFileIcon(CoDAssets::GameInstance->GetProcessPath());
        // Load if not null
        if (GameIcon != NULL)
        {
            // Load into cube, then clean up
            GameCube.LoadCubeIcon(GameIcon);
            DestroyIcon(GameIcon);
            // Handled
            return 0;
        }
    }

    // We must restore default icon
    GameCube.LoadCubeIcon(WraithTheme::ApplicationIconLarge);

    // Nothing
    return 0;
}

void MainWindow::OnSearch()
{
    // Reset search
    this->ClearSearch(false);
    // Prepare to search for assets
    if (CoDAssets::GameAssets != nullptr)
    {
        // Fetch the value
        CString TextValue = "";
        GetDlgItemText(IDC_SEARCHTEXT, TextValue);

        // Grab as a string
        std::string SearchText = Strings::ToNormalString(std::wstring((LPCWSTR)TextValue));
        // Filter with the shared search language
        SearchResults = AssetSearch::Filter(SearchText, CoDAssets::GameAssets->LoadedAssets);

        // Engage search mode
        SearchMode = true;
        AssetListView.SetVirtualCount((uint32_t)SearchResults.size());
        AssetListView.Invalidate();

        // Format size
        CString AssetCountFmt;
        AssetCountFmt.Format(L"Assets found: %d", (uint32_t)SearchResults.size());
        // Apply
        SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);

        // Show the clear button
        GetDlgItem(IDC_CLEARSEARCH)->EnableWindow(true);
    }
}

void MainWindow::OnClearSearch()
{
    // Proxy over
    this->ClearSearch(true);
}

void MainWindow::ClearSearch(bool ResetSearch)
{
    // Disengage search mode
    SearchMode = false;
    // If we have assets still, set the count
    if (CoDAssets::GameAssets != nullptr)
    {
        // Fetch size
        auto FoundSize = (uint32_t)CoDAssets::GameAssets->LoadedAssets.size();

        // Apply
        AssetListView.SetVirtualCount(FoundSize);

        // Format size
        CString AssetCountFmt;
        AssetCountFmt.Format(L"Assets loaded: %d", FoundSize);
        // Apply
        SetDlgItemText(IDC_ASSETCOUNT, AssetCountFmt);
    }
    AssetListView.Invalidate();

    // Clear results, free list memory
    SearchResults.clear();
    SearchResults.shrink_to_fit();

    // Reset text and disable button
    if (ResetSearch)
    {
        GetDlgItem(IDC_SEARCHTEXT)->SetWindowTextW(L"");
    }
    GetDlgItem(IDC_CLEARSEARCH)->EnableWindow(false);
}

void MainWindow::OnMore()
{
    // Show settings
    OnSettings();
}

void MainWindow::OnAbout()
{
    // Show the about dialog
    AboutWindow AboutDialog(this);
    // Show it
    AboutDialog.DoModal();
}

BOOL MainWindow::PreTranslateMessage(MSG* pMsg)
{
    // Check for enter key on the control
    if (pMsg->message == WM_KEYDOWN && pMsg->wParam == VK_RETURN && GetFocus() == &SearchTextBox)
    {
        // Press search
        this->OnSearch();
        // Handle return pressed in edit control
        return TRUE;
    }
    else if(GetFocus() == &AssetListView && (GetKeyState(VK_CONTROL) & 0x8000 && (pMsg->wParam == 'C' || pMsg->wParam == 'X')))
    {
        // Grab the list of objects
        auto SelectedIndicies = AssetListView.GetSelectedItems();
        // Continue if we got some
        if (SelectedIndicies.size() > 0)
        {
            // New line or not
            bool NewLine = pMsg->wParam == 'C';
            // Our output
            std::stringstream Output;
            // Resolve the asset list
            auto& LoadedAssets = (this->SearchMode) ? this->SearchResults : CoDAssets::GameAssets->LoadedAssets;
            // Loop and output the stream
            for (auto SelectedIndex : SelectedIndicies)
            {
                if(NewLine)
                    Output << LoadedAssets[SelectedIndex]->AssetName << "\n";
                else
                    Output << LoadedAssets[SelectedIndex]->AssetName << ",";
            }
            // Attempt to open the clip board
            if (OpenClipboard())
            {
                // Empty it
                EmptyClipboard();
                // Convert to unicode and create a handle
                auto AsUnicode = Strings::ToUnicodeString(Output.str());
                auto Handle = GlobalAlloc(GMEM_MOVEABLE | GMEM_DDESHARE, (AsUnicode.length() + 1) * sizeof(WCHAR));
                // Validate
                if (Handle != NULL)
                {
                    // Lock the buffer
                    auto Buffer = (LPWSTR)GlobalLock(Handle);
                    // Validate
                    if (Buffer != nullptr)
                    {
                        memcpy(Buffer, AsUnicode.c_str(), AsUnicode.length() * sizeof(WCHAR));
                        SetClipboardData(CF_UNICODETEXT, Handle);
                        CloseClipboard();
                    }
                }
            }
        }
    }

    // All other cases still need default processing
    return FALSE;
}

namespace
{
    // Routes a shared export job into the classic progress dialog.
    struct DialogSink : JobSink
    {
        WraithProgressDialog* Dialog;
        explicit DialogSink(WraithProgressDialog* Target) : Dialog(Target) {}
        void Status(const std::string& Text) override { Dialog->UpdateStatus(Text); }
        void Progress(uint32_t Percent) override { Dialog->UpdateProgress(Percent); }
        int Ask(const std::string& Title, const std::string& Text) override
        {
            return MessageBoxA(Dialog->GetSafeHwnd(), Text.c_str(), Title.c_str(), MB_YESNOCANCEL | MB_ICONQUESTION);
        }
    };
}

void MainWindow::RunJob(const std::string& Title, const std::string& Initial, bool Cancellable,
    const std::function<JobResult(JobSink&)>& Job)
{
    ProgressDialog = std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG, this);
    ProgressDialog->SetupDialog("Greyhound | " + Title, Initial, true, Cancellable);
    if (Cancellable) ProgressDialog->OnCancelClick = CancelProgress;
    ProgressDialog->OnOkClick = FinishProgress;
    CoDAssets::CanExportContinue = true;
    std::thread Worker([this, Job, Cancellable]
    {
        ProgressDialog->WaitTillReady(); ProgressDialog->UpdateWindowClose(false); ProgressDialog->UpdateButtons(false, Cancellable);
        DialogSink Sink(ProgressDialog.get());
        const auto Result = Job(Sink);
        ProgressDialog->UpdateWindowClose(true);
        if (Result.Cancelled) { ProgressDialog->CloseProgress(); return; }
        ProgressDialog->UpdateStatus(Result.Status); ProgressDialog->UpdateButtons(true, false);
    });
    Worker.detach(); ProgressDialog->DoModal();
}

void MainWindow::OnExportJsonModels()
{
    const auto Problem = ExportJobs::CheckModelsFromJson();
    if (!Problem.empty()) { MessageBoxA(GetSafeHwnd(), Problem.c_str(), "Models from JSON", MB_OK); return; }
    const auto File = WraithFileDialogs::OpenFileDialog("Select static or non-static model placement JSON", "", "JSON (*.json)|*.json;", GetSafeHwnd());
    if (File.empty()) return;
    RunJob("CAST models from JSON", "Preparing unique models...", true,
        [File](JobSink& Sink) { return ExportJobs::ModelsFromJson(File, Sink); });
}

void MainWindow::OnExportPlacements()
{
    RunJob("Model placements", "Reading model placements...", false, ExportJobs::ModelPlacements);
}

void MainWindow::OnExportBrushes()
{
    const auto Problem = ExportJobs::CheckRadiantBrushes();
    if (!Problem.empty()) { MessageBoxA(GetSafeHwnd(), Problem.c_str(), "Radiant brushes", MB_OK); return; }
    RunJob("Radiant Brushes", "Capturing verified brush data...", false, ExportJobs::RadiantBrushes);
}

void MainWindow::OnTerrainSource()
{
    const auto Problem = ExportJobs::CheckTerrainSource();
    if (!Problem.empty()) { MessageBoxA(GetSafeHwnd(), Problem.c_str(), "Terrain source capture", MB_OK); return; }
    RunJob("Terrain source capture", "Capturing raw terrain source data...", false, ExportJobs::TerrainSource);
}

void MainWindow::OnRunBO4Diagnostic()
{
    int Mode = 0;
    const auto Problem = ExportJobs::CheckBo4Diagnostic(Mode);
    if (!Problem.empty()) { MessageBoxA(GetSafeHwnd(), Problem.c_str(), "Dev Tools", MB_OK); return; }
    if (Mode == 5) { OnExportBrushes(); return; }
    RunJob("BO4 diagnostics", "Capturing selected diagnostic...", false,
        [Mode](JobSink& Sink) { return ExportJobs::Bo4Diagnostic(Mode, Sink); });
}

void MainWindow::OnVerifyRuntime()
{
    RunJob("Export runtime check", "Checking installed tools and dependencies...", false,
        [](JobSink& Sink) { return ExportJobs::VerifyRuntime("", Sink); });
}

void MainWindow::OnVerifyExport()
{
    const auto File = WraithFileDialogs::OpenFileDialog("Select a brush export_report.json or terrain research_capture.report.json", "", "JSON (*.json)|*.json;", GetSafeHwnd());
    if (File.empty()) return;
    RunJob("Saved export check", "Checking published file integrity...", false,
        [File](JobSink& Sink) { return ExportJobs::VerifyRuntime(File, Sink); });
}

void MainWindow::OnExportSplineModels()
{
    const auto Problem = ExportJobs::CheckSplineModels();
    if (!Problem.empty()) { MessageBoxA(GetSafeHwnd(), Problem.c_str(), "Spline models", MB_OK); return; }
    const auto Placements = WraithFileDialogs::OpenFileDialog("Select the matching spline/static model placements JSON", "", "JSON (*.json)|*.json;", GetSafeHwnd());
    if (Placements.empty()) return;
    const auto Controls = WraithFileDialogs::OpenFileDialog("Select splined_models.json captured from this map/session", "", "JSON (*.json)|*.json;", GetSafeHwnd());
    if (Controls.empty()) return;
    RunJob("Spline models", "Baking spline models in your selected export formats...", false,
        [Placements, Controls](JobSink& Sink) { return ExportJobs::SplineModels(Placements, Controls, Sink); });
}
