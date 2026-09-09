#include "stdafx.h"

// The class we are implementing
#include "MainWindow.h"

// We need the following Wraith classes
#include "Strings.h"
#include "FileSystems.h"
#include "WraithApp.h"
#include "WraithFileDialogs.h"
#include "SettingsManager.h"
#include "WraithTheme.h"

// The custom windows
#include "SettingsWindow.h"
#include "AboutWindow.h"

// String View
#include <string_view>
#include <charconv>
#include <fstream>
#include <set>
#include "json.hpp"
#include "Image.h"
#include "GameBlackOpsCW.h"
#include "ModelBatchSelection.h"
#include "ModelBatchResume.h"
#include "ModelExportNaming.h"

// Update cube icon callback
#define UPDATE_CUBE_ICON (WM_USER + 137)

template <typename T, T min, T defaultVal, T max>
class RangedIntSearchValue
{
public:
    T Min;
    T Value;
    T Max;

    RangedIntSearchValue()
    {
        Min = min;
        Value = defaultVal;
        Max = max;
    }

    void SetFromSearchString(std::string view)
    {
        if (view.size() == 0)
            return;

        if (view[0] == '<')
        {
            Max = strtoll(view.data() + 1, NULL, 10);
        }
        else if (view[0] == '>')
        {
            Min = strtoll(view.data() + 1, NULL, 10);
        }
        else
        {
            Value = strtoll(view.data(), NULL, 10);
        }
    }
};

class StringMatch
{
public:
    // The value
    std::string Value;
    // Whether or not to negate the result
    bool Negate;

    // Initializes String Match
    StringMatch(std::string& value) :
        Value(value),
        Negate(false) { }

    // Initializes String Match
    StringMatch(std::string& value, bool negate) :
        Value(value),
        Negate(negate) { }
};

class SearchContext
{
public:
    // List of assets to search for
    std::vector<StringMatch> AssetNames;
    // List of bones to search for
    std::vector<StringMatch> BoneNames;
    // Lod Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> LodCount;
    // Bone Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> BoneCount;
    // Frame Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> FrameCount;
    // Shape Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> ShapeCount;
    // Frame Rate Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> Framerate;
    // Width Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> Width;
    // Height Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> Height;
    // Sound Length Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> SoundLength;
    // Streamed Value
    RangedIntSearchValue<int64_t, 0,            -1, 1>            Streamed;
    // Placeholder Value
    RangedIntSearchValue<int64_t, 0,            -1, 1>            Placeholder;


    // Initializes the search context
    SearchContext(std::string& search);
};

SearchContext::SearchContext(std::string& search)
{
    if (search.size() == 0)
        return;

    bool negate = false;

    size_t currentIndex = 0;

    if (search[currentIndex] == '!')
    {
        negate = true;
        currentIndex++;
    }

    std::string currentString = search;
    size_t currentStart = currentIndex;
    size_t valueStart = 0;

    while (currentIndex < search.length())
    {
        auto nextChar = search[currentIndex++];
        auto atEnd = currentIndex == search.length();

        if (nextChar == ',' || atEnd)
        {
            // We have a value
            if (valueStart != 0)
            {
                auto name = currentString.substr(currentStart, valueStart - 1 - currentStart);
                auto value = currentString.substr(valueStart, currentIndex - (atEnd ? 0 : 1) - valueStart);

                // C# TODO: Use reflection
                if (name == "lodcount")
                {
                    LodCount.SetFromSearchString(value);
                }
                else if (name == "bonecount")
                {
                    BoneCount.SetFromSearchString(value);
                }
                else if (name == "framecount")
                {
                    FrameCount.SetFromSearchString(value);
                }
                else if (name == "shapecount")
                {
                    ShapeCount.SetFromSearchString(value);
                }
                else if (name == "framerate")
                {
                    Framerate.SetFromSearchString(value);
                }
                else if (name == "width")
                {
                    Width.SetFromSearchString(value);
                }
                else if (name == "height")
                {
                    Height.SetFromSearchString(value);
                }
                else if (name == "length")
                {
                    SoundLength.SetFromSearchString(value);
                }
                else if (name == "streamed")
                {
                    Streamed.SetFromSearchString(value);
                }
                else if (name == "placeholder")
                {
                    Placeholder.SetFromSearchString(value);
                }
                else if (name == "bonename")
                {
                    auto boneName = std::string(value.data(), value.size());
                    BoneNames.emplace_back(Strings::ToLower(Strings::Trim(boneName)));
                }
            }
            // Standard asset name
            else
            {
                auto view = currentString.substr(currentStart, currentIndex - currentStart - (atEnd ? 0 : 1));

                if (view.size() != 0)
                {
                    auto assetName = std::string(view.data(), view.size());
                    AssetNames.emplace_back(Strings::ToLower(Strings::Trim(assetName)), negate);
                }
            }

            currentStart = currentIndex;
            valueStart = 0;
        }
        else if (nextChar == ':')
        {
            valueStart = currentIndex;
        }
    }
}

