#pragma once
#include <Windows.h>
#include <fstream>
#include <cstdint>
#include <set>
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
    inline std::string Directory(const std::string& Root, const std::string& Name)
    { return Root+"/"+ModelExportNaming::FileStem(Name); }
    inline bool PerModelBatch(const std::string& Root)
    {
        try {
            std::ifstream In(Root+"/model_export_checkpoint.json");
            nlohmann::json State; if (!In) return false; In>>State;
            return State.at("options").value("layout",std::string())=="per_model_images_mat_info";
        } catch (const std::exception&) { return false; }
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
        } Find{FindFirstFileA((Directory(Root,Name)+"/*.cast").c_str(), &Data)};
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
            if (Match && CompleteCast(Directory(Root,Name)+"/"+File))
                Out.push_back({{"file", File}, {"bytes", FileSize(Directory(Root,Name)+"/"+File)}});
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
                const auto Path = Directory(Root,Name)+"/"+File;
                if (!CompleteCast(Path) || FileSize(Path) != Item.at("bytes").get<uint64_t>()) return false;
            }
            return true;
        }
        return LegacySingleLod && CompleteCast(Directory(Root,Name)+"/"+ModelExportNaming::FileStem(Name)+".cast");
    }
    // The user normally reopens the original placements JSON, not our copied
    // JSON inside the batch. Locate its model set among existing batch folders.
    inline std::string FindExisting(const std::string& Root, const std::set<std::string>& Names,
        const nlohmann::json& Options)
    {
        std::string Best;
        size_t BestCount=0;
        WIN32_FIND_DATAA Data{};
        const auto Handle=FindFirstFileA((Root+"/*").c_str(),&Data);
        if (Handle==INVALID_HANDLE_VALUE) return {};
        do {
            if (!(Data.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY) ||
                (Data.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT) || Data.cFileName[0]=='.') continue;
            const auto Folder=Root+"/"+Data.cFileName;
            try {
                nlohmann::json Rows,Ids,State;
                std::ifstream Input(Folder+"/static_models.json"); if (!Input) continue; Input>>Rows;
                std::set<std::string> Found;
                for (const auto& Row:Rows)
                    Found.insert(Row.value("SourceName",Row.at("Name").get<std::string>()));
                if (Found!=Names) continue;
                std::ifstream Checkpoint(Folder+"/model_export_checkpoint.json");
                if (!Checkpoint) continue; Checkpoint>>State;
                if (State.at("options")!=Options) continue;
                std::ifstream IdentityFile(Folder+"/model_identities.json");
                if (!IdentityFile) continue; IdentityFile>>Ids;
                size_t Count=0;
                for (const auto& Name:Names)
                    if (Completed(Folder,Name,Ids,State.at("completed_models"),false)) ++Count;
                if (Count>BestCount) { BestCount=Count; Best=Folder; }
            } catch (const std::exception&) { /* Ignore unrelated/incomplete metadata. */ }
        } while (FindNextFileA(Handle,&Data));
        FindClose(Handle);
        return Best;
    }
}
