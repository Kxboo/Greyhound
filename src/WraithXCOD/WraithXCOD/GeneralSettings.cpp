#include "stdafx.h"

// The class we are implementing
#include "GeneralSettings.h"

// We need the Wraith theme and settings classes
#include "WraithTheme.h"
#include "SettingsManager.h"
#include "BO4NameDatabase.h"
#include "BO4CaptureModes.h"
#include "CoDAssets.h"

// We need the following Wraith classes
#include "Strings.h"

BEGIN_MESSAGE_MAP(GeneralSettings, WraithWindow)
    ON_CBN_SELENDOK(IDC_DEV_SECTION, OnDevSection)
    ON_CBN_SELENDOK(IDC_BO4_CAPTURE_MODE, OnBO4DiagnosticMode)
    ON_COMMAND(IDC_DEV_BO4_RUN, OnRunBO4Diagnostic)
    ON_COMMAND(IDC_DEV_VERIFY_RUNTIME, OnVerifyRuntime)
    ON_COMMAND(IDC_DEV_VERIFY_EXPORT, OnVerifyExport)
    ON_COMMAND(IDC_DEV_TERRAIN_SETTINGS, OnTerrainSettings)
    ON_COMMAND(IDC_SHOWXMODEL, OnXModels)
    ON_COMMAND(IDC_SHOWXANIM, OnXAnims)
    ON_COMMAND(IDC_SHOWXIMAGE, OnXImages)
    ON_COMMAND(IDC_SHOWXRAW, OnXRawFiles)
    ON_COMMAND(IDC_SHOWXSOUNDS, OnXSounds)
    ON_COMMAND(IDC_SHOWXMTL, OnXMTL)
    ON_COMMAND(IDC_CW_RADIANT_ENABLE, OnCWRadiantEnable)
    ON_COMMAND(IDC_CW_RADIANT_TYPES, OnCWRadiantOptions)
    ON_COMMAND(IDC_CW_RADIANT_VOLUMES, OnCWRadiantOptions)
    ON_COMMAND(IDC_EXPORT_BRUSHES, OnExportBrushes)
    ON_COMMAND(IDC_EXPORT_PLACEMENTS, OnExportPlacements)
    ON_COMMAND(IDC_CW_NONSTATIC_PLACEMENTS, OnNonStaticPlacements)
    ON_COMMAND(IDC_CW_PROXY_FILTER, OnPlacementOptions)
    ON_COMMAND(IDC_CW_ORGANIZE_PLACEMENTS, OnPlacementOptions)
    ON_COMMAND(IDC_CW_VERIFY_PLACEMENTS, OnPlacementOptions)
    ON_COMMAND(IDC_CW_FLOAT_TRIANGLES, OnCollisionCoverage)
    ON_COMMAND(IDC_CW_MODEL_TRIANGLES, OnCollisionCoverage)
    ON_COMMAND(IDC_EXPORT_JSON_MODELS, OnExportJsonModels)
    ON_COMMAND(IDC_EXPORT_SPLINE_MODELS, OnExportSplineModels)
    ON_COMMAND(IDC_CW_CLIP, OnCWCLIP)
    ON_COMMAND(IDC_CW_WORLD, OnCWWORLD)
    ON_COMMAND(IDC_CW_NAV, OnCWNAV)
    ON_COMMAND(IDC_CW_FX, OnCWFX)
    ON_COMMAND(IDC_CW_ENTITY, OnCWENTITY)
    ON_COMMAND(IDC_CW_TRIGGER, OnCWTRIGGER)
    ON_COMMAND(IDC_CW_AI, OnCWAI)
    ON_COMMAND(IDC_CW_CAPTURE_ENTITIES, OnCWCaptureOptions)
    ON_COMMAND(IDC_CW_CAPTURE_PLACEMENTS, OnCWCaptureOptions)
    ON_COMMAND(IDC_CW_CAPTURE_COLLISION, OnCWCaptureOptions)
    ON_COMMAND(IDC_CW_CAPTURE_SPLINES, OnCWCaptureOptions)
    ON_COMMAND(IDC_CW_CODE_PROBE, OnCWCaptureOptions)
    ON_CBN_SELENDOK(IDC_CW_EXPORT_MODE, OnCWExportMode)
    ON_CBN_SELENDOK(IDC_ASSET_SORT_METHOD, OnAssetSortMethod)
    ON_CBN_SELENDOK(IDC_BO4_NAME_DATABASE, OnBO4NameDatabase)
END_MESSAGE_MAP()

