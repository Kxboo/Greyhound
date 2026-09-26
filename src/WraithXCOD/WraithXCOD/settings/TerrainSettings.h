#pragma once

#define _AFXDLL // AFX Shared DLL
#define _WIN32_WINNT 0x0601 // Windows 7+

#include <afxwin.h>
#include <afxcview.h>
#include <afxext.h>

#include "resource.h"
#include "WraithWindow.h"

// Main terrain model export controls. Raw captures live in Dev Tools.
class TerrainSettings : public WraithWindow
{
public:
    TerrainSettings(CWnd* pParent = NULL) : WraithWindow(IDD_TERRAINSETTINGS, pParent) { }

private:
    void OnShowTerrains();
    void OnArea();
    void OnFormats();
    void OnOutput();

protected:
    virtual void OnBeforeLoad();
    CFont TitleFont;

    DECLARE_MESSAGE_MAP()
};
