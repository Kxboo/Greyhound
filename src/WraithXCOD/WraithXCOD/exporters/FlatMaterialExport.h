#pragma once
#include <fstream>
#include <mutex>
#include "json.hpp"

namespace FlatMaterialExport
{
    // Flat CW batches share one material per name. Later differences do not
    // create variants, overwrite the first description, or abort model export.
    inline std::string Save(const std::string& Directory, const nlohmann::json& Description, bool* Created = nullptr)
    {
        static std::mutex Mutex;
        std::lock_guard<std::mutex> Lock(Mutex);
        if (Created) *Created = false;
        const auto Name = Description.at("Name").get<std::string>();
        const auto Path = Directory + "/" + Name + ".json";
        std::ifstream Existing(Path);
        if (Existing) return Name;
        std::ofstream Output(Path, std::ios::binary); Output << Description.dump(2); Output.close();
        if (!Output) throw std::runtime_error("Could not write material: " + Path);
        if (Created) *Created = true;
        return Name;
    }
}
