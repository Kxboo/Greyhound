#include "shared/RadiantExportResult.h"
#include <cassert>
#include <iostream>

int main()
{
    using nlohmann::json;
    const json BO4{{"status", "exported_with_review"}, {"prefab_geometry_verified", true}};
    const json CW{{"status", "exported"}, {"all_placed_brushes_present", true}};
    assert(RadiantExportResult::Complete(true, true, BO4));
    assert(RadiantExportResult::Complete(true, false, CW));
    // A converter may write a report before a later verification step fails.
    assert(!RadiantExportResult::Complete(false, true, BO4));
    assert(!RadiantExportResult::Complete(false, false, CW));
    assert(!RadiantExportResult::Complete(true, true, CW));
    assert(!RadiantExportResult::Complete(true, false, BO4));
    assert(!RadiantExportResult::Complete(true, true, json{{"status", "failed"}, {"prefab_geometry_verified", true}}));
    assert(!RadiantExportResult::Complete(true, true, json{{"status", "exported_with_review"}}));
    assert(!RadiantExportResult::Complete(true, true, json{{"status", "exported_with_review"}, {"prefab_geometry_verified", "true"}}));
    assert(!RadiantExportResult::Complete(true, true, json::array()));
    assert(!RadiantExportResult::Read(true, true, ""));
    std::cout << "Radiant completion requires producer success and verified report\n";
}
