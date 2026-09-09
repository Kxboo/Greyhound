#include "../src/WraithXCOD/WraithXCOD/CWDistrictPayload.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <iterator>
using namespace CWDistrictPayload;
void Check(bool V) { if (!V) throw std::runtime_error("district payload check failed"); }
void Put32(std::vector<uint8_t>& B, size_t O, uint32_t V) { memcpy(B.data()+O,&V,4); }
void PutFloat(std::vector<uint8_t>& B, size_t O, float V) { memcpy(B.data()+O,&V,4); }
std::vector<uint8_t> Read(const char* File)
{
    std::ifstream F(File, std::ios::binary);
    if (!F) throw std::runtime_error("fixture unavailable");
    return {std::istreambuf_iterator<char>(F), std::istreambuf_iterator<char>()};
}
int main(int argc, char** argv)
{
    try
    {
        std::string Error; Layout L;
        if (argc == 3 && std::string(argv[1]) == "--package")
        {
            auto B=Read(argv[2]); Check(PackageLayout(B,B.size(),L,Error));
            std::vector<uint8_t> R(B.begin()+L.References,B.begin()+L.Transforms);
            std::vector<uint8_t> T(B.begin()+L.Transforms,B.begin()+L.Transforms+64ull*L.Count);
            if (!ValidateArrays(R,T,L.Count,true,Error)) throw std::runtime_error(Error);
            std::cout << L.Start << " " << L.Count << "\n"; return 0;
        }
        if (argc == 4 && std::string(argv[1]) == "--live")
        {
            auto R=Read(argv[2]), T=Read(argv[3]);
            if (!ValidateArrays(R,T,uint32_t(T.size()/64),false,Error)) throw std::runtime_error(Error);
            std::cout << T.size()/64 << "\n"; return 0;
        }
        for (uint32_t N : {0u,1u,2u,19u})
        {
            std::vector<uint8_t> B(HeaderBytes+240*N+(N%2?8:0));
            Put32(B,0,uint32_t(B.size()-256)); Put32(B,268,N);
            Check(PackageLayout(B,B.size(),L,Error)); Check(L.Count==N);
            Check(!PackageLayout(B,B.size()+256,L,Error));
            auto Bad=B; Put32(Bad,268,UINT32_MAX); Check(!PackageLayout(Bad,Bad.size(),L,Error));
            Bad=B; Bad[272]=1; Check(!PackageLayout(Bad,Bad.size(),L,Error));
            Bad=B; Bad.pop_back(); Check(!PackageLayout(Bad,Bad.size(),L,Error));
        }
        std::vector<uint8_t> R(128),T(128);
        R[16]=R[80]=1;
        for (int I=0;I<2;++I) { PutFloat(T,64*I+12,1); PutFloat(T,64*I+28,1); }
        // Reordered rows and the runtime flag must still partition references.
        Put32(T,56,0x80000001); Put32(T,120,0);
        Check(ValidateArrays(R,T,2,true,Error));
        auto Bad=T; Put32(Bad,120,1); Check(!ValidateArrays(R,Bad,2,true,Error));
        Bad=T; Put32(Bad,56,2); Check(!ValidateArrays(R,Bad,2,true,Error));
        Bad=T; Put32(Bad,16,0x7FC00000); Check(!ValidateArrays(R,Bad,2,true,Error));
        Bad=T; PutFloat(Bad,28,0); Check(!ValidateArrays(R,Bad,2,true,Error));
        Bad=T; PutFloat(Bad,32,1); Check(!ValidateArrays(R,Bad,2,true,Error));
        R[16]=0; Check(!ValidateArrays(R,T,2,true,Error));
        Check(Contiguous({{2,3},{0,2}})); Check(!Contiguous({{0,2},{3,1}}));
        Check(!Contiguous({{0,2},{1,1}})); Check(!Contiguous({{1,2}}));
        std::cout << "PASS: allocation, pointer relocation, permutation, bounds, transforms, range gaps/overlap\n";
    }
    catch (const std::exception& E) { std::cerr << E.what() << "\n"; return 1; }
}
