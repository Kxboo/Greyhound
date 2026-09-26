#include "stdafx.h"

// The class we are implementing
#include "ui/native/UiHost.h"

#include <memory>
#include <thread>
#include <wrl.h>
#include <dwmapi.h>
#include <shlobj.h>
#include "WebView2.h"
#include "ui/native/UiBridge.h"
#include "SettingsManager.h"
#include "Strings.h"
#include "resource.h"

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

namespace
{
    const UINT WM_APP_INVOKE = WM_APP + 1;
    const UINT WM_APP_PAGE = WM_APP + 2;
    const UINT_PTR FlushTimer = 1;
    const wchar_t* WindowClass = L"GreyhoundV2";
    const wchar_t* Origin = L"https://greyhound.ui/";
    const COLORREF DarkBackground = RGB(0x1c, 0x1b, 0x1a);
    const COLORREF LightBackground = RGB(0xfa, 0xf9, 0xf5);

    std::wstring ExeFolder()
    {
        wchar_t Path[MAX_PATH * 4]{};
        GetModuleFileNameW(NULL, Path, (DWORD)(sizeof(Path) / sizeof(Path[0])));
        std::wstring Folder(Path);
        return Folder.substr(0, Folder.find_last_of(L"\\/"));
    }

    std::wstring UiFolder() { return ExeFolder() + L"\\ui"; }

    std::wstring Utf8ToWide(const std::string& Text)
    {
        if (Text.empty()) return {};
        const int Size = MultiByteToWideChar(CP_UTF8, 0, Text.data(), (int)Text.size(), nullptr, 0);
        std::wstring Out((size_t)Size, L'\0');
        MultiByteToWideChar(CP_UTF8, 0, Text.data(), (int)Text.size(), &Out[0], Size);
        return Out;
    }

    std::string WideToUtf8(const wchar_t* Text)
    {
        if (Text == nullptr || *Text == 0) return {};
        const int Size = WideCharToMultiByte(CP_UTF8, 0, Text, -1, nullptr, 0, nullptr, nullptr);
        std::string Out((size_t)Size, '\0');
        WideCharToMultiByte(CP_UTF8, 0, Text, -1, &Out[0], Size, nullptr, nullptr);
        Out.resize((size_t)Size - 1);
        return Out;
    }

    // Windows 10 1607+ APIs, looked up so older SDK headers still build.
    UINT WindowDpi(HWND Window)
    {
        using GetDpiForWindowFn = UINT(WINAPI*)(HWND);
        static auto Fn = (GetDpiForWindowFn)GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow");
        if (Fn != nullptr && Window != NULL) return Fn(Window);
        HDC Dc = GetDC(NULL);
        const UINT Dpi = (UINT)GetDeviceCaps(Dc, LOGPIXELSX);
        ReleaseDC(NULL, Dc);
        return Dpi;
    }

    void UsePerMonitorDpi()
    {
        using SetContextFn = HANDLE(WINAPI*)(HANDLE);
        auto Fn = (SetContextFn)GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetThreadDpiAwarenessContext");
        // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if (Fn != nullptr) Fn((HANDLE)-4);
    }

    bool SystemPrefersDark()
    {
        DWORD Light = 1, Size = sizeof(Light);
        RegGetValueW(HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
            L"AppsUseLightTheme", RRF_RT_REG_DWORD, nullptr, &Light, &Size);
        return Light == 0;
    }

    struct PageMessage
    {
        std::string Json;
        std::vector<std::string> Files;
        bool FromPopup = false;
    };

    class Window
    {
    public:
        HWND Hwnd = NULL;
        bool Failed = false;
        explicit Window(Window* Owner = nullptr) : Parent(Owner) {}

        bool Create()
        {
            Life = std::make_shared<std::atomic<bool>>(true);
            HINSTANCE Instance = GetModuleHandleW(NULL);
            WNDCLASSEXW Class{};
            Class.cbSize = sizeof(Class);
            Class.lpfnWndProc = Proc;
            Class.hInstance = Instance;
            Class.hIcon = LoadIconW(Instance, MAKEINTRESOURCEW(IDI_MAINICON));
            Class.hIconSm = (HICON)LoadImageW(Instance, MAKEINTRESOURCEW(IDI_MAINICON), IMAGE_ICON,
                GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), LR_SHARED);
            Class.hCursor = LoadCursor(NULL, IDC_ARROW);
            Class.lpszClassName = WindowClass;
            RegisterClassExW(&Class);

