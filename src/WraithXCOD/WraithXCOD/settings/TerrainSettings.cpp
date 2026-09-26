#include "stdafx.h"
#include "settings/TerrainSettings.h"
#include "SettingsManager.h"
BEGIN_MESSAGE_MAP(TerrainSettings, WraithWindow)
    ON_COMMAND(IDC_SHOWXTERRAIN, OnShowTerrains)
    ON_CBN_SELENDOK(IDC_TERRAIN_AREA, OnArea)
    ON_CBN_SELENDOK(IDC_TERRAIN_FORMATS, OnFormats)
    ON_EN_KILLFOCUS(IDC_TERRAIN_OUTPUT, OnOutput)
END_MESSAGE_MAP()
void TerrainSettings::OnBeforeLoad()
{
    TitleFont.CreateFont(20,0,0,0,FW_NORMAL,FALSE,FALSE,0,ANSI_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY,DEFAULT_PITCH | FF_SWISS,L"Microsoft Sans Serif");
    GetDlgItem(IDC_TITLE)->SetFont(&TitleFont);
    ((CButton*)GetDlgItem(IDC_SHOWXTERRAIN))->SetCheck(SettingsManager::GetSetting("showxterrain","true")=="true");
    ::SetWindowTextA(GetDlgItem(IDC_TERRAIN_OUTPUT)->GetSafeHwnd(),SettingsManager::GetSetting("terrainoutputroot", "").c_str());
    auto Area=(CComboBox*)GetDlgItem(IDC_TERRAIN_AREA);
    Area->AddString(L"Whole map");Area->AddString(L"5 x 5 tiles near the current view (test)");
    Area->SetCurSel(SettingsManager::GetSetting("terrainarea","whole")=="nearby"?1:0);
    auto Formats=(CComboBox*)GetDlgItem(IDC_TERRAIN_FORMATS);
    Formats->AddString(L"CAST");Formats->AddString(L"Use formats selected in Model settings");
    Formats->SetCurSel(SettingsManager::GetSetting("terrainmodelformats","cast")=="selected"?1:0);
}
void TerrainSettings::OnShowTerrains()
{
    SettingsManager::SetSetting("showxterrain",((CButton*)GetDlgItem(IDC_SHOWXTERRAIN))->GetCheck()?"true":"false");
}
void TerrainSettings::OnArea()
{
    SettingsManager::SetSetting("terrainarea",((CComboBox*)GetDlgItem(IDC_TERRAIN_AREA))->GetCurSel()==1?"nearby":"whole");
}
void TerrainSettings::OnFormats()
{
    SettingsManager::SetSetting("terrainmodelformats",((CComboBox*)GetDlgItem(IDC_TERRAIN_FORMATS))->GetCurSel()==1?"selected":"cast");
}

void TerrainSettings::OnOutput()
{
    char Path[32768]={};
    ::GetWindowTextA(GetDlgItem(IDC_TERRAIN_OUTPUT)->GetSafeHwnd(),Path,sizeof Path);
    SettingsManager::SetSetting("terrainoutputroot",Path);
}
