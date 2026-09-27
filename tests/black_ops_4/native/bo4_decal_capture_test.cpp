#include "games/black_ops_4/capture/BO4DecalCapture.h"
#include <stdexcept>
#include <vector>

int main()
{
    using namespace BO4DecalCapture;
    constexpr uint64_t Base = 0x100000;
    std::vector<uint8_t> Bytes(WorldBytes * 3);
    uint64_t World = 0;
    auto Check = [](bool Value) { if (!Value) throw std::runtime_error("BO4 decal pool validation failed"); };
    auto Link = [&](uint32_t Slot, uint64_t Next) {
        std::memcpy(Bytes.data() + size_t(Slot) * WorldBytes, &Next, sizeof Next);
    };
    auto Select = [&](uint64_t Head, uint32_t Loaded = 1) {
        return SelectWorld(Base, WorldBytes, 3, Loaded, Head, Bytes.data(), Bytes.size(), World);
    };
    Link(0, Base + 2 * WorldBytes);
    Check(Select(Base).empty() && World == Base + WorldBytes);
    // A cyclic or truncated free list must not turn a free slot into the loaded world.
    Link(2, Base);
    Check(!Select(Base).empty() && World == 0);
    Link(2, 0);
    Link(0, 0);
    Check(!Select(Base).empty() && World == 0);
    Link(0, Base + 3 * WorldBytes);
    Check(!Select(Base).empty());
    Link(0, Base + WorldBytes + 1);
    Check(!Select(Base).empty());
    Check(!Select(Base - 1).empty());
    Check(!Select(0).empty());
    Check(!Select(Base, 0).empty());
    Check(!Select(Base, 2).empty());
    Check(!SelectWorld(Base, WorldBytes, 3, 1, Base, Bytes.data(), Bytes.size()-1, World).empty());
    Check(!SelectWorld(Base, WorldBytes, 17, 1, 0, Bytes.data(), Bytes.size(), World).empty());
    Check(!SelectWorld(Base, WorldBytes+1, 3, 1, 0, Bytes.data(), Bytes.size(), World).empty());
    Check(!SelectWorld(UINT64_MAX-WorldBytes, WorldBytes, 3, 1, 0, Bytes.data(), Bytes.size(), World).empty());
    Check(SelectWorld(Base, WorldBytes, 1, 1, 0, Bytes.data(), WorldBytes, World).empty() && World == Base);
    // Classification uses primary world references, never forward-material fields or names.
    std::vector<uint8_t> Records(216 * 4);
    uint64_t Primary = 0x123400, Other = 0x234500;
    std::memcpy(Records.data() + 0xB8, &Primary, 8);
    std::memcpy(Records.data() + 216 + 0xB8, &Primary, 8);
    std::memcpy(Records.data() + 216 * 2 + 0xB8, &Other, 8);
    std::memcpy(Records.data() + 216 * 3 + 0xC0, &Other, 8);
    const auto Uses = MaterialUses(Records);
    Check(Uses.size() == 2 && Uses.at(Primary) == 2 && Uses.at(Other) == 1);
    Check(MaterialUses({}).empty());
    bool Rejected = false;
    Records.pop_back();
    try { MaterialUses(Records); } catch (const std::runtime_error&) { Rejected = true; }
    Check(Rejected);
    return 0;
}
