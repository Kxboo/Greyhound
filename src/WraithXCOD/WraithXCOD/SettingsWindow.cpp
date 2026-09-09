#include "stdafx.h"

// The class we are implementing
#include "SettingsWindow.h"
#include <algorithm>

// We need the Wraith theme and settings classes
#include "WraithTheme.h"
#include "SettingsManager.h"

// We need the panels
#include "GeneralSettings.h"
#include "ModelSettings.h"
#include "AnimSettings.h"
#include "ImageSettings.h"
#include "SoundSettings.h"
#include "TerrainSettings.h"

// We need the following Wraith classes
#include "Strings.h"

BEGIN_MESSAGE_MAP(SettingsWindow, WraithWindow)
    ON_COMMAND(IDC_EXPORT_PLACEMENTS, OnExportPlacements)
    ON_COMMAND(IDC_EXPORT_JSON_MODELS, OnExportJsonModels)
    ON_COMMAND(IDC_EXPORT_BRUSHES, OnExportBrushes)
    ON_WM_PAINT()
    ON_WM_SIZE()
    ON_COMMAND(IDC_GENERALPANEL, OnGeneralPage)
    ON_COMMAND(IDC_MODELPANEL, OnModelsPage)
    ON_COMMAND(IDC_ANIMPANEL, OnAnimsPage)
    ON_COMMAND(IDC_IMAGEPANEL, OnImagesPage)
    ON_COMMAND(IDC_SOUNDPANEL, OnSoundsPage)
    ON_COMMAND(IDC_TERRAINPANEL, OnTerrainsPage)
    ON_COMMAND(IDC_CW_MAP_PANEL, OnCWMapPage)
    ON_COMMAND(IDC_CW_RESEARCH_PANEL, OnCWResearchPage)
    ON_COMMAND(IDC_CW_RADIANT_PANEL, OnCWRadiantPage)
END_MESSAGE_MAP()

void SettingsWindow::DoDataExchange(CDataExchange* pDX)
{
    // Handle base
    WraithWindow::DoDataExchange(pDX);
    // Map our buttons properly
    DDX_Control(pDX, IDC_GENERALPANEL, GeneralButton);
    DDX_Control(pDX, IDC_MODELPANEL, ModelButton);
    DDX_Control(pDX, IDC_ANIMPANEL, AnimButton);
    DDX_Control(pDX, IDC_IMAGEPANEL, ImageButton);
    DDX_Control(pDX, IDC_SOUNDPANEL, SoundButton);
    DDX_Control(pDX, IDC_TERRAINPANEL, TerrainButton);
    DDX_Control(pDX, IDC_CW_MAP_PANEL, CWMapButton);
    DDX_Control(pDX, IDC_CW_RESEARCH_PANEL, CWResearchButton);
    DDX_Control(pDX, IDC_CW_RADIANT_PANEL, CWRadiantButton);
}

void SettingsWindow::OnBeforeLoad()
{
    // Dialog units track the actual dialog font rather than assuming pixel sizes.
    CRect Sidebar(0, 0, 117, 0);
    MapDialogRect(&Sidebar);
    SidebarWidth = Sidebar.right;
    CRect Minimum(0, 0, 350, 260);
    MapDialogRect(&Minimum);
    Minimum.right += SidebarWidth + 1;
    AdjustWindowRectEx(&Minimum, GetStyle(), FALSE, GetExStyle());
    MinimumWidth = Minimum.Width();
    MinimumHeight = Minimum.Height();

    // Adjust controls
    ShiftControl(IDC_SOUNDPANEL, CRect(0, -1, 0, 0));
    ShiftControl(IDC_TERRAINPANEL, CRect(0, -1, 0, 0));
}

void SettingsWindow::OnLoad()
{
    // Setup default panel
    CRect Size;
    // Fetch
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<GeneralSettings>();
    SettingsPanel->Create(IDD_GENERALSETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);
    // Set button
    this->GeneralButton.SetSelectedState(true);
}

void SettingsWindow::OnPaint()
{
    // Make a paint context
    CPaintDC dc(this);

    // Get client size
    CRect Size;
    // Fetch
    this->GetClientRect(&Size);
    // Fill the color
    dc.FillRect(CRect(0, 0, SidebarWidth, Size.bottom), &CBrush(RGB(42, 42, 42)));

    // Draw rest
    WraithWindow::OnPaint();
}

void SettingsWindow::SetUnselected()
{
    // Set them
    this->GeneralButton.SetSelectedState(false);
    this->ModelButton.SetSelectedState(false);
    this->AnimButton.SetSelectedState(false);
    this->ImageButton.SetSelectedState(false);
    this->SoundButton.SetSelectedState(false);
    this->TerrainButton.SetSelectedState(false);
    CWMapButton.SetSelectedState(false);
    CWResearchButton.SetSelectedState(false);
    CWRadiantButton.SetSelectedState(false);
}

