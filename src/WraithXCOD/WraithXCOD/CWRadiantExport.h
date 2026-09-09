#pragma once
#include <fstream>
#include <functional>
#include <vector>
#include "FileSystems.h"
#include "Strings.h"
#include "json.hpp"

// The versioned Python converter is shipped next to the executable. It only
// reads saved evidence; no live game access, shells, or BO3 tools are involved.
namespace CWRadiantExport
{
    using Progress = std::function<void(uint32_t, const std::string&)>;
    inline std::wstring Quote(const std::wstring& Value)
    {
        std::wstring Out=L"\""; size_t Slashes=0;
        for (auto C:Value) {
            if(C==L'\\') {++Slashes;continue;}
            Out.append(C==L'"'?Slashes*2+1:Slashes,L'\\');Slashes=0;Out+=C;
        }
        Out.append(Slashes*2,L'\\');return Out+L"\"";
    }
    inline std::string Bundle() {return FileSystems::CombinePath(FileSystems::GetApplicationPath(),"brush_export");}
    inline bool Available()
    {
        for(const auto* Name:{"runtime/python.exe","export_brushes.py","manifest.json","bo3_reference.json"})
            if(GetFileAttributesA(FileSystems::CombinePath(Bundle(),Name).c_str())==INVALID_FILE_ATTRIBUTES)return false;
        return true;
    }
    inline bool Run(const std::string& Capture,const std::string& Output,const std::string& MapPath,const Progress& Notify,
        bool AutoTypes=true,const std::string& TriggerCapture="")
    {
        const auto Python=Strings::ToUnicodeString(FileSystems::CombinePath(Bundle(),"runtime/python.exe"));
        std::wstring Command=Quote(Python)+L" -I "+Quote(Strings::ToUnicodeString(FileSystems::CombinePath(Bundle(),"export_brushes.py")))+
            L" --capture "+Quote(Strings::ToUnicodeString(Capture))+L" --output "+Quote(Strings::ToUnicodeString(Output))+
            L" --map-path "+Quote(Strings::ToUnicodeString(MapPath));
        if(AutoTypes)Command+=L" --auto-types";
        if(!TriggerCapture.empty())Command+=L" --trigger-capture "+Quote(Strings::ToUnicodeString(TriggerCapture));
        std::vector<wchar_t> Buffer(Command.begin(),Command.end());Buffer.push_back(0);
        STARTUPINFOW Start{};Start.cb=sizeof(Start);PROCESS_INFORMATION Process{};
        if(!CreateProcessW(Python.c_str(),Buffer.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&Start,&Process)) {
            if(Notify)Notify(0,"Could not start bundled brush converter. Reinstall the brush_export folder.");return false;
        }
        CloseHandle(Process.hThread);
        auto ReadStatus=[&]() {
            try {
                const auto Path=Strings::ToUnicodeString(FileSystems::CombinePath(Capture,"radiant_progress.json"));
                // Atomic rename requires delete-sharing on Windows. std::ifstream
                // denied that sharing and occasionally killed the Python export.
                const auto File=CreateFileW(Path.c_str(),GENERIC_READ,
                    FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
                if(File!=INVALID_HANDLE_VALUE) {
                    LARGE_INTEGER Size{};std::string Text;DWORD Read=0;
                    if(GetFileSizeEx(File,&Size) && Size.QuadPart>0 && Size.QuadPart<=1024*1024) {
                        Text.resize(static_cast<size_t>(Size.QuadPart));
                        if(!ReadFile(File,&Text[0],static_cast<DWORD>(Text.size()),&Read,nullptr) || Read!=Text.size())Text.clear();
                    }
                    CloseHandle(File);
                    if(!Text.empty()) { const auto State=nlohmann::json::parse(Text);if(Notify)Notify(State.value("percent",0u),State.value("stage",std::string("Converting brushes..."))); }
                }
            } catch(const std::exception&) {} // An atomic progress-file replacement may race a read.
        };
        while(WaitForSingleObject(Process.hProcess,250)==WAIT_TIMEOUT)ReadStatus();
        DWORD Code=1;GetExitCodeProcess(Process.hProcess,&Code);CloseHandle(Process.hProcess);ReadStatus();
        if(Code!=0) {
            if(Notify)Notify(0,"Brush conversion failed. See radiant_error.log and radiant_progress.json in the capture folder.");return false;
        }
        try {
            std::ifstream Input(FileSystems::CombinePath(Output,"metadata/export_report.json"));nlohmann::json Report;Input>>Report;
            return Report.value("status",std::string())=="exported" && Report.value("all_placed_brushes_present",false);
        } catch(const std::exception&) {return false;}
    }
}
