#pragma once

#include <functional>
#include <string>
#include <vector>
#include "json.hpp"
#include "assets/preview/PreviewPolicy.h"

class CoDAsset_t;

namespace PreviewData
{
    struct Result
    {
        nlohmann::json metadata;
        std::vector<uint8_t> bytes;
        std::string error;
        bool cancelled = false;
    };

    // Call on a COM-initialized worker while holding the owner's game-data lock.
    // The asset and CoDAssets game/cache globals must live through this call.
    // No exporter or output path is used. Cancellation is cooperative between
    // reader operations; existing readers themselves are synchronous.
    Result Build(const CoDAsset_t* asset, const Options& options = Options{},
        const std::function<bool()>& cancelled = {});
}
