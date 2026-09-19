#include "stdafx.h"

#include "TerrainSettings.h"
#include "SettingsManager.h"
#include "BO4CaptureModes.h"
using namespace BO4Diagnostics;

BEGIN_MESSAGE_MAP(TerrainSettings, WraithWindow)
    ON_COMMAND(IDC_SHOWXTERRAIN, OnShowTerrains)
    ON_COMMAND(IDC_SKIPPREVTERRAIN, OnSkipPreviousTerrains)
    ON_CBN_SELENDOK(IDC_BO4_CAPTURE_MODE, OnBO4CaptureMode)
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

    GetDlgItem(IDC_BO4_CAPTURE_LABEL)->SetWindowText(
        L"Black Ops 4 capture run by Export (Cold War is unaffected)");

    auto Modes = (CComboBox*)GetDlgItem(IDC_BO4_CAPTURE_MODE);
    for (int i = 0; i < BO4CaptureModeCount; i++)
        Modes->InsertString(i, BO4CaptureModes[i].Label);

    const auto Selected = SettingsManager::GetSetting("bo4capturemode", "0");
    Modes->SetCurSel(0);
    for (int i = 0; i < BO4CaptureModeCount; i++)
    {
        if (Selected == BO4CaptureModes[i].Value)
        {
            Modes->SetCurSel(i);
            break;
        }
    }

    UpdateBO4CaptureMode();
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

void TerrainSettings::OnBO4CaptureMode()
{
    const auto Index = ((CComboBox*)GetDlgItem(IDC_BO4_CAPTURE_MODE))->GetCurSel();
    if (Index < 0 || Index >= BO4CaptureModeCount)
        return;
    SettingsManager::SetSetting("bo4capturemode", BO4CaptureModes[Index].Value);
    UpdateBO4CaptureMode();
}

void TerrainSettings::UpdateBO4CaptureMode()
{
    auto Modes = (CComboBox*)GetDlgItem(IDC_BO4_CAPTURE_MODE);
    auto Index = Modes->GetCurSel();
    if (Index < 0 || Index >= BO4CaptureModeCount)
        Index = 0;

    // The environment variable still wins inside the exporter so existing
    // headless scripts keep working. Say so instead of showing a selection
    // that will not be the one used.
    wchar_t Override[2] = {};
    const bool Overridden =
        GetEnvironmentVariableW(L"GREYHOUND_BO4_WORLD_PROBE", Override, 2) == 1;

    if (Overridden)
    {
        for (int i = 0; i < BO4CaptureModeCount; i++)
        {
            if (Override[0] == wchar_t(BO4CaptureModes[i].Value[0]))
            {
                Index = i;
                Modes->SetCurSel(i);
                break;
            }
        }
    }
    Modes->EnableWindow(!Overridden);

    GetDlgItem(IDC_BO4_CAPTURE_HINT)->SetWindowText(BO4CaptureModes[Index].Hint);

    CString Status(L"Output: complete source capture (no reconstructed mesh)");
    if (Index != 0)
    {
        Status = L"Output: Black Ops 4 ";
        Status += BO4CaptureModes[Index].Label;
        Status += L". Terrain assets are not captured in this mode.";
    }
    if (Overridden)
        Status += L" Set by GREYHOUND_BO4_WORLD_PROBE.";
    GetDlgItem(IDC_TERRAIN_STATUS)->SetWindowText(Status);

    GetDlgItem(IDC_TERRAIN_NOTICE)->SetWindowText(Index == 0
        ? L"Use the separate terrain reconstruction tool after Greyhound finishes and seals the capture. Black Ops 4 terrain is measured, not reconstructed, and is not sealed."
        : L"Select a Black Ops 4 TerrainGfx asset and Export to run this capture. Return to the default mode for terrain source data.");
}
