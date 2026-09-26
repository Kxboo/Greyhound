#pragma once

#include <cstdint>

// A structure that represents game offset information
struct DBGameInfo
{
    uint64_t DBAssetPools;
    uint64_t DBPoolSizes;
    uint64_t StringTable;
    uint64_t ImagePackageTable;

    DBGameInfo(uint64_t Pools, uint64_t Sizes, uint64_t Strings, uint64_t Package);
};

// -- Contains structures for various game asset / memory formats

#include "games/quantum_solace/reader/GameQuantumSolaceAssetLayouts.h"
#include "games/world_at_war/reader/GameWorldAtWarAssetLayouts.h"
#include "games/black_ops/reader/GameBlackOpsAssetLayouts.h"
#include "games/black_ops_2/reader/GameBlackOps2AssetLayouts.h"
#include "games/black_ops_3/reader/GameBlackOps3AssetLayouts.h"
#include "games/black_ops_4/reader/GameBlackOps4AssetLayouts.h"
#include "games/modern_warfare/reader/GameModernWarfareAssetLayouts.h"
#include "games/modern_warfare_2/reader/GameModernWarfare2AssetLayouts.h"
#include "games/modern_warfare_3/reader/GameModernWarfare3AssetLayouts.h"
#include "games/ghosts/reader/GameGhostsAssetLayouts.h"
#include "games/advanced_warfare/reader/GameAdvancedWarfareAssetLayouts.h"
#include "games/modern_warfare_remastered/reader/GameModernWarfareRMAssetLayouts.h"
#include "games/infinite_warfare/reader/GameInfiniteWarfareAssetLayouts.h"
#include "games/world_war_2/reader/GameWorldWar2AssetLayouts.h"
#include "games/modern_warfare_4/reader/GameModernWarfare4AssetLayouts.h"
#include "games/cold_war/reader/GameBlackOpsCWAssetLayouts.h"
#include "games/vanguard/reader/GameVanguardAssetLayouts.h"
