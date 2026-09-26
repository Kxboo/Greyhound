#pragma once
#include <fstream>
#include <string>
#include "FileSystems.h"

namespace BO4NameDatabase
{
    constexpr const char* Files[] = {"fnv1a_xanims.wni", "fnv1a_ximages.wni",
        "fnv1a_xmaterials.wni", "fnv1a_xmodels.wni", "fnv1a_xsounds.wni"};

    inline std::string Root(const std::string& Provider)
    {
        return FileSystems::CombinePath(FileSystems::GetApplicationPath(),
            Provider=="echo000" ? "package_index\\echo000_bo4" : "package_index");
    }

    inline bool Ready(const std::string& Provider)
    {
        if (Provider!="bundled" && Provider!="echo000") return false;
        for (const auto* File:Files)
            if (!FileSystems::FileExists(FileSystems::CombinePath(Root(Provider),File))) return false;
        return Provider!="echo000" || FileSystems::FileExists(FileSystems::CombinePath(Root(Provider),"source.json"));
    }
}
