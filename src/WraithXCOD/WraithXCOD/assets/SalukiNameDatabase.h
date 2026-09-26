#pragma once
#include <functional>
#include <string>
#include <vector>
#include "WraithNameIndex.h"

namespace SalukiNameDatabase
{
    constexpr const char* ProjectUrl = "https://github.com/echo000/cod-name-db";
    struct File { std::string Stem, Path; };
    std::vector<File> Discover(const std::string& Folder);
    size_t Validate(const std::string& Folder);
    void Apply(WraithNameIndex& Index, const std::vector<std::string>& Stems, uint64_t Mask = UINT64_MAX);
    void ApplyAssets(WraithNameIndex& Index);
    void ApplyStrings(WraithNameIndex& Index, bool MaskHashes = true);
    std::string ResolveMetadata(const std::string& Table, uint64_t Hash, const std::string& Fallback);
    // Returns a fully validated version directory. Never changes a user's folder.
    std::string Update(bool Force, const std::function<void(const std::string&)>& Progress = {});
    void AutoUpdate();
}