void GeneralSettings::OnBeforeLoad()
{
    // Make it
    TitleFont.CreateFont(20,           // Height
        0,                             // Width
        0,                             // Escapement
        0,                             // Orientation
        FW_NORMAL,                     // Weight
        FALSE,                         // Italic
        FALSE,                         // Underline
        0,                             // StrikeOut
        ANSI_CHARSET,                  // CharSet
        OUT_DEFAULT_PRECIS,            // OutPrecision
        CLIP_DEFAULT_PRECIS,           // ClipPrecision
        DEFAULT_QUALITY,               // Quality
        DEFAULT_PITCH | FF_SWISS,      // PitchAndFamily
        L"Microsoft Sans Serif");       // Name

    // Set it
    GetDlgItem(IDC_TITLE)->SetFont(&TitleFont);

    // Set tip
    SetControlAnchor(IDC_TIP, 0, 100, 0, 0);
    SetControlAnchor(IDC_NOTICE, 0, 100, 0, 0);

    // Load up configuration
    ((CButton*)GetDlgItem(IDC_SHOWXMODEL))->SetCheck(SettingsManager::GetSetting("showxmodel", "true") == "true");
    ((CButton*)GetDlgItem(IDC_SHOWXANIM))->SetCheck(SettingsManager::GetSetting("showxanim", "true") == "true");
    ((CButton*)GetDlgItem(IDC_SHOWXIMAGE))->SetCheck(SettingsManager::GetSetting("showximage", "false") == "true");
    ((CButton*)GetDlgItem(IDC_SHOWXRAW))->SetCheck(SettingsManager::GetSetting("showxrawfiles", "false") == "true");
    ((CButton*)GetDlgItem(IDC_SHOWXSOUNDS))->SetCheck(SettingsManager::GetSetting("showxsounds", "false") == "true");
    ((CButton*)GetDlgItem(IDC_SHOWXMTL))->SetCheck(SettingsManager::GetSetting("showxmtl", "false") == "true");

    ((CButton*)GetDlgItem(IDC_CW_CLIP))->SetCheck(SettingsManager::GetSetting("showcwcollision", "false") == "true");

    ((CButton*)GetDlgItem(IDC_CW_WORLD))->SetCheck(SettingsManager::GetSetting("showcwworld", "false") == "true");

    ((CButton*)GetDlgItem(IDC_CW_NAV))->SetCheck(SettingsManager::GetSetting("showcwnav", "false") == "true");

    ((CButton*)GetDlgItem(IDC_CW_FX))->SetCheck(SettingsManager::GetSetting("showcwfx", "false") == "true");

    ((CButton*)GetDlgItem(IDC_CW_ENTITY))->SetCheck(SettingsManager::GetSetting("showcwentities", "false") == "true");
    ((CButton*)GetDlgItem(IDC_CW_TRIGGER))->SetCheck(SettingsManager::GetSetting("showcwtriggers", "false") == "true");
    ((CButton*)GetDlgItem(IDC_CW_AI))->SetCheck(SettingsManager::GetSetting("showcwai", "false") == "true");
    auto CWMode=(CComboBox*)GetDlgItem(IDC_CW_EXPORT_MODE);
    CWMode->AddString(L"Headers only");
    CWMode->AddString(L"Map data + readback verification");
    CWMode->AddString(L"Probe referenced bytes");
    CWMode->AddString(L"Deep probe (experimental)");
    const bool Probe=SettingsManager::GetSetting("cwprobepayloads", "false")=="true";
    CWMode->SetCurSel(SettingsManager::GetSetting("cwmapdata", "false")=="true" ? 1 :
        Probe ? (SettingsManager::GetSetting("cwdeepProbe", "false")=="true" ? 3 : 2) : 0);
    ((CButton*)GetDlgItem(IDC_CW_CAPTURE_ENTITIES))->SetCheck(SettingsManager::GetSetting("cwcaptureentities", "true")=="true");
    ((CButton*)GetDlgItem(IDC_CW_CAPTURE_PLACEMENTS))->SetCheck(SettingsManager::GetSetting("cwcaptureplacements", "true")=="true");
    ((CButton*)GetDlgItem(IDC_CW_CAPTURE_COLLISION))->SetCheck(SettingsManager::GetSetting("cwcapturecollision", "true")=="true");
    ((CButton*)GetDlgItem(IDC_CW_CAPTURE_SPLINES))->SetCheck(SettingsManager::GetSetting("cwcapturesplines", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_CODE_PROBE))->SetCheck(SettingsManager::GetSetting("cwcollisioncodeprobe", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_RADIANT_ENABLE))->SetCheck(SettingsManager::GetSetting("cwradiantbrushes", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_RADIANT_TYPES))->SetCheck(SettingsManager::GetSetting("cwradianttypes", "true")=="true");
    ((CButton*)GetDlgItem(IDC_CW_RADIANT_VOLUMES))->SetCheck(SettingsManager::GetSetting("cwradiantvolumes", "true")=="true");
    auto Names=(CComboBox*)GetDlgItem(IDC_BO4_NAME_DATABASE);
    ((CButton*)GetDlgItem(IDC_CW_NONSTATIC_PLACEMENTS))->SetCheck(SettingsManager::GetSetting("cwnonstaticplacements", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_PROXY_FILTER))->SetCheck(SettingsManager::GetSetting("cwproxyfilter", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_ORGANIZE_PLACEMENTS))->SetCheck(SettingsManager::GetSetting("cworganizeplacements", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_VERIFY_PLACEMENTS))->SetCheck(SettingsManager::GetSetting("cwverifyplacements", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_FLOAT_TRIANGLES))->SetCheck(SettingsManager::GetSetting("cwfloattriangles", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_MODEL_TRIANGLES))->SetCheck(SettingsManager::GetSetting("cwmodeltriangles", "false")=="true");
    Names->AddString(L"Bundled Greyhound database");
    Names->AddString(L"echo000 / cod-name-db");
    Names->SetCurSel(SettingsManager::GetSetting("bo4namedatabase","bundled")=="echo000" ? 1 : 0);
    auto Sections=(CComboBox*)GetDlgItem(IDC_DEV_SECTION);
    for(const auto* Label:{L"Cold War: asset pool groups", L"Cold War: capture options",
                          L"Black Ops 4: diagnostic captures", L"Export workflows and checks"})
        Sections->AddString(Label);
    DevPage=CoDAssets::GameID==SupportedGames::BlackOps4 ? 2 : 0;
    Sections->SetCurSel(DevPage);
    auto BO4Modes=(CComboBox*)GetDlgItem(IDC_BO4_CAPTURE_MODE);
    for(const auto& Mode:BO4Diagnostics::BO4CaptureModes)BO4Modes->AddString(Mode.Label);
    const auto BO4Mode=SettingsManager::GetSetting("bo4capturemode","0");
    BO4Modes->SetCurSel(BO4Mode.size()==1 && BO4Mode[0]>='0' && BO4Mode[0]<='7' ? BO4Mode[0]-'0' : 0);
    UpdateCWExportHint();
    ConfigurePage();
    // Add sort methods
    auto ComboControl = (CComboBox*)GetDlgItem(IDC_ASSET_SORT_METHOD);
    // Add
    ComboControl->InsertString(0, L"Name");
    ComboControl->InsertString(1, L"Details");
    ComboControl->InsertString(2, L"None");

    // Sort settings
    auto ImageFormat = SettingsManager::GetSetting("assetsortmethod", "Name");
    // Apply
    if (ImageFormat == "Name") { ComboControl->SetCurSel(0); }
    if (ImageFormat == "Details") { ComboControl->SetCurSel(1); }
    if (ImageFormat == "None") { ComboControl->SetCurSel(2); }
}