BEGIN_MESSAGE_MAP(MainWindow, WraithWindow)
    ON_COMMAND(IDC_LOADGAME, OnLoadGame)
    ON_COMMAND(IDC_LOADFILE, OnLoadFile)
    ON_COMMAND(IDC_CLEARALL, OnClearAll)
    ON_COMMAND(IDC_EXPORTALL, OnExportAll)
    ON_COMMAND(IDC_EXPORT_JSON_MODELS, OnExportJsonModels)
    ON_COMMAND(IDC_EXPORT_PLACEMENTS, OnExportPlacements)
    ON_COMMAND(IDC_EXPORT_BRUSHES, OnExportBrushes)
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

// -- Hashing Functions for BO4 --

const uint64_t FNVPrime = 0x100000001B3;
const uint64_t FNVOffset = 0xCBF29CE484222325;

// Generates a 64bit FNV Hash for the given string
uint64_t FNVHash(std::string data, const uint64_t fnvPrime, const uint64_t fnvOffset)
{
    uint64_t Result = fnvOffset;

    for (uint32_t i = 0; i < data.length(); i++)
    {
        Result ^= data[i];
        Result *= fnvPrime;
    }

    return Result & 0xFFFFFFFFFFFFFFF;
}

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
                this->PopupDialog->ShowPopup(Strings::Format("%s was exported", AssetName.c_str()).c_str(), FileSystems::CombinePath(FileSystems::GetApplicationPath(), "exported_files").c_str(), 6000);
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
    std::thread LoadAsync([this]
    {
        // Run it
        this->LoadGameAsync();
    });

    // Detatch
    LoadAsync.detach();
}

