#pragma once

#include <string>
#include <Windows.h>
#include "CoDAssets.h"
#include "FileSystems.h"
#include "Strings.h"

// Reserves the run folder a map-level export writes into. Every export lands in
// exported_files\<game>\<category>\<run>, never loose in exported_files, and a
// repeated export never overwrites an earlier one.
namespace ExportRun
{
    // "run" becomes run_01, run_02...; any other name gets a plain _2, _3 suffix
    // only once it is taken, so the common case stays a bare readable name.
    inline std::string Candidate(const std::string& Name, unsigned Attempt)
    {
        if (Name == "run") return Strings::Format("run_%02u", Attempt + 1);
        return Attempt ? Name + "_" + std::to_string(Attempt + 1) : Name;
    }

    // Creates exported_files\<game>\<Category>\<Name>, suffixing until the name
    // is free. Empty when the loaded game has no export folder.
    inline std::string Reserve(const std::string& Category, const std::string& Name)
    {
        const auto Root = CoDAssets::BuildMapExportPath(Category);
        if (Root.empty()) return {};
        FileSystems::CreateDirectory(Root);
        for (unsigned Attempt = 0; Attempt < 1000; ++Attempt)
        {
            const auto Path = FileSystems::CombinePath(Root, Candidate(Name, Attempt));
            if (CreateDirectoryA(Path.c_str(), nullptr)) return Path;
            if (GetLastError() != ERROR_ALREADY_EXISTS) break;
        }
        return {};
    }

    // Renames a folder Reserve() handed out, once the export knows what to call
    // it. Returns Reserved unchanged when the rename cannot be made, so a locked
    // folder costs a tidy name rather than the export.
    inline std::string Rename(const std::string& Reserved, const std::string& Name)
    {
        if (Reserved.empty() || Name.empty()) return Reserved;
        const auto Root = FileSystems::GetDirectoryName(Reserved);
        for (unsigned Attempt = 0; Attempt < 1000; ++Attempt)
        {
            const auto Path = FileSystems::CombinePath(Root, Candidate(Name, Attempt));
            if (Path == Reserved) return Reserved;
            if (FileSystems::DirectoryExists(Path)) continue;
            if (MoveFileA(Reserved.c_str(), Path.c_str())) return Path;
            if (GetLastError() != ERROR_ALREADY_EXISTS) break;
        }
        return Reserved;
    }
}