void GeneralSettings::ConfigurePage()
{
    const int Standard[] = {IDC_SHOWXMODEL, IDC_SHOWXANIM, IDC_SHOWXIMAGE, IDC_SHOWXRAW,
        IDC_SHOWXSOUNDS, IDC_SHOWXMTL, IDC_ASSET_SORT_METHOD, IDC_STATICFORMAT2,
        IDC_BO4_NAME_DATABASE, IDC_BO4_NAME_DB_LABEL, IDC_BO4_NAME_DB_HINT};
    const int ColdWar[] = {IDC_CW_CLIP, IDC_CW_WORLD, IDC_CW_NAV, IDC_CW_FX,
        IDC_CW_ENTITY, IDC_CW_TRIGGER, IDC_CW_AI, IDC_CW_EXPORT_LABEL,
        IDC_CW_EXPORT_MODE, IDC_CW_EXPORT_HINT, IDC_CW_CAPTURE_ENTITIES,
        IDC_CW_CAPTURE_PLACEMENTS, IDC_CW_CAPTURE_COLLISION, IDC_CW_CAPTURE_SPLINES};
    for (int Id : {IDC_CW_RADIANT_ENABLE, IDC_EXPORT_BRUSHES, IDC_CW_RADIANT_INFO, IDC_CW_RADIANT_TYPES, IDC_CW_RADIANT_VOLUMES, IDC_CW_FLOAT_TRIANGLES, IDC_CW_MODEL_TRIANGLES}) GetDlgItem(Id)->ShowWindow(SW_HIDE);
    for (int Id : {IDC_EXPORT_PLACEMENTS,IDC_EXPORT_JSON_MODELS,IDC_EXPORT_SPLINE_MODELS,IDC_CW_PLACEMENT_INFO,IDC_CW_MODELS_INFO,IDC_CW_NONSTATIC_PLACEMENTS,IDC_CW_PROXY_FILTER,IDC_CW_ORGANIZE_PLACEMENTS,IDC_CW_VERIFY_PLACEMENTS}) GetDlgItem(Id)->ShowWindow(SW_HIDE);
    GetDlgItem(IDC_CW_CODE_PROBE)->ShowWindow(SW_HIDE);
    for(int Id:{IDC_DEV_SECTION,IDC_DEV_HEADING,IDC_DEV_DESCRIPTION,IDC_BO4_CAPTURE_MODE,
                IDC_DEV_BO4_RUN,IDC_DEV_VERIFY_RUNTIME,IDC_DEV_VERIFY_EXPORT,IDC_DEV_TERRAIN_SETTINGS})GetDlgItem(Id)->ShowWindow(SW_HIDE);
    for (int Id : Standard) GetDlgItem(Id)->ShowWindow(Page==0 ? SW_SHOW : SW_HIDE);
    for (int Id : ColdWar) GetDlgItem(Id)->ShowWindow(SW_HIDE);
    auto Place = [this](int Id, int X, int Y, int W, int H)
    {
        CRect Rect(X,Y,X+W,Y+H); MapDialogRect(&Rect);
        GetDlgItem(Id)->MoveWindow(Rect); GetDlgItem(Id)->ShowWindow(SW_SHOW);
    };
    GetDlgItem(IDC_TITLE)->SetWindowText(Page==0 ? L"In-game asset settings" :
        Page==1 ? L"Map & Model Export" : L"Dev Tools");
    if (Page==0)
    {
        GetDlgItem(IDC_NOTICE)->SetWindowText(L"Model placement JSON and batch exports: Map & Model Export. Diagnostics: Dev Tools.");
        GetDlgItem(IDC_TIP)->SetWindowText(L"Asset group and name database changes require Load Game.");
        return;
    }
    if(Page==1)
    {
        Place(IDC_EXPORT_PLACEMENTS,17,40,220,24);
        Place(IDC_CW_NONSTATIC_PLACEMENTS,17,68,310,12);
        Place(IDC_CW_PROXY_FILTER,17,82,310,12);
        Place(IDC_CW_ORGANIZE_PLACEMENTS,17,96,310,12);
        Place(IDC_CW_VERIFY_PLACEMENTS,17,110,310,12);
        UpdatePlacementOptions();
        Place(IDC_CW_PLACEMENT_INFO,17,124,310,34);
        GetDlgItem(IDC_CW_PLACEMENT_INFO)->SetWindowText(L"BO4 / CW: static_models.json. CW can also include entity classes, lights, probes and effects. Optional sorting creates a copy; verification checks captured bytes. Excluded proxies are recorded.");
        Place(IDC_EXPORT_JSON_MODELS,17,161,220,24);
        Place(IDC_EXPORT_SPLINE_MODELS,17,188,220,24);
        Place(IDC_CW_MODELS_INFO,17,215,310,16);
        GetDlgItem(IDC_CW_MODELS_INFO)->SetWindowText(L"Models from JSON: CAST. CW splines: selected model formats, with images and material info in each folder.");
        GetDlgItem(IDC_TIP)->SetWindowText(L"Load the matching map and Load Game first. Model and image settings apply to batch export.");
        GetDlgItem(IDC_NOTICE)->SetWindowText(L"Export all available LODs is respected. Brush prefabs are in Radiant Brushes.");
        return;
    }
    if(Page==3)
    {
        GetDlgItem(IDC_TITLE)->SetWindowText(L"Radiant Brushes");
        Place(IDC_CW_RADIANT_ENABLE,17,40,310,18);
        Place(IDC_CW_RADIANT_TYPES,17,60,310,14);
        Place(IDC_CW_RADIANT_VOLUMES,17,78,310,14);
        Place(IDC_CW_FLOAT_TRIANGLES,17,96,310,12);
        Place(IDC_CW_MODEL_TRIANGLES,17,110,310,12);
        Place(IDC_EXPORT_BRUSHES,17,128,155,22);
        Place(IDC_CW_RADIANT_INFO,17,158,310,70);
        GetDlgItem(IDC_CW_RADIANT_INFO)->SetWindowText(
            L"BO3 types come from the bundled catalogue. Differences and fallbacks are recorded in material_assignments.json.\r\n\r\n"
            L"Brushes, clips, volumes and triggers have separate prefabs. CW model clips use per-model .map files.\r\n\r\n"
            L"CW triangle output is OBJ reference geometry. BO4 triangle output is decoded JSON. Neither option creates triangle brushes.");
        GetDlgItem(IDC_TIP)->SetWindowText(L"Load a BO4 or CW map, then Export brushes now. Automatic collision-pool export applies to CW.");
        GetDlgItem(IDC_NOTICE)->SetWindowText(L"Exports to Greyhound's output folder. Does not create test maps or run BO3 compilation.");
        return;
    }
    Place(IDC_DEV_SECTION,17,32,310,85);
    Place(IDC_DEV_HEADING,17,59,310,12);
    Place(IDC_DEV_DESCRIPTION,17,168,310,58);
    GetDlgItem(IDC_TIP)->SetWindowText(L"Select a section above. Saved options apply to the matching game.");
    GetDlgItem(IDC_NOTICE)->SetWindowText(L"Capture reports distinguish verified data, candidates and unsupported layouts.");
    if(DevPage==0)
    {
        GetDlgItem(IDC_DEV_HEADING)->SetWindowText(L"Choose the Cold War pool rows to show");
        Place(IDC_CW_WORLD,17,80,155,12); Place(IDC_CW_NAV,180,80,147,12);
        Place(IDC_CW_CLIP,17,98,310,12);
        Place(IDC_CW_ENTITY,17,116,155,12); Place(IDC_CW_TRIGGER,180,116,147,12);
        Place(IDC_CW_FX,17,134,155,12); Place(IDC_CW_AI,180,134,147,12);
        GetDlgItem(IDC_CW_WORLD)->SetWindowText(L"Map worlds");
        GetDlgItem(IDC_CW_NAV)->SetWindowText(L"Navigation");
        GetDlgItem(IDC_CW_CLIP)->SetWindowText(L"Collision: clip maps and model collision");
        GetDlgItem(IDC_CW_ENTITY)->SetWindowText(L"Entities / dynamic models");
        GetDlgItem(IDC_CW_TRIGGER)->SetWindowText(L"Triggers");
        GetDlgItem(IDC_CW_FX)->SetWindowText(L"Effects");
        GetDlgItem(IDC_CW_AI)->SetWindowText(L"AI / animation tables");
        GetDlgItem(IDC_DEV_DESCRIPTION)->SetWindowText(L"1. Select the pool groups.\r\n2. Close Settings and click Load Game.\r\n3. Select the cw_pool rows and Export Selected.\r\n\r\nUse Capture options above to choose headers, verified map data or memory probes.");
    }
    else if(DevPage==1)
    {
        GetDlgItem(IDC_DEV_HEADING)->SetWindowText(L"Cold War pool export contents");
        Place(IDC_CW_EXPORT_MODE,17,78,310,85);
        Place(IDC_CW_CAPTURE_PLACEMENTS,17,103,310,12);
        Place(IDC_CW_CAPTURE_ENTITIES,17,119,310,12);
        Place(IDC_CW_CAPTURE_COLLISION,17,135,310,12);
        Place(IDC_CW_CAPTURE_SPLINES,17,151,310,12);
        Place(IDC_CW_CODE_PROBE,17,167,310,12);
        GetDlgItem(IDC_CW_CODE_PROBE)->SetWindowText(L"Capture collision reader code instead of pool data (research)");
        Place(IDC_CW_EXPORT_HINT,17,188,310,38);
        GetDlgItem(IDC_DEV_DESCRIPTION)->ShowWindow(SW_HIDE);
        UpdateCWExportHint();
    }
    else if(DevPage==2)
    {
        GetDlgItem(IDC_DEV_HEADING)->SetWindowText(L"Black Ops 4 capture to run");
        Place(IDC_BO4_CAPTURE_MODE,17,80,310,130);
        Place(IDC_DEV_BO4_RUN,17,108,220,22);
        wchar_t Override[2]={};
        const bool Overridden=GetEnvironmentVariableW(L"GREYHOUND_BO4_WORLD_PROBE",Override,2)==1;
        auto Modes=(CComboBox*)GetDlgItem(IDC_BO4_CAPTURE_MODE);
        if(Overridden)Modes->SetCurSel(Override[0]>='0' && Override[0]<='7' ? Override[0]-'0' : 0);
        Modes->EnableWindow(!Overridden);
        const int Mode=Modes->GetCurSel();
        GetDlgItem(IDC_DEV_DESCRIPTION)->SetWindowText(BO4Diagnostics::BO4CaptureModes[Mode>=0&&Mode<8?Mode:0].Hint);
        GetDlgItem(IDC_DEV_BO4_RUN)->EnableWindow(Mode>0 && CoDAssets::GameID==SupportedGames::BlackOps4 && CoDAssets::GameInstance!=nullptr);
        Place(IDC_DEV_TERRAIN_SETTINGS,17,137,220,22);
        GetDlgItem(IDC_TIP)->SetWindowText(Overridden ? L"Capture mode is set by GREYHOUND_BO4_WORLD_PROBE." : L"Load a BO4 map first. Terrain source capture uses TerrainGfx rows.");
    }
    else
    {
        GetDlgItem(IDC_DEV_HEADING)->SetWindowText(L"BO4 and Cold War export workflows");
        Place(IDC_DEV_TERRAIN_SETTINGS,17,78,220,22);
        Place(IDC_EXPORT_PLACEMENTS,17,105,220,22);
        Place(IDC_EXPORT_BRUSHES,17,132,220,22);
        Place(IDC_DEV_VERIFY_RUNTIME,17,159,151,22);
        Place(IDC_DEV_VERIFY_EXPORT,176,159,151,22);
        Place(IDC_DEV_DESCRIPTION,17,190,310,36);
        GetDlgItem(IDC_DEV_DESCRIPTION)->SetWindowText(L"Check installed tools, or select a brush export_report.json / terrain research_capture.report.json to check saved file integrity.\r\nPlacement verification and triangle options are on their export pages.");
    }
}

