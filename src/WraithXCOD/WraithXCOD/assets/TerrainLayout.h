#pragma once

#include <string>
#include <Windows.h>
#include "Strings.h"
#include "FileSystems.h"

namespace TerrainLayout
{
    constexpr const char* Source = "_source";
    constexpr const char* Game = "black_ops_3";
    constexpr const char* Geometry = "terrain_geometry_only";
    constexpr const char* Materials = "terrain_with_materials";
    constexpr const char* Logs = "logs";

    // Atomically reserve a fresh directory, including for repeated calls in
    // one millisecond. Existing captures never participate in this operation.
    inline std::string CreateRun(const std::string& MapRoot)
    {
        FileSystems::CreateDirectory(MapRoot);
        SYSTEMTIME T{}; GetSystemTime(&T);
        const auto Name = Strings::Format(
            "%04u-%02u-%02u_%02u%02u%02u_%03uZ_pid%lu_%llu",
            T.wYear, T.wMonth, T.wDay, T.wHour, T.wMinute, T.wSecond,
            T.wMilliseconds, GetCurrentProcessId(), GetTickCount64());
        for (unsigned Attempt = 0; Attempt < 100; ++Attempt)
        {
            const auto Path = FileSystems::CombinePath(MapRoot,
                Name + (Attempt ? "_" + std::to_string(Attempt) : ""));
            if (CreateDirectoryA(Path.c_str(), nullptr)) return Path;
            if (GetLastError() != ERROR_ALREADY_EXISTS) break;
        }
        return {};
    }
}