void MainWindow::LoadGameAsync()
{
    // Prepare to load the game, and report back if need be
    auto LoadGameResult = CoDAssets::BeginGameMode();

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
    // Show the settings dialog
    SettingsWindow SettingsDialog(this);
    // Show it
    const auto Action = SettingsDialog.DoModal();
    if (Action == IDC_EXPORT_PLACEMENTS || Action == IDC_EXPORT_JSON_MODELS || Action == IDC_EXPORT_BRUSHES)
        PostMessage(WM_COMMAND, Action);
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
            this->PopupDialog->ShowPopup("Bulk export has finished", FileSystems::CombinePath(FileSystems::GetApplicationPath(), "exported_files").c_str(), 6000);
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
                this->PopupDialog->ShowPopup("Bulk export has finished", FileSystems::CombinePath(FileSystems::GetApplicationPath(), "exported_files").c_str(), 6000);
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
    // Prepare to load the file, and report back if need be
    auto LoadFileResult = CoDAssets::BeginGameFileMode(FilePath);

    // Check if we had success
    if (LoadFileResult == LoadGameFileResult::Success)
    {
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
        // Create Context
        SearchContext Context(SearchText);

        // Iterate and append what we find
        for (auto& Asset : CoDAssets::GameAssets->LoadedAssets)
        {
            // Grab the string
            std::string AssetName = Asset->AssetName;
            // Make it lowercase
            std::transform(AssetName.begin(), AssetName.end(), AssetName.begin(), ::tolower);

            // Whether or not we can add
            bool CanAdd = true;

            // Check type and format it
            switch (Asset->AssetType)
            {
            case WraithAssetType::Model:
            {
                auto XModelBoneCount = (int64_t)((CoDModel_t*)Asset)->BoneCount;
                auto XModelLodCount = (int64_t)((CoDModel_t*)Asset)->LodCount;
                auto XModelBoneNames = ((CoDModel_t*)Asset)->BoneNames;

                if (Context.BoneCount.Value != -1 && XModelBoneCount != Context.BoneCount.Value)
                    CanAdd = false;
                if (XModelBoneCount < Context.BoneCount.Min)
                    CanAdd = false;
                if (XModelBoneCount > Context.BoneCount.Max)
                    CanAdd = false;

                if (Context.LodCount.Value != -1 && XModelLodCount != Context.LodCount.Value)
                    CanAdd = false;
                if (XModelLodCount < Context.LodCount.Min)
                    CanAdd = false;
                if (XModelLodCount > Context.LodCount.Max)
                    CanAdd = false;

                if (!Context.BoneNames.empty())
                {
                    bool XModelBoneMatch = false;

                    for (auto& BoneName : Context.BoneNames)
                    {
                        for (auto& XModelBoneName : XModelBoneNames)
                        {
                            // If we match, add, then stop
                            auto Result = XModelBoneName.find(BoneName.Value);
                            // Check match type
                            if (Result != std::string::npos)
                            {
                                XModelBoneMatch = true;
                                break;
                            }
                        }
                    }

                    if (!XModelBoneMatch)
                        CanAdd = false;
                }

                break;
            }
            case WraithAssetType::Animation:
            {
                auto XAnimBoneCount = (int64_t)((CoDAnim_t*)Asset)->BoneCount;
                auto XAnimFrameCount = (int64_t)((CoDAnim_t*)Asset)->FrameCount;
                auto XAnimShapeCount = (int64_t)((CoDAnim_t*)Asset)->ShapeCount;
                auto XAnimFrameRate = ((CoDAnim_t*)Asset)->Framerate;
                auto XAnimBoneNames = ((CoDAnim_t*)Asset)->BoneNames;

                if (Context.BoneCount.Value != -1 && XAnimBoneCount != Context.BoneCount.Value)
                    CanAdd = false;
                if (XAnimBoneCount < Context.BoneCount.Min)
                    CanAdd = false;
                if (XAnimBoneCount > Context.BoneCount.Max)
                    CanAdd = false;

                if (Context.ShapeCount.Value != -1 && XAnimShapeCount != Context.ShapeCount.Value)
                    CanAdd = false;
                if (XAnimShapeCount < Context.ShapeCount.Min)
                    CanAdd = false;
                if (XAnimShapeCount > Context.ShapeCount.Max)
                    CanAdd = false;

                if (Context.FrameCount.Value != -1 && XAnimFrameCount != Context.FrameCount.Value)
                    CanAdd = false;
                if (XAnimFrameCount < Context.FrameCount.Min)
                    CanAdd = false;
                if (XAnimFrameCount > Context.FrameCount.Max)
                    CanAdd = false;

                if (Context.Framerate.Value != -1 && XAnimFrameRate != Context.Framerate.Value)
                    CanAdd = false;
                if (XAnimFrameRate < Context.Framerate.Min)
                    CanAdd = false;
                if (XAnimFrameRate > Context.Framerate.Max)
                    CanAdd = false;

                if (!Context.BoneNames.empty())
                {
                    bool XModelBoneMatch = false;

                    for (auto& XAnimBoneName : XAnimBoneNames)
                    {
                        for (auto& BoneName : Context.BoneNames)
                        {
                            // If we match, add, then stop
                            auto Result = XAnimBoneName.find(BoneName.Value);
                            // Check match type
                            if (Result != std::string::npos)
                            {
                                XModelBoneMatch = true;
                                break;
                            }
                        }
                    }

                    if (!XModelBoneMatch)
                        CanAdd = false;
                }

                break;
            }
            case WraithAssetType::Image:
            {
                auto ImageWidth = (int64_t)((CoDImage_t*)Asset)->Width;
                auto ImageHeight = (int64_t)((CoDImage_t*)Asset)->Height;

                if (Context.Width.Value != -1 && ImageWidth != Context.Width.Value)
                    CanAdd = false;
                if (ImageWidth < Context.Width.Min)
                    CanAdd = false;
                if (ImageWidth > Context.Width.Max)
                    CanAdd = false;

                if (Context.Height.Value != -1 && ImageHeight != Context.Height.Value)
                    CanAdd = false;
                if (ImageHeight < Context.Height.Min)
                    CanAdd = false;
                if (ImageHeight > Context.Height.Max)
                    CanAdd = false;

                break;
            }
            case WraithAssetType::Sound:
            {
                auto SoundLength = (int64_t)((CoDSound_t*)Asset)->Length;

                if (Context.SoundLength.Value != -1 && SoundLength != Context.SoundLength.Value)
                    CanAdd = false;
                if (SoundLength < Context.SoundLength.Min)
                    CanAdd = false;
                if (SoundLength > Context.SoundLength.Max)
                    CanAdd = false;

                break;
            }
            }

            if (Context.Streamed.Value != -1)
                CanAdd = (Context.Streamed.Value == 1 && Asset->Streamed) || (Context.Streamed.Value == 0 && !Asset->Streamed);
            if (Context.Placeholder.Value != -1)
                CanAdd = (Context.Placeholder.Value == 1 && Asset->AssetStatus == WraithAssetStatus::Placeholder) || (Context.Placeholder.Value == 0 && Asset->AssetStatus != WraithAssetStatus::Placeholder);


            // At this point we've checked out with value checks, skip names
            // if other values haven't checked
            if (!CanAdd)
                continue;

            bool AssetNameMatch = true;

            for (auto& MapFind : Context.AssetNames)
            {
                // If we match, add, then stop
                auto Result = AssetName.find(MapFind.Value);

                // Check match type
                if (Result == std::string::npos && MapFind.Negate)
                {
                    AssetNameMatch = true;
                    break;
                }
                if (Result == std::string::npos && !MapFind.Negate)
                {
                    AssetNameMatch = false;
                }
                else
                {
                    AssetNameMatch = true;
                    break;
                }

                // Second pass for Bo4, hash
                if (CoDAssets::GameID == SupportedGames::BlackOps4 || CoDAssets::GameID == SupportedGames::BlackOpsCW)
                {
                    // Convert to hex string
                    std::stringstream HashValue;
                    HashValue << std::hex << FNVHash(MapFind.Value, FNVPrime, FNVOffset) << std::dec;

                    // If we match, add, then stop
                    Result = AssetName.find(HashValue.str());
                    
                    // Check match type
                    if (Result == std::string::npos && MapFind.Negate)
                    {
                        AssetNameMatch = true;
                        break;
                    }
                    if (Result == std::string::npos && !MapFind.Negate)
                    {
                        AssetNameMatch = false;
                    }
                    else
                    {
                        AssetNameMatch = true;
                        break;
                    }
                }
                // Second pass for Bo4, hash
                else if (CoDAssets::GameID == SupportedGames::ModernWarfare5 || CoDAssets::GameID == SupportedGames::ModernWarfare6)
                {
                    // Convert to hex string
                    std::stringstream HashValue;
                    HashValue << std::hex << FNVHash(MapFind.Value, 0x100000001B3, 0x47F5817A5EF961BA) << std::dec;

                    // If we match, add, then stop
                    Result = AssetName.find(HashValue.str());

                    // Check match type
                    if (Result == std::string::npos && MapFind.Negate)
                    {
                        AssetNameMatch = true;
                        break;
                    }
                    if (Result == std::string::npos && !MapFind.Negate)
                    {
                        AssetNameMatch = false;
                    }
                    else
                    {
                        AssetNameMatch = true;
                        break;
                    }
                }
            }

            if (!AssetNameMatch)
                CanAdd = false;

            // Check to add
            if (CanAdd)
            {
                SearchResults.push_back(Asset);
            }
        }

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

void MainWindow::OnExportJsonModels()
{
    if (CoDAssets::GameID != SupportedGames::BlackOpsCW) { MessageBoxA(GetSafeHwnd(),"Models from JSON currently supports Cold War CAST exports only.","Models from JSON",MB_OK); return; }
    if (!CoDAssets::GameAssets) { MessageBoxA(GetSafeHwnd(),"Load Game with XModels enabled first.","Models from JSON",MB_OK); return; }
    auto File=WraithFileDialogs::OpenFileDialog("Select static_models.json", "", "JSON (*.json)|*.json;",GetSafeHwnd());
    if (File.empty()) return;
    using json=nlohmann::json;
    std::set<std::string> Names;
    json PlacementRows;
    ModelExportNaming::SourceLookup Lookup;
    for (const auto* Asset : CoDAssets::GameAssets->LoadedAssets)
        if (Asset->AssetType == WraithAssetType::Model) Lookup.Add(Asset->AssetName);
    try
    {
        std::ifstream Input(File); json Doc; Input>>Doc;
        const auto& Rows=Doc.is_array()?Doc:Doc.at("StaticModels");
        if (!Rows.is_array()) throw std::runtime_error("StaticModels must be an array");
        PlacementRows = Rows;
        for(const auto& Row:Rows)
        {
            const auto Name=Row.at("Name").get<std::string>();
            if(!Name.empty()) Names.insert(Lookup.Resolve(Name,Row.value("SourceName",std::string())));
        }
        if(Names.empty()) throw std::runtime_error("No model names found");
        for (auto& Row : PlacementRows)
        {
            Row["SourceName"] = Lookup.Resolve(Row.at("Name").get<std::string>(), Row.value("SourceName",std::string()));
            ModelExportNaming::PublishPlacementName(Row);
        }
    }
    catch(const std::exception& E) { MessageBoxA(GetSafeHwnd(),(std::string("Select placement static_models.json, not spline-input JSON.\n")+E.what()).c_str(),"Models from JSON",MB_OK|MB_ICONERROR); return; }
    struct ModelRequest
    {
        std::string Name;
        std::vector<CoDAsset_t*> Candidates;
        size_t Selected;
    };
    std::vector<ModelRequest> Queue;
    size_t DuplicateNames = 0;
    for(const auto& Name:Names)
    {
        ModelRequest Request{Name, {}, (std::numeric_limits<size_t>::max)()};
        std::vector<ModelBatchSelection::Candidate> Selection;
        for(auto* Asset:CoDAssets::GameAssets->LoadedAssets)
            if(Asset->AssetType==WraithAssetType::Model && Asset->AssetName==Name)
            {
                const auto State = Asset->AssetStatus;
                const bool Usable = State != WraithAssetStatus::Placeholder &&
                    State != WraithAssetStatus::NotLoaded && State != WraithAssetStatus::Processing;
                Selection.push_back({Asset->AssetPointer, Request.Candidates.size(), Usable,
                    State == WraithAssetStatus::Exported, State == WraithAssetStatus::Loaded});
                Request.Candidates.push_back(Asset);
            }
        Request.Selected = ModelBatchSelection::Select(Selection);
        if (Request.Candidates.size() > 1) ++DuplicateNames;
        Queue.push_back(std::move(Request));
    }
    auto BatchRoot = FileSystems::CombinePath(FileSystems::GetApplicationPath(),
        "exported_files/models_from_json_" + std::to_string(GetTickCount64()));
    bool Resume = false;
    const auto ExistingRoot = FileSystems::GetDirectoryName(File);
    if (FileSystems::FileExists(FileSystems::CombinePath(ExistingRoot,"model_identities.json")) &&
        FileSystems::DirectoryExists(FileSystems::CombinePath(ExistingRoot,"models")))
    {
        const auto Choice = MessageBoxA(GetSafeHwnd(),
            "This JSON belongs to an existing model export. Resume in that folder?\n\nYes: keep completed models and retry unfinished ones.\nNo: create a new export.\nCancel: do nothing.",
            "Resume models from JSON", MB_YESNOCANCEL | MB_ICONQUESTION);
        if (Choice == IDCANCEL) return;
        Resume = Choice == IDYES;
        if (Resume) BatchRoot = ExistingRoot;
    }
    for (const auto* Folder : {"models", "materials", "images"})
        FileSystems::CreateDirectory(FileSystems::CombinePath(BatchRoot, Folder));
    if (!Resume)
    {
        std::ofstream PlacementOutput(FileSystems::CombinePath(BatchRoot, "static_models.json"), std::ios::binary);
        PlacementOutput << PlacementRows.dump(2); PlacementOutput.close();
        if (!PlacementOutput) { MessageBoxA(GetSafeHwnd(),"Could not create JSON batch output.","Models from JSON",MB_OK|MB_ICONERROR); return; }
    }
    json Options=json::object(), Identities=json::object(), CompletedModels=json::object();
    for (const auto* Key : {"exportalllods","match_game_lod_index","exportmodelimg","exportimg","exportimgnames","exportvtxcolor","exporthitbox","patchcolor","patchnormals"})
        Options[Key]=SettingsManager::GetSetting(Key);
    const auto CheckpointPath=FileSystems::CombinePath(BatchRoot,"model_export_checkpoint.json");
    bool LegacySingleLod=Resume && !FileSystems::FileExists(CheckpointPath) &&
        Options["exportalllods"]!="true" && Options["match_game_lod_index"]!="true";
    try
    {
        if (Resume)
        {
            std::ifstream IdFile(FileSystems::CombinePath(BatchRoot,"model_identities.json")); IdFile>>Identities;
            if (FileSystems::FileExists(CheckpointPath))
            {
                json Checkpoint; std::ifstream Input(CheckpointPath); Input>>Checkpoint;
                if (Checkpoint.at("options")==Options)
                {
                    CompletedModels=Checkpoint.at("completed_models");
                    LegacySingleLod=Checkpoint.value("legacy_single_lod",false);
                }
            }
        }
    }
    catch (const std::exception& E) { MessageBoxA(GetSafeHwnd(), E.what(), "Could not read resume metadata", MB_OK|MB_ICONERROR); return; }
    ProgressDialog=std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG,this);
    ProgressDialog->SetupDialog("Greyhound | Cold War CAST from JSON","Preparing unique models...",true,true);
    ProgressDialog->OnCancelClick=CancelProgress; ProgressDialog->OnOkClick=FinishProgress;
    CoDAssets::CanExportContinue=true;
    std::thread Worker([this,Queue,File,DuplicateNames,BatchRoot,Resume,Options,Identities,CompletedModels,LegacySingleLod,CheckpointPath]() mutable
    {
        ProgressDialog->WaitTillReady(); ProgressDialog->UpdateWindowClose(false); ProgressDialog->UpdateButtons(false,true);
        json Results=json::array(); size_t Done=0,Success=0,Failed=0,Missing=0,Unavailable=0,Kept=0;
        bool CheckpointFailed=false;
        ProgressDialog->UpdateStatus("Waiting for model package cache...");
        if(CoDAssets::GamePackageCache) CoDAssets::GamePackageCache->WaitForPackageCacheLoad();
        Image::SetupConversionThread();
        for(const auto& Item:Queue)
        {
            if(!CoDAssets::CanExportContinue) break;
            ProgressDialog->UpdateStatus(("Completed "+std::to_string(Done)+" / "+std::to_string(Queue.size())+" unique models | "+ModelExportNaming::FileStem(Item.Name)).c_str());
            std::string Status,Error;
            json Candidates=json::array();
            for (size_t Index=0; Index<Item.Candidates.size(); ++Index)
            {
                const auto* Candidate=Item.Candidates[Index];
                Candidates.push_back({{"asset_pointer",Strings::Format("0x%llx",Candidate->AssetPointer)},
                    {"loaded_index",Candidate->AssetLoadedIndex}, {"status_before",int(Candidate->AssetStatus)},
                    {"selected",Index==Item.Selected}});
            }
            bool Keep=false;
            try { Keep=Resume && ModelBatchResume::Completed(BatchRoot,Item.Name,Identities,CompletedModels,LegacySingleLod); }
            catch (const std::exception&) { Keep=false; }
            if(Keep) {Status="kept_existing";++Kept;}
            else if(Item.Candidates.empty()) {Status="missing";++Missing;}
            else if(Item.Selected==(std::numeric_limits<size_t>::max)()) {Status="unavailable";++Unavailable;}
            else
            {
                try { auto R=CoDAssets::ExportJsonBatchModel(static_cast<const CoDModel_t*>(Item.Candidates[Item.Selected]),BatchRoot); Status=R==ExportGameResult::Success?"exported":"failed"; }
                catch(const std::exception& E) {Status="failed";Error=E.what();}
                if(Status=="exported") ++Success; else ++Failed;
            }
            Results.push_back({{"Name",ModelExportNaming::FileStem(Item.Name)},{"SourceName",Item.Name},
                {"output_directory",FileSystems::CombinePath(BatchRoot,"models")},
                {"status",Status},{"error",Error},
                {"candidate_count",Item.Candidates.size()},{"candidates",Candidates},
                {"selection_policy","prefer previously exported, then loaded, then other usable; address order breaks ties"},
                {"candidate_geometry_equivalence_verified",false}});
            if(Status=="exported" || Status=="kept_existing")
            {
                try
                {
                    auto Files=json::array();
                    if (Status=="kept_existing" && CompletedModels.contains(Item.Name)) Files=CompletedModels.at(Item.Name);
                    else if (Status=="kept_existing" && LegacySingleLod)
                    {
                        const auto File=ModelExportNaming::FileStem(Item.Name)+".cast";
                        Files.push_back({{"file",File},{"bytes",ModelBatchResume::FileSize(BatchRoot+"/models/"+File)}});
                    }
                    else Files=ModelBatchResume::Files(BatchRoot,Item.Name);
                    if (!Files.empty()) CompletedModels[Item.Name]=std::move(Files);
                }
                catch(const std::exception&) { CompletedModels.erase(Item.Name); }
            }
            // Persist after every model; replacement is atomic so a crash cannot
            // destroy the last usable checkpoint. The final report remains separate.
            try
            {
                std::ofstream Output(CheckpointPath+".tmp",std::ios::binary);
                Output<<json({{"schema","greyhound-model-resume-v1"},{"options",Options},{"legacy_single_lod",LegacySingleLod},{"completed_models",CompletedModels}}).dump(2);
                Output.close();
                if (!Output || !MoveFileExA((CheckpointPath+".tmp").c_str(),CheckpointPath.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)) CheckpointFailed=true;
            }
            catch(const std::exception&) { CheckpointFailed=true; }
            ++Done; ProgressDialog->UpdateProgress(uint32_t(100ull*Done/Queue.size()));
        }
        Image::DisableConversionThread();
        CoDAssets::LatestExportPath=BatchRoot;
        json Report={{"schema","greyhound-models-from-json-v3"},{"source",File},{"output_directory",BatchRoot},{"layout","flat_models_materials_images"},{"model_format","cast"},{"unique_models",Queue.size()},
            {"completed",Done},{"exported",Success},{"kept_existing",Kept},{"resumed",Resume},{"checkpoint_write_failed",CheckpointFailed},{"failed",Failed},{"missing",Missing},{"unavailable",Unavailable},
            {"duplicate_names",DuplicateNames},{"cancelled",Done<Queue.size()},{"models",Results}};
        std::string ReportPath=FileSystems::CombinePath(BatchRoot,"model_export_report.json"); std::ofstream Output(ReportPath); Output<<Report.dump(2); Output.close();
        std::string Summary=(Done<Queue.size()?"Cancelled: ":"Finished: ")+std::to_string(Done)+" / "+std::to_string(Queue.size())+"; kept "+std::to_string(Kept)+", exported "+std::to_string(Success)+", failed "+std::to_string(Failed)+", missing "+std::to_string(Missing)+", unavailable "+std::to_string(Unavailable)+", duplicate names "+std::to_string(DuplicateNames);
        if(CheckpointFailed) Summary+="; checkpoint could not be saved";
        if(!Output) Summary+="; report could not be saved";
        Summary+=" | Output: "+BatchRoot;
        ProgressDialog->UpdateStatus(Summary.c_str()); ProgressDialog->UpdateWindowClose(true);ProgressDialog->UpdateButtons(true,false);
    });
    Worker.detach(); ProgressDialog->DoModal();
}

void MainWindow::OnExportPlacements()
{
    ProgressDialog=std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG,this);
    ProgressDialog->SetupDialog("Greyhound | Model placements","Reading placement districts...",true,false);
    ProgressDialog->OnOkClick=FinishProgress;
    std::thread Worker([this]
    {
        ProgressDialog->WaitTillReady(); ProgressDialog->UpdateWindowClose(false); ProgressDialog->UpdateButtons(false,false);
        const auto Directory=FileSystems::CombinePath(FileSystems::GetApplicationPath(),"exported_files/model_placements_"+std::to_string(GetTickCount64()));
        std::string Status;
        try { Status=GameBlackOpsCW::ExportModelPlacements(Directory,[this](uint32_t P){ProgressDialog->UpdateProgress(P);}); }
        catch(const std::exception& E) {Status=std::string("Placement export failed: ")+E.what();}
        CoDAssets::LatestExportPath=Directory;
        ProgressDialog->UpdateStatus(Status.c_str()); ProgressDialog->UpdateWindowClose(true);ProgressDialog->UpdateButtons(true,false);
    });
    Worker.detach(); ProgressDialog->DoModal();
}

