#pragma once

#define _AFXDLL // AFX Shared DLL
#define _WIN32_WINNT 0x0601 // Windows 7+

#include <afxwin.h>
#include <afxcview.h>
#include <afxext.h>

// We need the resources
#include "resource.h"

// We need the WraithWindow class
#include "WraithWindow.h"

// The COD general settings
class GeneralSettings : public WraithWindow
{
public:
    // Make a new panel
    GeneralSettings(CWnd* pParent = NULL, int page = 0) : WraithWindow(IDD_GENERALSETTINGS, pParent), Page(page) { }

private:
    // -- Event delegates

    int Page = 0;
    int DevPage = 0;
    void OnDevSection();
    void OnBO4DiagnosticMode();
    void OnRunBO4Diagnostic();
    void OnVerifyRuntime();
    void OnVerifyExport();
    void OnTerrainSettings();
    void ConfigurePage();
    void OnCWRadiantEnable();
    void OnCWRadiantOptions();
    void OnExportBrushes();
    void OnExportPlacements();
    void OnNonStaticPlacements();
    void OnPlacementOptions();
    void UpdatePlacementOptions();
    void OnCollisionCoverage();
    void OnExportJsonModels();
    void OnExportSplineModels();
    void OnXModels();
    void OnXAnims();
    void OnXImages();
    void OnXEffects();
    void OnXRawFiles();
    void OnXSounds();
    void OnXMTL();
    void OnCWCLIP();
    void OnCWWORLD();
    void OnCWNAV();
    void OnCWFX();
    void OnCWENTITY();
    void OnCWTRIGGER();
    void OnCWAI();
    void OnCWExportMode();
    void OnCWCaptureOptions();
    void UpdateCWExportHint();
    void OnAssetSortMethod();
    void OnSalukiFolder();
    void OnSalukiDownload();
    void OnSalukiLink();
    void OnSalukiAuto();
    void OnSalukiDisable();
    void UpdateSalukiHint();
    void RunSalukiImport(const std::string& Folder, bool Download);


protected:

    // Occures when the window is loading
    virtual void OnBeforeLoad();

    // The title font
    CFont TitleFont;

    // Make the map
    DECLARE_MESSAGE_MAP()
};