void GeneralSettings::OnXModels()
{
    // Whether or not we are checked
    bool CheckboxChecked = ((((CButton*)GetDlgItem(IDC_SHOWXMODEL))->GetState() & BST_CHECKED) == BST_CHECKED);
    // Set it
    SettingsManager::SetSetting("showxmodel", (CheckboxChecked) ? "true" : "false");
}

void GeneralSettings::OnXAnims()
{
    // Whether or not we are checked
    bool CheckboxChecked = ((((CButton*)GetDlgItem(IDC_SHOWXANIM))->GetState() & BST_CHECKED) == BST_CHECKED);
    // Set it
    SettingsManager::SetSetting("showxanim", (CheckboxChecked) ? "true" : "false");
}

void GeneralSettings::OnXImages()
{
    // Whether or not we are checked
    bool CheckboxChecked = ((((CButton*)GetDlgItem(IDC_SHOWXIMAGE))->GetState() & BST_CHECKED) == BST_CHECKED);
    // Set it
    SettingsManager::SetSetting("showximage", (CheckboxChecked) ? "true" : "false");
}

void GeneralSettings::OnXRawFiles()
{
    // Whether or not we are checked
    bool CheckboxChecked = ((((CButton*)GetDlgItem(IDC_SHOWXRAW))->GetState() & BST_CHECKED) == BST_CHECKED);
    // Set it
    SettingsManager::SetSetting("showxrawfiles", (CheckboxChecked) ? "true" : "false");
}

