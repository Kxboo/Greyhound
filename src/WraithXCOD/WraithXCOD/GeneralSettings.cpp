#include "stdafx.h"

// The class we are implementing
#include "GeneralSettings.h"

// We need the Wraith theme and settings classes
#include "WraithTheme.h"
#include "SettingsManager.h"

// We need the following Wraith classes
#include "Strings.h"

BEGIN_MESSAGE_MAP(GeneralSettings, WraithWindow)
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
    ON_COMMAND(IDC_EXPORT_JSON_MODELS, OnExportJsonModels)
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
    ON_CBN_SELENDOK(IDC_CW_EXPORT_MODE, OnCWExportMode)
    ON_CBN_SELENDOK(IDC_ASSET_SORT_METHOD, OnAssetSortMethod)
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
    ((CButton*)GetDlgItem(IDC_CW_RADIANT_ENABLE))->SetCheck(SettingsManager::GetSetting("cwradiantbrushes", "false")=="true");
    ((CButton*)GetDlgItem(IDC_CW_RADIANT_TYPES))->SetCheck(SettingsManager::GetSetting("cwradianttypes", "true")=="true");
    ((CButton*)GetDlgItem(IDC_CW_RADIANT_VOLUMES))->SetCheck(SettingsManager::GetSetting("cwradiantvolumes", "true")=="true");
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
        IDC_SHOWXSOUNDS, IDC_SHOWXMTL, IDC_ASSET_SORT_METHOD, IDC_STATICFORMAT2};
    const int ColdWar[] = {IDC_CW_CLIP, IDC_CW_WORLD, IDC_CW_NAV, IDC_CW_FX,
        IDC_CW_ENTITY, IDC_CW_TRIGGER, IDC_CW_AI, IDC_CW_EXPORT_LABEL,
        IDC_CW_EXPORT_MODE, IDC_CW_EXPORT_HINT, IDC_CW_CAPTURE_ENTITIES,
        IDC_CW_CAPTURE_PLACEMENTS, IDC_CW_CAPTURE_COLLISION, IDC_CW_CAPTURE_SPLINES};
    for (int Id : {IDC_CW_RADIANT_ENABLE, IDC_EXPORT_BRUSHES, IDC_CW_RADIANT_INFO, IDC_CW_RADIANT_TYPES, IDC_CW_RADIANT_VOLUMES}) GetDlgItem(Id)->ShowWindow(SW_HIDE);
    for (int Id : {IDC_EXPORT_PLACEMENTS,IDC_EXPORT_JSON_MODELS,IDC_CW_PLACEMENT_INFO,IDC_CW_MODELS_INFO}) GetDlgItem(Id)->ShowWindow(SW_HIDE);
    for (int Id : Standard) GetDlgItem(Id)->ShowWindow(Page==0 ? SW_SHOW : SW_HIDE);
    for (int Id : ColdWar) GetDlgItem(Id)->ShowWindow(SW_HIDE);
    auto Place = [this](int Id, int X, int Y, int W, int H)
    {
        CRect Rect(X,Y,X+W,Y+H); MapDialogRect(&Rect);
        GetDlgItem(Id)->MoveWindow(Rect); GetDlgItem(Id)->ShowWindow(SW_SHOW);
    };
    GetDlgItem(IDC_TITLE)->SetWindowText(Page==0 ? L"In-game asset settings" :
        Page==1 ? L"CW Map Export" : L"Dev Tools");
    if (Page==0)
    {
        GetDlgItem(IDC_NOTICE)->SetWindowText(L"Model placement JSON and batch exports: CW Map Export. Research captures: Dev Tools.");
        GetDlgItem(IDC_TIP)->SetWindowText(L"Asset group changes require Load Game.");
        return;
    }
    if(Page==1)
    {
        Place(IDC_EXPORT_PLACEMENTS,17,48,220,24);
        Place(IDC_CW_PLACEMENT_INFO,17,80,310,34);
        GetDlgItem(IDC_CW_PLACEMENT_INFO)->SetWindowText(L"Save the loaded Cold War map's model names, positions, rotations and scales to static_models.json.");
        Place(IDC_EXPORT_JSON_MODELS,17,124,220,24);
        Place(IDC_CW_MODELS_INFO,17,156,310,56);
        GetDlgItem(IDC_CW_MODELS_INFO)->SetWindowText(L"Export each unique model referenced by static_models.json as CAST, with separate models, materials and images folders.\r\n\r\nTo resume, select the JSON inside an existing batch folder and choose Yes. Completed models are kept.");
        GetDlgItem(IDC_TIP)->SetWindowText(L"Load the matching map and Load Game first. Model and image settings apply to batch export.");
        GetDlgItem(IDC_NOTICE)->SetWindowText(L"Export all available LODs is respected. Brush prefabs are in CW Radiant Brushes.");
        return;
    }
    if(Page==3)
    {
        GetDlgItem(IDC_TITLE)->SetWindowText(L"CW Radiant Brushes");
        Place(IDC_CW_RADIANT_ENABLE,17,40,310,18);
        Place(IDC_CW_RADIANT_TYPES,17,60,310,14);
        Place(IDC_CW_RADIANT_VOLUMES,17,78,310,14);
        Place(IDC_EXPORT_BRUSHES,17,98,155,22);
        Place(IDC_CW_RADIANT_INFO,17,130,310,94);
        GetDlgItem(IDC_CW_RADIANT_INFO)->SetWindowText(
            L"Built-in BO3 material catalogue. No GDT paths or Python setup needed.\r\n\r\n"
            L"Brush types adapt to this map's properties. Named tools such as mount and closest BO3 collision matches are applied. Differences and unidentified fallbacks are recorded in material_assignments.json.\r\n\r\n"
            L"Brushes/clips, volumes and triggers export as separate world-space prefabs. Source properties and prefab membership stay in triggers.json. Brush cleanup remains bounded to 0.01 game units.");
        GetDlgItem(IDC_TIP)->SetWindowText(L"Load Game first, then Export brushes now. The checkbox also applies to CW collision-pool exports.");
        GetDlgItem(IDC_NOTICE)->SetWindowText(L"Exports to Greyhound's output folder. Does not create test maps or run BO3 compilation.");
        return;
    }
    Place(IDC_CW_EXPORT_LABEL,17,32,310,10);
    Place(IDC_CW_EXPORT_MODE,17,46,310,85);
    Place(IDC_CW_WORLD,17,76,155,12);
    Place(IDC_CW_NAV,180,76,147,12);
    Place(IDC_CW_CLIP,17,94,310,12);
    Place(IDC_CW_ENTITY,17,112,100,12);
    Place(IDC_CW_TRIGGER,122,112,100,12);
    Place(IDC_CW_FX,227,112,100,12);
    Place(IDC_CW_AI,17,128,310,12);
    GetDlgItem(IDC_CW_WORLD)->SetWindowText(L"Map world pools");
    GetDlgItem(IDC_CW_NAV)->SetWindowText(L"Navigation pools");
    GetDlgItem(IDC_CW_CLIP)->SetWindowText(L"Collision pools (model collision and brush payloads)");
    GetDlgItem(IDC_CW_ENTITY)->SetWindowText(L"Entity pools");
    GetDlgItem(IDC_CW_TRIGGER)->SetWindowText(L"Trigger pools");
    GetDlgItem(IDC_CW_FX)->SetWindowText(L"Effects pools");
    GetDlgItem(IDC_CW_AI)->SetWindowText(L"AI / animation table pools");
    Place(IDC_CW_CAPTURE_PLACEMENTS,17,146,310,12);
    Place(IDC_CW_CAPTURE_ENTITIES,17,162,310,12);
    Place(IDC_CW_CAPTURE_COLLISION,17,178,310,12);
    Place(IDC_CW_CAPTURE_SPLINES,17,194,310,12);
    GetDlgItem(IDC_CW_CAPTURE_SPLINES)->SetWindowText(L"Capture splined model inputs (experimental; no mesh export)");
    GetDlgItem(IDC_CW_CAPTURE_PLACEMENTS)->SetWindowText(L"Capture model placement records (not render meshes)");
    GetDlgItem(IDC_CW_CAPTURE_ENTITIES)->SetWindowText(L"Capture supported entity / trigger data");
    GetDlgItem(IDC_CW_CAPTURE_COLLISION)->SetWindowText(L"Capture collision payloads (offline mesh decoding)");
    Place(IDC_CW_EXPORT_HINT,17,209,310,23);
    GetDlgItem(IDC_NOTICE)->SetWindowText(L"Research capture controls. Use CW Map Export for placement JSON and model exports.");
    GetDlgItem(IDC_CW_EXPORT_LABEL)->SetWindowText(L"Shared capture mode (applies to exported CW pool rows)");
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
}

