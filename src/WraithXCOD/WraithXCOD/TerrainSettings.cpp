#include "stdafx.h"

#include "TerrainSettings.h"
#include "SettingsManager.h"

BEGIN_MESSAGE_MAP(TerrainSettings, WraithWindow)
    ON_COMMAND(IDC_SHOWXTERRAIN, OnShowTerrains)
    ON_COMMAND(IDC_SKIPPREVTERRAIN, OnSkipPreviousTerrains)
END_MESSAGE_MAP()

namespace
{
    void SetFlag(const char* Key, bool Value)
    {
        SettingsManager::SetSetting(Key, Value ? "true" : "false");
    }

    bool Flag(const char* Key, const char* Fallback)
    {
        return SettingsManager::GetSetting(Key, Fallback) == "true";
    }
}

void TerrainSettings::OnBeforeLoad()
{
    TitleFont.CreateFont(20, 0, 0, 0, FW_NORMAL, FALSE, FALSE, 0,
        ANSI_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY, DEFAULT_PITCH | FF_SWISS, L"Microsoft Sans Serif");
    GetDlgItem(IDC_TITLE)->SetFont(&TitleFont);

    ((CButton*)GetDlgItem(IDC_SHOWXTERRAIN))->SetCheck(
        Flag("showxterrain", "true"));
    ((CButton*)GetDlgItem(IDC_SKIPPREVTERRAIN))->SetCheck(
        Flag("skipprevterrain", "false"));
    GetDlgItem(IDC_TERRAIN_STATUS)->SetWindowText(
        L"Output: complete source capture (no reconstructed mesh)");
    GetDlgItem(IDC_TERRAIN_NOTICE)->SetWindowText(
        L"Use the separate terrain reconstruction tool after Greyhound finishes and seals the capture.");
}

void TerrainSettings::OnShowTerrains()
{
    SetFlag("showxterrain",
        (((CButton*)GetDlgItem(IDC_SHOWXTERRAIN))->GetState() & BST_CHECKED)
        == BST_CHECKED);
}

void TerrainSettings::OnSkipPreviousTerrains()
{
    SetFlag("skipprevterrain",
        (((CButton*)GetDlgItem(IDC_SKIPPREVTERRAIN))->GetState() & BST_CHECKED)
        == BST_CHECKED);
}