void GeneralSettings::OnXSounds()
{
    // Whether or not we are checked
    bool CheckboxChecked = ((((CButton*)GetDlgItem(IDC_SHOWXSOUNDS))->GetState() & BST_CHECKED) == BST_CHECKED);
    // Set it
    SettingsManager::SetSetting("showxsounds", (CheckboxChecked) ? "true" : "false");
}

void GeneralSettings::OnXMTL()
{
    // Whether or not we are checked
    bool CheckboxChecked = ((((CButton*)GetDlgItem(IDC_SHOWXMTL))->GetState() & BST_CHECKED) == BST_CHECKED);
    // Set it
    SettingsManager::SetSetting("showxmtl", (CheckboxChecked) ? "true" : "false");
}

void GeneralSettings::OnCWCLIP()
{
    SettingsManager::SetSetting("showcwcollision", ((CButton*)GetDlgItem(IDC_CW_CLIP))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWWORLD()
{
    SettingsManager::SetSetting("showcwworld", ((CButton*)GetDlgItem(IDC_CW_WORLD))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWNAV()
{
    SettingsManager::SetSetting("showcwnav", ((CButton*)GetDlgItem(IDC_CW_NAV))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWFX()
{
    SettingsManager::SetSetting("showcwfx", ((CButton*)GetDlgItem(IDC_CW_FX))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWENTITY()
{
    SettingsManager::SetSetting("showcwentities", ((CButton*)GetDlgItem(IDC_CW_ENTITY))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWTRIGGER()
{
    SettingsManager::SetSetting("showcwtriggers", ((CButton*)GetDlgItem(IDC_CW_TRIGGER))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWAI()
{
    SettingsManager::SetSetting("showcwai", ((CButton*)GetDlgItem(IDC_CW_AI))->GetCheck() == BST_CHECKED ? "true" : "false");
}

void GeneralSettings::OnCWExportMode()
{
    const auto Mode=((CComboBox*)GetDlgItem(IDC_CW_EXPORT_MODE))->GetCurSel();
    SettingsManager::SetSetting("cwmapdata",Mode==1?"true":"false");
    SettingsManager::SetSetting("cwprobepayloads",Mode>=2?"true":"false");
    SettingsManager::SetSetting("cwdeepProbe",Mode==3?"true":"false");
    UpdateCWExportHint();
}

void GeneralSettings::OnCWCaptureOptions()
{
    SettingsManager::SetSetting("cwcapturesplines", ((CButton*)GetDlgItem(IDC_CW_CAPTURE_SPLINES))->GetCheck()==BST_CHECKED ? "true":"false");
    SettingsManager::SetSetting("cwcaptureentities", ((CButton*)GetDlgItem(IDC_CW_CAPTURE_ENTITIES))->GetCheck()==BST_CHECKED ? "true":"false");
    SettingsManager::SetSetting("cwcaptureplacements", ((CButton*)GetDlgItem(IDC_CW_CAPTURE_PLACEMENTS))->GetCheck()==BST_CHECKED ? "true":"false");
    SettingsManager::SetSetting("cwcapturecollision", ((CButton*)GetDlgItem(IDC_CW_CAPTURE_COLLISION))->GetCheck()==BST_CHECKED ? "true":"false");
    SettingsManager::SetSetting("cwcollisioncodeprobe", ((CButton*)GetDlgItem(IDC_CW_CODE_PROBE))->GetCheck()==BST_CHECKED ? "true":"false");
    UpdateCWExportHint();
}

void GeneralSettings::UpdateCWExportHint()
{
    const auto Mode=((CComboBox*)GetDlgItem(IDC_CW_EXPORT_MODE))->GetCurSel();
    for (auto Id : {IDC_CW_CAPTURE_ENTITIES, IDC_CW_CAPTURE_PLACEMENTS, IDC_CW_CAPTURE_COLLISION, IDC_CW_CAPTURE_SPLINES})
        GetDlgItem(Id)->EnableWindow(Mode==1 || Mode==3);
    // The code span is read before any depth branching, so it replaces the pool
    // evidence in every mode, headers-only included. It is not mode-dependent.
    const wchar_t* Hints[]={
        L"Exports CW pool headers for research. Referenced geometry and entity properties are not collected.",
        L"Enable matching pools, Load Game, then export their cw_pool rows. Spline capture saves controls. Bake meshes with Spline models from JSON in Map & Model Export.",
        L"Exports headers and small samples of referenced memory. Samples are incomplete and may include adjacent data. Results remain research evidence.",
        L"Advanced: bounded reference probes plus selected map sections. Probes may include adjacent data regardless of section choices. Collision topology and ownership remain experimental."
    };
    const bool Code=SettingsManager::GetSetting("cwcollisioncodeprobe","false")=="true" ||
        GetEnvironmentVariableA("GREYHOUND_CW_COLLISION_CODE_PROBE",nullptr,0)!=0;
    for(auto Id:{IDC_CW_EXPORT_MODE,IDC_CW_CAPTURE_ENTITIES,IDC_CW_CAPTURE_PLACEMENTS,IDC_CW_CAPTURE_COLLISION,IDC_CW_CAPTURE_SPLINES})
        GetDlgItem(Id)->EnableWindow(!Code && (Id==IDC_CW_EXPORT_MODE || Mode==1 || Mode==3));
    GetDlgItem(IDC_CW_EXPORT_HINT)->SetWindowText(Code
        ? L"Pool exports save the fixed collision code span only. Requires the researched CW build. Radiant brush export continues to capture geometry."
        : Hints[Mode>=0&&Mode<4?Mode:0]);
}

void GeneralSettings::OnAssetSortMethod()
{
    // Grab the sort method
    auto SelectedFormat = ((CComboBox*)GetDlgItem(IDC_ASSET_SORT_METHOD))->GetCurSel();
    // Check and set
    switch (SelectedFormat)
    {
    case 0: SettingsManager::SetSetting("assetsortmethod", "Name"); break;
    case 1: SettingsManager::SetSetting("assetsortmethod", "Details"); break;
    case 2: SettingsManager::SetSetting("assetsortmethod", "None"); break;
    default: SettingsManager::SetSetting("exportimg", "Name"); break;
    }
}

void GeneralSettings::OnCWRadiantEnable()
{
    const bool Enabled=((CButton*)GetDlgItem(IDC_CW_RADIANT_ENABLE))->GetCheck()==BST_CHECKED;
    SettingsManager::SetSetting("cwradiantbrushes",Enabled?"true":"false");
    if(Enabled)SettingsManager::SetSetting("showcwcollision","true");
}
void GeneralSettings::OnCWRadiantOptions()
{
    SettingsManager::SetSetting("cwradianttypes",((CButton*)GetDlgItem(IDC_CW_RADIANT_TYPES))->GetCheck()==BST_CHECKED?"true":"false");
    SettingsManager::SetSetting("cwradiantvolumes",((CButton*)GetDlgItem(IDC_CW_RADIANT_VOLUMES))->GetCheck()==BST_CHECKED?"true":"false");
}
void GeneralSettings::OnExportBrushes()
{
    if(GetParent()) GetParent()->PostMessage(WM_COMMAND,IDC_EXPORT_BRUSHES);
}

void GeneralSettings::OnExportPlacements() { if(GetParent()) GetParent()->PostMessage(WM_COMMAND,IDC_EXPORT_PLACEMENTS); }
void GeneralSettings::OnNonStaticPlacements()
{
    SettingsManager::SetSetting("cwnonstaticplacements", ((CButton*)GetDlgItem(IDC_CW_NONSTATIC_PLACEMENTS))->GetCheck()==BST_CHECKED ? "true" : "false");
    UpdatePlacementOptions();
}

void GeneralSettings::OnPlacementOptions()
{
    SettingsManager::SetSetting("cwproxyfilter", ((CButton*)GetDlgItem(IDC_CW_PROXY_FILTER))->GetCheck()==BST_CHECKED ? "true" : "false");
    SettingsManager::SetSetting("cworganizeplacements", ((CButton*)GetDlgItem(IDC_CW_ORGANIZE_PLACEMENTS))->GetCheck()==BST_CHECKED ? "true" : "false");
    SettingsManager::SetSetting("cwverifyplacements", ((CButton*)GetDlgItem(IDC_CW_VERIFY_PLACEMENTS))->GetCheck()==BST_CHECKED ? "true" : "false");
}

// Sorting keys the run on the focused capture the non-static stage writes, so
// it cannot run on its own. Say so in the box rather than failing at export.
void GeneralSettings::UpdatePlacementOptions()
{
    const bool NonStatic=((CButton*)GetDlgItem(IDC_CW_NONSTATIC_PLACEMENTS))->GetCheck()==BST_CHECKED;
    GetDlgItem(IDC_CW_ORGANIZE_PLACEMENTS)->EnableWindow(NonStatic);
    GetDlgItem(IDC_CW_ORGANIZE_PLACEMENTS)->SetWindowText(NonStatic
        ? L"Sort the finished export into per-category folders"
        : L"Sort the finished export into per-category folders (needs the option above)");
    // Both auditors read the non-static stage's files, so they share its gate.
    GetDlgItem(IDC_CW_VERIFY_PLACEMENTS)->EnableWindow(NonStatic);
    GetDlgItem(IDC_CW_VERIFY_PLACEMENTS)->SetWindowText(NonStatic
        ? L"Verify the finished export against the captured bytes"
        : L"Verify the finished export against the captured bytes (needs the option above)");
}

void GeneralSettings::OnCollisionCoverage()
{
    SettingsManager::SetSetting("cwfloattriangles", ((CButton*)GetDlgItem(IDC_CW_FLOAT_TRIANGLES))->GetCheck()==BST_CHECKED ? "true" : "false");
    SettingsManager::SetSetting("cwmodeltriangles", ((CButton*)GetDlgItem(IDC_CW_MODEL_TRIANGLES))->GetCheck()==BST_CHECKED ? "true" : "false");
}
void GeneralSettings::OnExportJsonModels() { if(GetParent()) GetParent()->PostMessage(WM_COMMAND,IDC_EXPORT_JSON_MODELS); }

void GeneralSettings::OnBO4NameDatabase()
{
    auto Combo=(CComboBox*)GetDlgItem(IDC_BO4_NAME_DATABASE);
    const std::string Selected=Combo->GetCurSel()==1 ? "echo000" : "bundled";
    if (Selected=="echo000" && !BO4NameDatabase::Ready(Selected)) {
        MessageBoxA(GetSafeHwnd(),"The echo000 BO4/CW databases are not installed beside this Greyhound executable. Import them with tools/shared/name_db/import_echo_bo4.py first.","BO4 / CW name database",MB_OK|MB_ICONINFORMATION);
        Combo->SetCurSel(SettingsManager::GetSetting("bo4namedatabase","bundled")=="echo000" ? 1 : 0);
        return;
    }
    SettingsManager::SetSetting("bo4namedatabase",Selected);
}

void GeneralSettings::OnDevSection()
{
    DevPage=((CComboBox*)GetDlgItem(IDC_DEV_SECTION))->GetCurSel();
    ConfigurePage();
}
void GeneralSettings::OnBO4DiagnosticMode()
{
    const int Mode=((CComboBox*)GetDlgItem(IDC_BO4_CAPTURE_MODE))->GetCurSel();
    if(Mode>=0 && Mode<8)SettingsManager::SetSetting("bo4capturemode",std::to_string(Mode));
    ConfigurePage();
}
void GeneralSettings::OnRunBO4Diagnostic() { if(GetParent())GetParent()->PostMessage(WM_COMMAND,IDC_DEV_BO4_RUN); }
void GeneralSettings::OnVerifyRuntime() { if(GetParent())GetParent()->PostMessage(WM_COMMAND,IDC_DEV_VERIFY_RUNTIME); }
void GeneralSettings::OnTerrainSettings() { if(GetParent())GetParent()->PostMessage(WM_COMMAND,IDC_TERRAINPANEL); }

void GeneralSettings::OnVerifyExport() { if(GetParent())GetParent()->PostMessage(WM_COMMAND,IDC_DEV_VERIFY_EXPORT); }

void GeneralSettings::OnExportSplineModels() { if(GetParent()) GetParent()->PostMessage(WM_COMMAND,IDC_EXPORT_SPLINE_MODELS); }
