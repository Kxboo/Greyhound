#include "../src/WraithXCOD/WraithXCOD/SalukiNameIndex.h"
#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>

int main(int argc, char** argv)
{
    using namespace SalukiNames;
    Dictionary Names{{1, "already_decoded"}, {2, "xmodel_2"}, {3, "a_real_name"}};
    assert(!InsertFallback(Names, 1, "replacement"));
    assert(InsertFallback(Names, 2, "saluki_model"));
    assert(InsertFallback(Names, 4, "new_image"));
    assert(!InsertFallback(Names, 4, "conflicting_duplicate"));
    assert(!InsertFallback(Names, 5, "xmodel_5"));
    assert(!InsertFallback(Names, 6, std::string("bad\0name", 8)));
    assert(Names.at(1) == "already_decoded" && Names.at(2) == "saluki_model");
    assert(Names.at(3) == "a_real_name" && Names.at(4) == "new_image");
    std::istringstream Csv("\xEF\xBB\xBF\"000A\",\"folder/name, with \"\"quotes\"\"\"\r\n0xB,another\n\n");
    assert(ReadCsv(Csv, [&](uint64_t Key, const std::string& Value) { InsertFallback(Names, Key, Value); }) == 2);
    assert(Names.at(10) == "folder/name, with \"quotes\"");
    assert(Names.at(11) == "another");
    uint64_t Value;
    assert(!Hex("nope", Value) && !Hex("10000000000000000", Value) && !Hex("", Value));
    assert(Hex("FFFFFFFFFFFFFFFF", Value) && Value == UINT64_MAX);
    std::istringstream EmptyName("1,\n");
    ReadCsv(EmptyName, [&](uint64_t Hash, const std::string& Name) { assert(!InsertFallback(Names, Hash, Name)); });
    for (const auto* Ignored : {"abc", "zz,name", "1,a,extra", ">>>>>>> Stashed changes"})
    {
        std::istringstream Input(Ignored);
        assert(ReadCsv(Input, [](uint64_t, const std::string&) { assert(false); }) == 0);
    }
    for (const auto* Invalid : {"1,\"unfinished"})
    {
        bool Threw = false;
        try { std::istringstream Input(Invalid); ReadCsv(Input, [](uint64_t, const std::string&) {}); }
        catch (const std::exception&) { Threw = true; }
        assert(Threw);
    }
    std::string Data("first\0second\0", 13);
    const uint64_t Keys[] = {0xF123456789ABCDEF, 99};
    Data.append(reinterpret_cast<const char*>(Keys), sizeof(Keys));
    const uint32_t Header[] = {0x42444E50, 2, static_cast<uint32_t>(Data.size()), static_cast<uint32_t>(Data.size())};
    std::string Cdb(reinterpret_cast<const char*>(Header), sizeof(Header)); Cdb += Data;
    auto Copy = [](const char* From, char* To, uint32_t Packed, uint32_t Size) { assert(Packed == Size); std::memcpy(To, From, Size); return Size; };
    std::istringstream Binary(Cdb);
    assert(ReadCdb(Binary, [&](uint64_t Hash, const std::string& Name) { InsertFallback(Names, Hash & AssetMask, Name); }, Copy) == 2);
    assert(Names.at(0x123456789ABCDEF) == "first" && Names.at(99) == "second");
    for (int Case = 0; Case < 5; ++Case)
    {
        auto Broken = Cdb;
        if (Case == 0) Broken.resize(10);
        if (Case == 1) Broken[0] = 0;
        if (Case == 2) Broken.pop_back();
        if (Case == 3) Broken[16 + 5] = 'x';
        if (Case == 4) Broken.push_back('x');
        bool Threw = false; size_t Added = 0;
        try { std::istringstream Input(Broken); ReadCdb(Input, [&](uint64_t, const std::string&) { ++Added; }, Copy); }
        catch (const std::exception&) { Threw = true; }
        assert(Threw && Added == 0);
    }
    size_t Rows = 0;
    for (int I = 1; I < argc; ++I)
    {
        std::ifstream Input(argv[I], std::ios::binary);
        assert(Input);
        try { Rows += ReadCsv(Input, [](uint64_t, const std::string&) {}); }
        catch (const std::exception& E) { std::cerr << argv[I] << ": " << E.what() << '\n'; return 1; }
    }
    std::cout << "Saluki parser / fallback tests passed; source CSV rows: " << Rows << '\n';
}
