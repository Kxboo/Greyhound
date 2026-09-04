#pragma once

#define _AFXDLL // AFX Shared DLL
#define _WIN32_WINNT 0x0601 // Windows 7+

#include <afxwin.h>
#include <afxcview.h>
#include <afxext.h>

#include "resource.h"
#include "WraithWindow.h"

// Greyhound exports source terrain data only. Reconstruction settings live in
// the independent terrain reconstruction repository.
class TerrainSettings : public WraithWindow
{
public:
    TerrainSettings(CWnd* pParent = NULL) : WraithWindow(IDD_TERRAINSETTINGS, pParent) { }

private:
    void OnShowTerrains();
    void OnSkipPreviousTerrains();

protected:
    virtual void OnBeforeLoad();
    CFont TitleFont;

    DECLARE_MESSAGE_MAP()
};