            Dark = PreferDark();
            Background = CreateSolidBrush(Dark ? DarkBackground : LightBackground);

            // 1280 x 820 at 100%, centred on the primary work area.
            const UINT Dpi = WindowDpi(NULL);
            RECT Work{};
            SystemParametersInfoW(SPI_GETWORKAREA, 0, &Work, 0);
            const int Width = std::min<int>(MulDiv(1280, Dpi, 96), Work.right - Work.left);
            const int Height = std::min<int>(MulDiv(820, Dpi, 96), Work.bottom - Work.top);
            Hwnd = CreateWindowExW(0, WindowClass, Parent ? L"Greyhound Preview" : L"Greyhound", WS_OVERLAPPEDWINDOW,
                Work.left + (Work.right - Work.left - Width) / 2, Work.top + (Work.bottom - Work.top - Height) / 2,
                Width, Height, Parent ? Parent->Hwnd : NULL, NULL, Instance, this);
            if (Hwnd == NULL) return false;

            ApplyTheme(Dark);
            RestorePlacement();
            UpdateWindow(Hwnd);
            StartWebView();
            return true;
        }

        void Close()
        {
            *Life = false;
            Closing = true;
            if (Popup)
            {
                if (Popup->Hwnd) DestroyWindow(Popup->Hwnd);
                Popup->Close();
                Popup.reset();
            }
            Bridge.reset();
            Controller.Reset();
            View.Reset();
            Environment.Reset();
            if (Background) { DeleteObject(Background); Background = NULL; }
        }

    private:
        ComPtr<ICoreWebView2Environment> Environment;
        ComPtr<ICoreWebView2Controller> Controller;
        ComPtr<ICoreWebView2> View;
        std::unique_ptr<UiBridge> Bridge;
        Window* Parent = nullptr;
        std::unique_ptr<Window> Popup;
        std::shared_ptr<std::atomic<bool>> Life = std::make_shared<std::atomic<bool>>(true);
        bool Closing = false;
        HBRUSH Background = NULL;
        bool Dark = true;

        static bool PreferDark()
        {
            const auto Theme = SettingsManager::GetSetting("uitheme", "system");
            return Theme == "dark" || (Theme != "light" && SystemPrefersDark());
        }

        void ApplyTheme(bool UseDark)
        {
            Dark = UseDark;
            // DWMWA_USE_IMMERSIVE_DARK_MODE and DWMWA_CAPTION_COLOR (Windows 11).
            BOOL Value = UseDark ? TRUE : FALSE;
            DwmSetWindowAttribute(Hwnd, 20, &Value, sizeof(Value));
            COLORREF Caption = UseDark ? DarkBackground : LightBackground;
            DwmSetWindowAttribute(Hwnd, 35, &Caption, sizeof(Caption));
            if (Background) DeleteObject(Background);
            Background = CreateSolidBrush(Caption);
            ComPtr<ICoreWebView2Controller2> Controller2;
            if (Controller && SUCCEEDED(Controller.As(&Controller2)))
                Controller2->put_DefaultBackgroundColor({ 255, GetRValue(Caption), GetGValue(Caption), GetBValue(Caption) });
            InvalidateRect(Hwnd, nullptr, TRUE);
        }

        // "left,top,right,bottom,maximized" in workspace coordinates.
        void RestorePlacement()
        {
            const auto Saved = SettingsManager::GetSetting(Parent ? "v2previewwindow" : "v2window", "");
            WINDOWPLACEMENT Placement{};
            Placement.length = sizeof(Placement);
            GetWindowPlacement(Hwnd, &Placement);
            RECT Rect{};
            int Maximized = 0;
            if (sscanf_s(Saved.c_str(), "%ld,%ld,%ld,%ld,%d", &Rect.left, &Rect.top, &Rect.right, &Rect.bottom, &Maximized) == 5 &&
                Rect.right - Rect.left >= 400 && Rect.bottom - Rect.top >= 300 && MonitorFromRect(&Rect, MONITOR_DEFAULTTONULL) != NULL)
            {
                Placement.rcNormalPosition = Rect;
                Placement.showCmd = Maximized ? SW_SHOWMAXIMIZED : SW_SHOWNORMAL;
                SetWindowPlacement(Hwnd, &Placement);
            }
            else ShowWindow(Hwnd, SW_SHOWNORMAL);
        }