void GeneralSettings::UpdateCWExportHint()
{
    const auto Mode=((CComboBox*)GetDlgItem(IDC_CW_EXPORT_MODE))->GetCurSel();
    for (auto Id : {IDC_CW_CAPTURE_ENTITIES, IDC_CW_CAPTURE_PLACEMENTS, IDC_CW_CAPTURE_COLLISION, IDC_CW_CAPTURE_SPLINES})
        GetDlgItem(Id)->EnableWindow(Mode==1 || Mode==3);
    const wchar_t* Hints[]={
        L"Exports CW pool headers for research. Referenced geometry and entity properties are not collected.",
        L"Enable matching pools, Load Game, then export their cw_pool rows. Splines export source data; deformed meshes are not exported.",
        L"Exports headers and small samples of referenced memory. Samples are incomplete and may include adjacent data. Results remain research evidence.",
        L"Advanced: bounded reference probes plus selected map sections. Probes may include adjacent data regardless of section choices. Collision topology and ownership remain experimental."
    };
    GetDlgItem(IDC_CW_EXPORT_HINT)->SetWindowText(Hints[Mode>=0&&Mode<4?Mode:0]);
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
void GeneralSettings::OnExportJsonModels() { if(GetParent()) GetParent()->PostMessage(WM_COMMAND,IDC_EXPORT_JSON_MODELS); }
