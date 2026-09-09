#include "../src/WraithXCOD/WraithXCOD/XSUBObjectLayout.h"
#include <cassert>
#include <fstream>
#include <iterator>
#include <iostream>
#include <filesystem>
using namespace XSUBObjectLayout;
void Put(std::vector<uint8_t>& D, size_t O, uint32_t V) { std::memcpy(D.data()+O,&V,4); }
int main(int argc, char** argv)
{
    std::vector<Block> B;
    std::vector<uint8_t> D(256);
    Put(D,0,2); Put(D,8,4); Put(D,12,0x08000008);
    assert(Parse(D.data(),D.size(),0,B) && B.size()==2 && B[0].Offset==128 && B[1].Offset==132);
    assert(Parse(D.data(),140,0,B)); // Last payload without padding.
    Put(D,12,0x08ffffff);
    assert(!Parse(D.data(),D.size(),0,B) && B.empty()); // Cannot reach the next object.
    Put(D,12,0x08000003);
    assert(!Parse(D.data(),D.size(),0,B)); // Oodle size-prefix underflow.
    Put(D,0,256); Put(D,8,0);
    assert(!Parse(D.data(),D.size(),0,B)); // Truncated extended command table.
    Put(D,0,0); assert(!Parse(D.data(),D.size(),0,B));
    Put(D,0,257); assert(!Parse(D.data(),D.size(),0,B));
    assert(!Parse(nullptr,0,0,B));
    D.assign(264,0); Put(D,0,31); Put(D,8,4);
    assert(Parse(D.data(),136,0,B) && B.size()==31 && B[0].Offset==132);
    D.assign(256,0); Put(D,0,1); Put(D,8,4);
    assert(Parse(D.data(),253,3,B)); // Absolute-file alignment.
    D.resize(300); Put(D,256,1); Put(D,264,4);
    assert(!Parse(D.data(),D.size(),0,B) && B.empty()); // No partially accepted stream.
    if (argc>1)
    {
        std::ifstream F(argv[1],std::ios::binary); assert(F);
        D.assign(std::istreambuf_iterator<char>(F),{});
        assert(D.size()==2048 && !Parse(D.data(),D.size(),244000896,B) && B.empty());
    }
    if (argc>2)
    {
        size_t Count=0;
        for (const auto& P : std::filesystem::directory_iterator(argv[2]))
        {
            const auto Name=P.path().filename().string();
            if (Name.size()<9 || Name.substr(Name.size()-9)!=".xsub.bin") continue;
            std::ifstream F(P.path(),std::ios::binary);
            D.assign(std::istreambuf_iterator<char>(F),{});
            assert(Parse(D.data(),D.size(),0,B)); ++Count;
        }
        assert(Count>0);
        std::cout << "PASS: " << Count << " saved Zoo package object layouts\n";
    }
    std::cout << "PASS: valid/padded/raw/extended streams; truncated tables, crossing commands, short prefixes, invalid counts, partial streams and crash fixture rejected\n";
}