        void SavePlacement()
        {
            WINDOWPLACEMENT Placement{};
            Placement.length = sizeof(Placement);
            if (!GetWindowPlacement(Hwnd, &Placement)) return;
            const auto& R = Placement.rcNormalPosition;
            SettingsManager::SetSetting(Parent ? "v2previewwindow" : "v2window", Strings::Format("%ld,%ld,%ld,%ld,%d", R.left, R.top, R.right, R.bottom,
                Placement.showCmd == SW_SHOWMAXIMIZED ? 1 : 0));
        }

        void Fail(const wchar_t* Stage, HRESULT Result)
        {
            wchar_t Text[512];
            swprintf_s(Text, L"Greyhound v2 could not start its interface (%s, 0x%08X).\n\nThe classic interface will open instead.", Stage, (unsigned)Result);
            if (Parent) swprintf_s(Text, L"The preview window could not open (%s, 0x%08X). It will dock in the Library.", Stage, (unsigned)Result);
            MessageBoxW(Hwnd, Text, L"Greyhound", MB_OK | MB_ICONWARNING);
            Failed = true;
            DestroyWindow(Hwnd);
        }

        void StartWebView()
        {
            const auto Lifetime = Life;
            PWSTR LocalAppData = nullptr;
            std::wstring DataFolder;
            if (SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &LocalAppData)))
                DataFolder = std::wstring(LocalAppData) + L"\\Greyhound\\WebView2";
            CoTaskMemFree(LocalAppData);

            const HRESULT Started = CreateCoreWebView2EnvironmentWithOptions(nullptr, DataFolder.empty() ? nullptr : DataFolder.c_str(), nullptr,
                Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>([this, Lifetime](HRESULT Result, ICoreWebView2Environment* Created) -> HRESULT
            {
                if (!Lifetime->load()) return S_OK;
                if (FAILED(Result) || Created == nullptr) { Fail(L"environment", Result); return S_OK; }
                Environment = Created;
                const HRESULT StartedController = Environment->CreateCoreWebView2Controller(Hwnd, Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                    [this, Lifetime](HRESULT Result, ICoreWebView2Controller* Made) -> HRESULT
                {
                    if (!Lifetime->load()) { if (Made) Made->Close(); return S_OK; }
                    if (FAILED(Result) || Made == nullptr) { Fail(L"controller", Result); return S_OK; }
                    Controller = Made;
                    Controller->get_CoreWebView2(&View);
                    Configure();
                    return S_OK;
                }).Get());
                if (FAILED(StartedController)) Fail(L"controller", StartedController);
                return S_OK;
            }).Get());
            if (FAILED(Started)) Fail(L"loader", Started);
        }

        void Configure()
        {
            const auto Lifetime = Life;
            const bool DevTools = GetEnvironmentVariableW(L"GREYHOUND_DEVTOOLS", nullptr, 0) > 0;
            ApplyTheme(Dark);

            ComPtr<ICoreWebView2Settings> Settings;
            View->get_Settings(&Settings);
            Settings->put_AreDefaultContextMenusEnabled(DevTools);
            Settings->put_AreDevToolsEnabled(DevTools);
            Settings->put_IsStatusBarEnabled(FALSE);
            Settings->put_IsZoomControlEnabled(FALSE);
            ComPtr<ICoreWebView2Settings3> Settings3;
            if (SUCCEEDED(Settings.As(&Settings3))) Settings3->put_AreBrowserAcceleratorKeysEnabled(DevTools);
            ComPtr<ICoreWebView2Settings4> Settings4;
            if (SUCCEEDED(Settings.As(&Settings4)))
            {
                Settings4->put_IsPasswordAutosaveEnabled(FALSE);
                Settings4->put_IsGeneralAutofillEnabled(FALSE);
            }

            ComPtr<ICoreWebView2_3> View3;
            if (FAILED(View.As(&View3))) { Fail(L"folder mapping", E_NOINTERFACE); return; }
            View3->SetVirtualHostNameToFolderMapping(L"greyhound.ui", UiFolder().c_str(), COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_DENY_CORS);

            EventRegistrationToken Token;
            // The page never leaves greyhound.ui; links go through shell.url.
            View->add_NavigationStarting(Callback<ICoreWebView2NavigationStartingEventHandler>(
                [](ICoreWebView2*, ICoreWebView2NavigationStartingEventArgs* Args) -> HRESULT
            {
                PWSTR Uri = nullptr;
                Args->get_Uri(&Uri);
                const bool Allowed = Uri != nullptr && wcsncmp(Uri, Origin, wcslen(Origin)) == 0;
                CoTaskMemFree(Uri);
                if (!Allowed) Args->put_Cancel(TRUE);
                return S_OK;
            }).Get(), &Token);
            View->add_NewWindowRequested(Callback<ICoreWebView2NewWindowRequestedEventHandler>(
                [](ICoreWebView2*, ICoreWebView2NewWindowRequestedEventArgs* Args) -> HRESULT
            {
                Args->put_Handled(TRUE);
                return S_OK;
            }).Get(), &Token);
            View->add_ProcessFailed(Callback<ICoreWebView2ProcessFailedEventHandler>(
                [this, Lifetime](ICoreWebView2*, ICoreWebView2ProcessFailedEventArgs* Args) -> HRESULT
            {
                if (!Lifetime->load()) return S_OK;
                COREWEBVIEW2_PROCESS_FAILED_KIND Kind;
                Args->get_ProcessFailedKind(&Kind);
                if (Kind == COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_EXITED || Kind == COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_UNRESPONSIVE)
                    View->Reload();
                return S_OK;
            }).Get(), &Token);
            // Handled later from the message loop, never inside this callback,
            // so commands may open native dialogs safely.
            View->add_WebMessageReceived(Callback<ICoreWebView2WebMessageReceivedEventHandler>(
                [this, Lifetime](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* Args) -> HRESULT
            {
                if (!Lifetime->load()) return S_OK;
                PWSTR Source = nullptr;
                Args->get_Source(&Source);
                const bool Trusted = Source != nullptr && wcsncmp(Source, Origin, wcslen(Origin)) == 0;
                CoTaskMemFree(Source);
                if (!Trusted) return S_OK;

                PWSTR Json = nullptr;
                if (FAILED(Args->get_WebMessageAsJson(&Json))) return S_OK;
                auto Message = new PageMessage{ WideToUtf8(Json), {}, Parent != nullptr };
                CoTaskMemFree(Json);

                ComPtr<ICoreWebView2WebMessageReceivedEventArgs2> Args2;
                ComPtr<ICoreWebView2ObjectCollectionView> Objects;
                if (SUCCEEDED(Args->QueryInterface(IID_PPV_ARGS(&Args2))) && SUCCEEDED(Args2->get_AdditionalObjects(&Objects)) && Objects)
                {
                    UINT32 Count = 0;
                    Objects->get_Count(&Count);
                    for (UINT32 i = 0; i < Count; i++)
                    {
                        ComPtr<IUnknown> Object;
                        ComPtr<ICoreWebView2File> File;
                        PWSTR Path = nullptr;
                        if (SUCCEEDED(Objects->GetValueAtIndex(i, &Object)) && Object && SUCCEEDED(Object.As(&File)) && SUCCEEDED(File->get_Path(&Path)))
                        {
                            Message->Files.push_back(Strings::ToNormalString(Path));
                            CoTaskMemFree(Path);
                        }
                    }
                }
                if (!PostMessageW(Hwnd, WM_APP_PAGE, 0, (LPARAM)Message)) delete Message;
                return S_OK;
            }).Get(), &Token);

            if (!Parent)
            {
            UiBridge::Host Host;
            Host.Window = Hwnd;
            ComPtr<ICoreWebView2> Page = View;
            Host.Post = [Page](const std::string& Json) { Page->PostWebMessageAsJson(Utf8ToWide(Json).c_str()); };
            const HWND Target = Hwnd;
            Host.Invoke = [Target](std::function<void()> Work)
            {
                auto Boxed = new std::function<void()>(std::move(Work));
                if (!PostMessageW(Target, WM_APP_INVOKE, 0, (LPARAM)Boxed)) delete Boxed;
            };
            Host.Theme = [this](bool UseDark) { if (UseDark != Dark) ApplyTheme(UseDark); if (Popup && Popup->Hwnd) Popup->ApplyTheme(UseDark); };
            Host.Ready = [this] { Controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC); };
            Host.Close = [Target] { PostMessageW(Target, WM_CLOSE, 0, 0); };
            Host.PostPopup = [this](const std::string& Json)
            {
                if (Popup && Popup->Hwnd && Popup->View) Popup->View->PostWebMessageAsJson(Utf8ToWide(Json).c_str());
            };
            Host.PostPreview = [this](const std::string& Json)
            {
                auto Receiver = Popup && Popup->Hwnd ? Popup.get() : this;
                if (Receiver->View) Receiver->View->PostWebMessageAsJson(Utf8ToWide(Json).c_str());
            };
            Host.SharePreview = [this](const std::vector<uint8_t>& Bytes, const std::string& Metadata)
            {
                // The older runtime fallback uses bounded ordinary messages.
                auto Receiver = Popup && Popup->Hwnd ? Popup.get() : this;
                ComPtr<ICoreWebView2Environment12> Environment12;
                ComPtr<ICoreWebView2_17> View17;
                if (Bytes.empty() || !Receiver->Environment || !Receiver->View ||
                    FAILED(Receiver->Environment.As(&Environment12)) || FAILED(Receiver->View.As(&View17))) return false;
                ComPtr<ICoreWebView2SharedBuffer> Buffer;
                BYTE* Data = nullptr;
                if (FAILED(Environment12->CreateSharedBuffer(Bytes.size(), &Buffer)) || FAILED(Buffer->get_Buffer(&Data))) return false;
                memcpy(Data, Bytes.data(), Bytes.size());
                const HRESULT Result = View17->PostSharedBufferToScript(Buffer.Get(), COREWEBVIEW2_SHARED_BUFFER_ACCESS_READ_ONLY, Utf8ToWide(Metadata).c_str());
                Buffer->Close(); // The page releases its separate view after GPU upload.
                return SUCCEEDED(Result);
            };
            Host.PopOut = [this]
            {
                if (Popup && Popup->Hwnd) { SetForegroundWindow(Popup->Hwnd); return true; }
                if (Popup) Popup->Close();
                Popup = std::make_unique<Window>(this);
                return Popup->Create();
            };
            Host.Dock = [this] { if (Popup && Popup->Hwnd) PostMessageW(Popup->Hwnd, WM_CLOSE, 0, 0); };
            Bridge = std::make_unique<UiBridge>(Host);
            SetTimer(Hwnd, FlushTimer, 50, nullptr);
            }

            Resize();
            View->Navigate(Parent ? L"https://greyhound.ui/index.html?previewWindow=1" : L"https://greyhound.ui/index.html");
            if (DevTools) View->OpenDevToolsWindow();
        }

        void Resize()
        {
            if (!Controller) return;
            RECT Bounds;
            GetClientRect(Hwnd, &Bounds);
            Controller->put_Bounds(Bounds);
        }

        LRESULT Handle(UINT Message, WPARAM W, LPARAM L)
        {
            switch (Message)
            {
            case WM_SIZE:
                if (Controller) Controller->put_IsVisible(W != SIZE_MINIMIZED);
                Resize();
                return 0;
            case WM_MOVE:
            case WM_MOVING:
                if (Controller) Controller->NotifyParentWindowPositionChanged();
                break;
            case WM_SETFOCUS:
                if (Controller) Controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
                return 0;
            case WM_GETMINMAXINFO:
            {
                const UINT Dpi = WindowDpi(Hwnd);
                auto Info = (MINMAXINFO*)L;
                Info->ptMinTrackSize.x = MulDiv(Parent ? 420 : 900, Dpi, 96);
                Info->ptMinTrackSize.y = MulDiv(Parent ? 320 : 580, Dpi, 96);
                return 0;
            }
            case 0x02E0: // WM_DPICHANGED
            {
                auto Suggested = (RECT*)L;
                SetWindowPos(Hwnd, NULL, Suggested->left, Suggested->top, Suggested->right - Suggested->left,
                    Suggested->bottom - Suggested->top, SWP_NOZORDER | SWP_NOACTIVATE);
                return 0;
            }
            case WM_ERASEBKGND:
            {
                RECT Client;
                GetClientRect(Hwnd, &Client);
                FillRect((HDC)W, &Client, Background);
                return 1;
            }
            case WM_TIMER:
                if (W == FlushTimer && Bridge) Bridge->OnTimer();
                return 0;
            case WM_APP_INVOKE:
            {
                std::unique_ptr<std::function<void()>> Work((std::function<void()>*)L);
                (*Work)();
                return 0;
            }
            case WM_APP_PAGE:
            {
                std::unique_ptr<PageMessage> Page((PageMessage*)L);
                auto Service = Parent ? Parent->Bridge.get() : Bridge.get();
                if (Service) Service->OnMessage(Page->Json, Page->Files, Page->FromPopup);
                return 0;
            }
            case WM_CLOSE:
                if (Parent)
                {
                    SavePlacement();
                    DestroyWindow(Hwnd);
                    return 0;
                }
                if (!Bridge || Bridge->RequestClose())
                {
                    SavePlacement();
                    DestroyWindow(Hwnd);
                }
                return 0;
            case WM_DESTROY:
                *Life = false;
                KillTimer(Hwnd, FlushTimer);
                if (Controller) Controller->Close();
                if (Parent)
                {
                    Hwnd = NULL;
                    if (!Parent->Closing && Parent->Bridge) Parent->Bridge->PreviewDocked();
                    return 0;
                }
                Closing = true;
                PostQuitMessage(0);
                return 0;
            }
            return DefWindowProcW(Hwnd, Message, W, L);
        }

        static LRESULT CALLBACK Proc(HWND Hwnd, UINT Message, WPARAM W, LPARAM L)
        {
            if (Message == WM_NCDESTROY)
            {
                SetWindowLongPtrW(Hwnd, GWLP_USERDATA, 0);
                return DefWindowProcW(Hwnd, Message, W, L);
            }
            if (Message == WM_NCCREATE)
            {
                auto Self = (Window*)((CREATESTRUCTW*)L)->lpCreateParams;
                Self->Hwnd = Hwnd;
                SetWindowLongPtrW(Hwnd, GWLP_USERDATA, (LONG_PTR)Self);
            }
            auto Self = (Window*)GetWindowLongPtrW(Hwnd, GWLP_USERDATA);
            return Self != nullptr ? Self->Handle(Message, W, L) : DefWindowProcW(Hwnd, Message, W, L);
        }
    };
}

bool UiHost::Available()
{
    if (GetFileAttributesW((UiFolder() + L"\\index.html").c_str()) == INVALID_FILE_ATTRIBUTES) return false;
    PWSTR Version = nullptr;
    const HRESULT Result = GetAvailableCoreWebView2BrowserVersionString(nullptr, &Version);
    const bool Installed = SUCCEEDED(Result) && Version != nullptr;
    CoTaskMemFree(Version);
    return Installed;
}

bool UiHost::Run()
{
    // WebView2 needs a single-threaded apartment; the main thread is MTA.
    bool Worked = false;
    std::thread Ui([&Worked]
    {
        CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        UsePerMonitorDpi();
        {
            Window Main;
            if (Main.Create())
            {
                MSG Message;
                while (GetMessageW(&Message, NULL, 0, 0) > 0)
                {
                    TranslateMessage(&Message);
                    DispatchMessageW(&Message);
                }
                Worked = !Main.Failed;
            }
            Main.Close();
        }
        CoUninitialize();
    });
    Ui.join();
    return Worked;
}
