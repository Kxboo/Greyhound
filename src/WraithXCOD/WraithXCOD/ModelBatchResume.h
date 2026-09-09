#pragma once
#include <Windows.h>
#include <fstream>
#include <cstdint>
#include "json.hpp"
#include "ModelExportNaming.h"

namespace ModelBatchResume
{
    // Detect interrupted writes using the CAST root's declared file length.
    // This is a completeness check, not a geometry correctness test.
    inline bool CompleteCast(const std::string& Path)
    {
        std::ifstream In(Path, std::ios::binary);
        uint32_t H[10]{};
        if (!In.read(reinterpret_cast<char*>(H), sizeof(H))) return false;
        In.seekg(0, std::ios::end);
        return H[0] == 0x74736163 && H[1] == 1 && H[2] == 1 &&
            H[4] == 0x746f6f72 && H[5] >= 24 && In.tellg() == uint64_t(H[5]) + 16;
    }
    inline uint64_t FileSize(const std::string& Path)
    {
        std::ifstream In(Path,std::ios::binary|std::ios::ate);
        return In ? static_cast<uint64_t>(In.tellg()) : 0;
    }
    inline nlohmann::json Files(const std::string& Root, const std::string& Name)
    {
        auto Out = nlohmann::json::array();
        const auto Stem = ModelExportNaming::FileStem(Name);
        WIN32_FIND_DATAA Data{};
        struct Search
        {
            HANDLE Handle;
            ~Search() { if (Handle != INVALID_HANDLE_VALUE) FindClose(Handle); }
        } Find{FindFirstFileA((Root+"/models/*.cast").c_str(), &Data)};
        if (Find.Handle == INVALID_HANDLE_VALUE) return Out;
        do
        {
            const std::string File = Data.cFileName;
            bool Match = File == Stem + ".cast";
            const auto Prefix = Stem + "_LOD";
            if (File.compare(0, Prefix.size(), Prefix) == 0 && File.size() >= Prefix.size()+6 && File.substr(File.size()-5) == ".cast")
            {
                const auto Index = File.substr(Prefix.size(), File.size() - Prefix.size() - 5);
                Match = !Index.empty() && Index.find_first_not_of("0123456789") == std::string::npos;
            }
            if (Match && CompleteCast(Root+"/models/"+File))
                Out.push_back({{"file", File}, {"bytes", FileSize(Root+"/models/"+File)}});
        } while (FindNextFileA(Find.Handle,&Data));
        return Out;
    }
    inline bool Completed(const std::string& Root, const std::string& Name,
        const nlohmann::json& Identities, const nlohmann::json& CompletedModels, bool LegacySingleLod)
    {
        auto Key = ModelExportNaming::FileStem(Name);
        for (auto& C : Key) C = char(std::tolower(static_cast<unsigned char>(C)));
        if (!Identities.contains(Key) || Identities.at(Key) != Name) return false;
        if (CompletedModels.contains(Name))
        {
            const auto& List = CompletedModels.at(Name);
            if (!List.is_array() || List.empty()) return false;
            for (const auto& Item : List)
            {
                const auto File = Item.at("file").get<std::string>();
                if (File.empty() || File.find_first_of("/\\:") != std::string::npos || File=="." || File=="..") return false;
                const auto Path = Root+"/models/"+File;
                if (!CompleteCast(Path) || FileSize(Path) != Item.at("bytes").get<uint64_t>()) return false;
            }
            return true;
        }
        return LegacySingleLod && CompleteCast(Root+"/models/"+ModelExportNaming::FileStem(Name)+".cast");
    }
}
