// Offline migration uses exactly the same naming code as the GUI exporter.
#include "../src/WraithXCOD/WraithXCOD/ModelExportNaming.h"
#include "../src/WraithX/WraithX/json.hpp"
#include <fstream>
#include <iostream>
int main(int argc, char** argv)
{
    if (argc != 3) { std::cerr << "Usage: normalize_placement_names INPUT_JSON NEW_OUTPUT_JSON\n"; return 1; }
    try
    {
        if (std::ifstream(argv[2]).good()) throw std::runtime_error("Output already exists");
        std::ifstream Input(argv[1]); nlohmann::json Doc; Input >> Doc;
        auto& Rows = Doc.is_array() ? Doc : Doc.at("StaticModels");
        if (!Rows.is_array()) throw std::runtime_error("Expected placement array");
        size_t Changed = 0;
        for (auto& Row : Rows)
        {
            const auto Before = Row.at("Name");
            ModelExportNaming::PublishPlacementName(Row);
            if (Row.at("Name") != Before) ++Changed;
        }
        std::ofstream Output(argv[2], std::ios::binary); Output << Rows.dump(2); Output.close();
        if (!Output) throw std::runtime_error("Output write failed");
        std::cout << Rows.size() << " placements; " << Changed << " cleaned names\n";
    }
    catch (const std::exception& E) { std::cerr << E.what() << '\n'; return 1; }
}
