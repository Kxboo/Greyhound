#pragma once
#include <fstream>
#include <functional>
#include <vector>
#include "FileSystems.h"
#include "Strings.h"
#include "json.hpp"

// The versioned Python converter is shipped in tools beside the
// executable, packaged by tools/shared/runtime/package_runtime.py. It only
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
    inline std::string Bundle() {return FileSystems::CombinePath(FileSystems::GetApplicationPath(),"tools");}

    // Mirrors shared/brushes/cw_export_layout.py map_name(): the map path is only
    // recoverable by hashing candidates back to the map hash, and these four are
    // the only names currently known. Keep both lists in step; the stem is passed
    // to the converter as --map-name so the folder and the .map files match.
    inline std::string MapStem(uint64_t MapHash,const std::string& MapPath)
    {
        auto Hash63=[](const std::string& Text) {
            uint64_t Value=0xcbf29ce484222325ull;
            for(unsigned char C:Text)Value=(Value^C)*0x100000001b3ull;
            return Value&0x7FFFFFFFFFFFFFFFull;
        };
        std::vector<std::string> Candidates{MapPath};
        for(const auto* Name:{"zm_platinum","zm_silver","zm_gold","zm_tungsten"})
            Candidates.push_back(std::string("maps/zm/")+Name+".d3dbsp");
        for(const auto& Candidate:Candidates)
            if(Candidate.size()>7 && Candidate.compare(Candidate.size()-7,7,".d3dbsp")==0 && Hash63(Candidate)==MapHash)
                return FileSystems::GetFileNamePurgeExtensions(Candidate);
        return Strings::Format("cw_map_%016llx",MapHash);
    }
    inline bool Available()
    {
        for(const auto* Name:{"runtime/python.exe","shared/runtime/export_brushes.py","manifest.json","black_ops_3/reference/bo3_reference.json"})
            if(GetFileAttributesA(FileSystems::CombinePath(Bundle(),Name).c_str())==INVALID_FILE_ATTRIBUTES)return false;
        return true;
    }
    inline bool VerifyRuntime(const std::string& Directory, const std::string& SourceReport="")
    {
        const auto Python=Strings::ToUnicodeString(FileSystems::CombinePath(Bundle(),"runtime/python.exe"));
        const auto Script=SourceReport.empty()?"shared/runtime/verify_runtime.py":"shared/runtime/verify_saved_export.py";
        const auto ReportName=SourceReport.empty()?"runtime_check.json":"saved_export_check.json";
        std::wstring Command=Quote(Python)+L" -I "+Quote(Strings::ToUnicodeString(FileSystems::CombinePath(Bundle(),Script)))+
            L" --output "+Quote(Strings::ToUnicodeString(FileSystems::CombinePath(Directory,ReportName)));
        if(!SourceReport.empty())Command+=L" --input "+Quote(Strings::ToUnicodeString(SourceReport));
        std::vector<wchar_t> Buffer(Command.begin(),Command.end());Buffer.push_back(0);
        STARTUPINFOW Start{};Start.cb=sizeof(Start);PROCESS_INFORMATION Process{};
        if(!CreateProcessW(Python.c_str(),Buffer.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&Start,&Process)) {
            const auto Error=GetLastError();
            std::ofstream Report(FileSystems::CombinePath(Directory,ReportName));
            Report<<nlohmann::json({{"status","failed"},{"error","Could not launch packaged runtime checker"},{"win32_error",Error}}).dump(2);
            return false;
        }
        CloseHandle(Process.hThread);
        // Worker-thread wait; hashing a large saved capture can take minutes.
        // Startup/import checks retain the shorter timeout.
        const auto Wait=WaitForSingleObject(Process.hProcess,SourceReport.empty()?120000:1800000);
        if(Wait!=WAIT_OBJECT_0)TerminateProcess(Process.hProcess,1);
        DWORD Code=1;GetExitCodeProcess(Process.hProcess,&Code);CloseHandle(Process.hProcess);
        if(Wait!=WAIT_OBJECT_0) {
            std::ofstream Report(FileSystems::CombinePath(Directory,ReportName));
            Report<<nlohmann::json({{"status","failed"},{"error","Runtime checker timed out or wait failed"}}).dump(2);
            return false;
        }
        try {
            std::ifstream Input(FileSystems::CombinePath(Directory,ReportName));nlohmann::json Report;Input>>Report;
            return Code==0 && Report.value("status",std::string())=="passed";
        } catch(const std::exception&) {
            std::ofstream Report(FileSystems::CombinePath(Directory,ReportName));
            Report<<nlohmann::json({{"status","failed"},{"error","Checker exited without a readable JSON report"},{"exit_code",Code}}).dump(2);
            return false;
        }
    }
    inline bool Run(const std::string& Capture,const std::string& Output,const std::string& MapPath,const Progress& Notify,
        bool AutoTypes=true,const std::string& TriggerCapture="",const std::string& MapName="",bool BO4=false,
        bool FloatTriangles=false,bool ModelTriangles=false)
    {
        const auto Python=Strings::ToUnicodeString(FileSystems::CombinePath(Bundle(),"runtime/python.exe"));
        std::wstring Command=Quote(Python)+L" -I "+Quote(Strings::ToUnicodeString(FileSystems::CombinePath(Bundle(),"shared/runtime/export_brushes.py")))+
            L" --capture "+Quote(Strings::ToUnicodeString(Capture))+L" --output "+Quote(Strings::ToUnicodeString(Output))+
            L" --map-path "+Quote(Strings::ToUnicodeString(MapPath));
        if(BO4)Command+=L" --game bo4";
        if(AutoTypes)Command+=L" --auto-types";
        if(!TriggerCapture.empty())Command+=L" --trigger-capture "+Quote(Strings::ToUnicodeString(TriggerCapture));
        if(!MapName.empty())Command+=L" --map-name "+Quote(Strings::ToUnicodeString(MapName));
        if(FloatTriangles)Command+=L" --float-triangles";
        if(ModelTriangles)Command+=L" --model-triangles";
        std::vector<wchar_t> Buffer(Command.begin(),Command.end());Buffer.push_back(0);
        STARTUPINFOW Start{};Start.cb=sizeof(Start);PROCESS_INFORMATION Process{};
        if(!CreateProcessW(Python.c_str(),Buffer.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,nullptr,&Start,&Process)) {
            if(Notify)Notify(0,"Could not start bundled brush converter. Reinstall the tools folder.");return false;
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
            if(BO4)return Report.value("status",std::string())=="exported_with_review" && Report.value("prefab_geometry_verified",false);
            return Report.value("status",std::string())=="exported" && Report.value("all_placed_brushes_present",false);
        } catch(const std::exception&) {return false;}
    }
}
