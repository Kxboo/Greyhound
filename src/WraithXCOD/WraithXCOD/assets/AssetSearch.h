#pragma once

#include <string>
#include <vector>
#include "assets/CoDAssetType.h"

namespace AssetSearch
{
    // Returns the assets matching a Greyhound search string, in their original order.
    std::vector<CoDAsset_t*> Filter(const std::string& Text, const std::vector<CoDAsset_t*>& Assets);
}
