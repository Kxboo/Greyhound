#include "../src/WraithXCOD/WraithXCOD/CWProbeBounds.h"
#include <iostream>
#include <limits>
using namespace CWProbeBounds;
void Check(bool B){if(!B)throw std::runtime_error("probe bounds test failed");}
template<class T>void Put(std::vector<uint8_t>& B,size_t O,T V){std::memcpy(B.data()+O,&V,sizeof(V));}
void Vec(std::vector<uint8_t>& B,size_t O,V3 V){for(int I=0;I<3;++I)Put(B,O+I*4,float(V[I]));}
int main()
{
    try
    {
        std::vector<uint8_t>B(604);
        Vec(B,0,{10,20,30});Vec(B,12,{0,1,0});Vec(B,24,{-1,0,0});Vec(B,36,{0,0,1});
        Vec(B,48,{2,3,4});Vec(B,60,{5,6,7});Vec(B,72,{1,2,3});Vec(B,84,{4,5,6});
        // Outer local bounds [-3,-5,-7] to [9,11,13], center [3,3,3].
        Vec(B,580,{7,23,33});auto R=Decode(B.data(),B.size());
        Check(R["StructuralValidation"]);Check(R["AnglesPitchYawRoll"][1]==90);
        Check(R["OuterBox"]["WorldAABBMin"]==json::array({-1.0,17.0,23.0}));
        Check(R["OuterBox"]["WorldAABBMax"]==json::array({15.0,29.0,43.0}));
        Check(R["BO3"]["size_min"]==json::array({2.0,3.0,4.0}));
        // local x <= 2 becomes world y <= 22 under a 90-degree yaw.
        Put(B,96,uint32_t(1));Vec(B,100,{1,0,0});Put(B,112,-2.0f);
        R=Decode(B.data(),B.size());Check(R["StructuralValidation"]);
        Check(R["InfluencePlanes"][0]["WorldNormal"]==json::array({0.0,1.0,0.0}));
        Check(R["InfluencePlanes"][0]["WorldD"]==-22);
        auto Bad=B;Put(Bad,96,uint32_t(31));Check(!Decode(Bad.data(),Bad.size())["StructuralValidation"].get<bool>());
        Bad=B;Put(Bad,12,std::numeric_limits<float>::quiet_NaN());Check(!Decode(Bad.data(),Bad.size())["StructuralValidation"].get<bool>());
        Bad=B;Vec(Bad,580,{10,20,30});Check(!Decode(Bad.data(),Bad.size())["StructuralValidation"].get<bool>());
        Bad=B;Put(Bad,72,-1.0f);Check(!Decode(Bad.data(),Bad.size())["StructuralValidation"].get<bool>());
        Bad=B;Bad[600]=2;Check(!Decode(Bad.data(),Bad.size())["StructuralValidation"].get<bool>());
        Check(!Decode(B.data(),603)["StructuralValidation"].get<bool>());
        // Gimbal lock pitch 90, equivalent yaw 0 roll 0. Keep the center consistent.
        Bad=B;Put(Bad,96,uint32_t(0));Vec(Bad,12,{0,0,-1});Vec(Bad,24,{0,1,0});Vec(Bad,36,{1,0,0});Vec(Bad,580,{13,23,27});
        R=Decode(Bad.data(),Bad.size());Check(R["StructuralValidation"]);Check(R["AnglesPitchYawRoll"][0]==90);
        std::vector<uint8_t>P(376*3);std::vector<int> O;
        Put(P,376+0x58,uint16_t(0));Put(P,376+0x5A,uint16_t(2));Put(P,752+0x58,uint16_t(2));Put(P,752+0x5A,uint16_t(1));
        Check(Owners(P,3,O));Check(O==std::vector<int>({1,1,2}));
        Put(P,752+0x58,uint16_t(1));Check(!Owners(P,3,O)); // overlap
        Put(P,752+0x58,uint16_t(3));Check(!Owners(P,3,O)); // overflow
        Put(P,752+0x58,uint16_t(2));Check(!Owners(P,4,O)); // gap
        P.resize(376);Check(Owners(P,0,O));
        std::cout<<"probe bounds tests passed\n";return 0;
    }
    catch(const std::exception& E){std::cerr<<E.what()<<"\n";return 1;}
}