void MainWindow::OnExportBrushes()
{
    ProgressDialog=std::make_unique<WraithProgressDialog>(IDD_PROGRESSDIALOG,this);
    ProgressDialog->SetupDialog("Greyhound | CW Radiant Brushes","Capturing verified brush data...",true,false);
    ProgressDialog->OnOkClick=FinishProgress;
    std::thread Worker([this]
    {
        ProgressDialog->WaitTillReady();ProgressDialog->UpdateWindowClose(false);ProgressDialog->UpdateButtons(false,false);
        SYSTEMTIME Time{};GetLocalTime(&Time);
        const auto Directory=FileSystems::CombinePath(FileSystems::GetApplicationPath(),Strings::Format("exported_files/CW_Radiant_%04u-%02u-%02u_%02u-%02u-%02u_%03u",
            Time.wYear,Time.wMonth,Time.wDay,Time.wHour,Time.wMinute,Time.wSecond,Time.wMilliseconds));
        std::string Status;
        try {Status=GameBlackOpsCW::ExportRadiantBrushes(Directory,[this](uint32_t P,const std::string& Stage){ProgressDialog->UpdateProgress(P);ProgressDialog->UpdateStatus(Stage.c_str());});}
        catch(const std::exception& E){Status=std::string("Brush export failed: ")+E.what();}
        ProgressDialog->UpdateStatus(Status.c_str());ProgressDialog->UpdateWindowClose(true);ProgressDialog->UpdateButtons(true,false);
    });
    Worker.detach();ProgressDialog->DoModal();
}
