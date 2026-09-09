#include "../src/WraithXCOD/WraithXCOD/ModelExportNaming.h"
#include "../src/WraithX/WraithX/json.hpp"
#include <cassert>
#include <iostream>
int main()
{
    using namespace ModelExportNaming;
    assert(FileStem("*doorframe_single_4.map_psh7ma2cqrgytjnmi6llllbdbn_16") == "doorframe_single_4");
    assert(FileStem("%2Adoorframe_single_4.map_build_16") == "doorframe_single_4");
    assert(FileStem("%2adoorframe_single_4.MAP_build_16") == "doorframe_single_4");
    assert(FileStem("*_zm_silver_terrain_vista.map_a_16") == "_zm_silver_terrain_vista");
    assert(Escape(Stem("*stairs.map_variant_16") + "_LOD3") == "stairs_LOD3");
    assert(FileStem("p8_wmd_generator") == "p8_wmd_generator");
    assert(FileStem("xmodel_adb096a827c177f") == "xmodel_adb096a827c177f");
    assert(FileStem("ordinary.map_name") == "ordinary.map_name");
    assert(FileStem("*x.maple") == "%2Ax.maple");
    assert(FileStem("*.map_bad") == "%2A.map_bad");
    assert(FileStem("*folder/thing.map_id") == "folder%2Fthing");
    assert(FileStem("*stairs.map_a") == FileStem("*stairs.map_b")); // Requires identity guard, never dedup by this stem.
    assert(LodSuffix(false, false, 0).empty());
    assert(LodSuffix(false, false, 3).empty());
    assert(LodSuffix(true, false, 0) == "_LOD0");
    assert(LodSuffix(true, false, 3) == "_LOD3");
    assert(LodSuffix(false, true, 3) == "_LOD3");
    nlohmann::json Row = {{"Name","*stairs.map_a"},{"Position",{1,2,3}},
        {"RotationQuaternion",{0,0,0,1}},{"ModelScale",2.5},{"ExportName","stairs"}};
    const auto Original = Row;
    PublishPlacementName(Row);
    assert(Row["Name"] == "stairs" && Row["SourceName"] == "*stairs.map_a");
    assert(Row["Position"] == Original["Position"] && Row["RotationQuaternion"] == Original["RotationQuaternion"] && Row["ModelScale"] == Original["ModelScale"]);
    assert(!Row.contains("ExportName"));
    const auto Published = Row; PublishPlacementName(Row); assert(Row == Published);
    SourceLookup Lookup; Lookup.Add("*stairs.map_a"); Lookup.Add("*stairs.map_a");
    assert(Lookup.Resolve("stairs", "") == "*stairs.map_a");
    assert(Lookup.Resolve("*stairs.map_a", "") == "*stairs.map_a");
    Lookup.Add("*stairs.map_b");
    assert(Lookup.Resolve("stairs", "*stairs.map_b") == "*stairs.map_b");
    bool Ambiguous = false;
    try { Lookup.Resolve("stairs", ""); } catch (const std::runtime_error&) { Ambiguous = true; }
    assert(Ambiguous);
    assert(Lookup.Resolve("missing", "") == "missing");
    std::cout << "model export naming tests passed\n";
}