void SettingsWindow::OnGeneralPage()
{
    // Clean up current
    if (SettingsPanel != nullptr)
    {
        SettingsPanel->DestroyWindow();
        SettingsPanel.reset();
    }

    // -- General

    CRect Size;
    // Fetch
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<GeneralSettings>();
    SettingsPanel->Create(IDD_GENERALSETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);

    this->SetUnselected();
    this->GeneralButton.SetSelectedState(true);
}

void SettingsWindow::OnModelsPage()
{
    // Clean up current
    if (SettingsPanel != nullptr)
    {
        SettingsPanel->DestroyWindow();
        SettingsPanel.reset();
    }

    // -- Models

    CRect Size;
    // Fetch
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<ModelSettings>();
    SettingsPanel->Create(IDD_MODELSETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);

    this->SetUnselected();
    this->ModelButton.SetSelectedState(true);
}

void SettingsWindow::OnAnimsPage()
{
    // Clean up current
    if (SettingsPanel != nullptr)
    {
        SettingsPanel->DestroyWindow();
        SettingsPanel.reset();
    }

    // -- Models

    CRect Size;
    // Fetch
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<AnimSettings>();
    SettingsPanel->Create(IDD_ANIMSETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);

    this->SetUnselected();
    this->AnimButton.SetSelectedState(true);
}

void SettingsWindow::OnImagesPage()
{
    // Clean up current
    if (SettingsPanel != nullptr)
    {
        SettingsPanel->DestroyWindow();
        SettingsPanel.reset();
    }

    // -- Models

    CRect Size;
    // Fetch
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<ImageSettings>();
    SettingsPanel->Create(IDD_IMAGESETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);

    this->SetUnselected();
    this->ImageButton.SetSelectedState(true);
}

void SettingsWindow::OnSoundsPage()
{
    // Clean up current
    if (SettingsPanel != nullptr)
    {
        SettingsPanel->DestroyWindow();
        SettingsPanel.reset();
    }

    // -- Models

    CRect Size;
    // Fetch
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<SoundSettings>();
    SettingsPanel->Create(IDD_SOUNDSETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);

    this->SetUnselected();
    this->SoundButton.SetSelectedState(true);
}

void SettingsWindow::OnTerrainsPage()
{
    if (SettingsPanel != nullptr)
    {
        SettingsPanel->DestroyWindow();
        SettingsPanel.reset();
    }

    CRect Size;
    this->GetClientRect(&Size);

    SettingsPanel = std::make_unique<TerrainSettings>();
    SettingsPanel->Create(IDD_TERRAINSETTINGS, this);
    LayoutPanel();
    SettingsPanel->ShowWindow(SW_SHOW);

    this->SetUnselected();
    this->TerrainButton.SetSelectedState(true);
}

void SettingsWindow::OnCWMapPage() { ShowCWPage(1); }
void SettingsWindow::OnCWResearchPage() { ShowCWPage(2); }
void SettingsWindow::OnCWRadiantPage() { ShowCWPage(3); }
void SettingsWindow::ShowCWPage(int Page)
{
    if (SettingsPanel) { SettingsPanel->DestroyWindow(); SettingsPanel.reset(); }
    SettingsPanel = std::make_unique<GeneralSettings>(nullptr, Page);
    SettingsPanel->Create(IDD_GENERALSETTINGS, this);
    LayoutPanel(); SettingsPanel->ShowWindow(SW_SHOW); SetUnselected();
    if (Page==1) CWMapButton.SetSelectedState(true);
    else if(Page==2) CWResearchButton.SetSelectedState(true);
    else CWRadiantButton.SetSelectedState(true);
}

void SettingsWindow::LayoutPanel()
{
    if (!SettingsPanel || !SettingsPanel->GetSafeHwnd()) return;
    CRect Client;
    GetClientRect(&Client);
    SettingsPanel->MoveWindow(SidebarWidth, 0,
        std::max(0, Client.Width() - SidebarWidth - 1), std::max(0, Client.Height()));
}

void SettingsWindow::OnSize(UINT nType, int cx, int cy)
{
    WraithWindow::OnSize(nType, cx, cy);
    if (nType != SIZE_MINIMIZED) LayoutPanel();
}

void SettingsWindow::OnExportPlacements() { EndDialog(IDC_EXPORT_PLACEMENTS); }
void SettingsWindow::OnExportJsonModels() { EndDialog(IDC_EXPORT_JSON_MODELS); }
void SettingsWindow::OnExportBrushes() { EndDialog(IDC_EXPORT_BRUSHES); }
