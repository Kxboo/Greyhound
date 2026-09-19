#include "../src/WraithXCOD/WraithXCOD/CWLightPlacements.h"
#include <fstream>
#include <iostream>
#include <limits>
using namespace CWProbeBounds;
void Check(bool B,const char* Why){if(!B)throw std::runtime_error(Why);}
template<class T>void Put(std::vector<uint8_t>& B,size_t O,T Value){std::memcpy(B.data()+O,&Value,sizeof(Value));}
double Linear(double S){return S<=0.04045?S/12.92:std::pow((S+0.055)/1.055,2.4);}
void Roundtrip(const json& J,const V3& C)
{
    const auto& B=J.at("BO3");const double Gain=std::pow(2.0,B.at("stops").get<double>());
    for(int K=0;K<3;++K)Check(std::abs(Linear(B.at("_color")[K].get<double>())*Gain-C[K])<=std::max(1e-12,std::abs(C[K])*1e-6),"RGB roundtrip failed");
}
int main(int argc,char** argv)
{
 try
 {
    std::vector<uint8_t> P(688);Put(P,0x40,uint32_t(2));Put(P,0xDC,-1.0f);Put(P,0x278,360.0f);
    Put(P,0xE8,250.0f);Put(P,0x1E8,uint32_t(7));Put(P,0x1EC,uint32_t(7));Put(P,0x1F0,4.0f);
    for(V3 C:{V3{1024,256,1},V3{0,0,0},V3{1e-12,2e-12,3e-12}})
    {
        for(int K=0;K<3;++K)Put(P,0xC8+4*K,float(C[K]));
        auto J=CWLightSettings::Decode(P.data(),P.size());Roundtrip(J,V(P.data(),0xC8));
        Check(J["BO3CoreSettingsValidated"],"ordinary omni should map");Check(J["BO3"]["PRIMARY_TYPE"]=="PRIMARY_OMNI","omni type");
        Check(J["BO3"]["volumetricIntensityBoost"]==2,"boost stops");
    }
    P[0x45]=1;Put(P,0xDC,float(std::cos(35*3.141592653589793/180)));Put(P,0x278,70.0f);
    auto J=CWLightSettings::Decode(P.data(),P.size());Check(J["BO3"]["PRIMARY_TYPE"]=="PRIMARY_SPOT","spot type");Check(J["BO3"]["fov_outer"]==70,"spot FOV");
    auto Bad=P;Bad[0x44]=1;Check(!CWLightSettings::Decode(Bad.data(),688)["BO3CoreSettingsValidated"].get<bool>(),"box deferred");
    Bad=P;Put(Bad,0x40,uint32_t(4));Check(!CWLightSettings::Decode(Bad.data(),688)["BO3"].contains("PRIMARY_TYPE"),"unverified raw type deferred");
    Bad=P;Put(Bad,0x278,360.0f);Check(!CWLightSettings::Decode(Bad.data(),688)["BO3CoreSettingsValidated"].get<bool>(),"conflicting FOV deferred");
    Bad=P;Put(Bad,0xC8,std::numeric_limits<float>::quiet_NaN());Check(!CWLightSettings::Decode(Bad.data(),688)["BO3"].contains("stops"),"NaN not mapped");
    Bad=P;Put(Bad,0x1EC,uint32_t(3));Check(!CWLightSettings::Decode(Bad.data(),688)["BO3"].contains("volumetricSampleCount"),"different quality samples not merged");
    Check(!CWLightSettings::Decode(P.data(),687)["SettingsDecoded"].get<bool>(),"size guard");
    std::cout<<"Synthetic color/type/FOV/volumetric/invalid-record tests passed\n";
    if(argc==4)
    {
        std::ifstream F(argv[1]);json Rows;F>>Rows;json Output=json::array();size_t Core=0;
        for(const auto& R:Rows)
        {
            const auto Hex=R.at("RawRecordHex").get<std::string>();Check(Hex.size()==1376,"raw length");
            for(size_t K=0;K<688;++K)P[K]=uint8_t(std::stoul(Hex.substr(K*2,2),nullptr,16));
            auto D=CWLightPlacements::Decode(P.data(),P.size());Check(D["PlacementValidated"],"captured placement invalid");
            Roundtrip(D,V(P.data(),0xC8));
            D["SourceId"]=R.at("SourceId");D["RecordAddress"]=R.at("RecordAddress");D["SourcePlacementFile"]="lights/placements.json";
            D["SourcePlacementIndex"]=R.at("Index");D["RawRecordHex"]=Hex;
            if(D["BO3CoreSettingsValidated"].get<bool>())++Core;
            Output.push_back(D);
        }
        std::ofstream O(argv[2]);O<<Output.dump(2)<<'\n';
        json Report={{"status","passed"},{"lights",Rows.size()},{"core_settings_mapped",Core},{"shape_or_cone_deferred",Rows.size()-Core},
            {"rgb_roundtrip_relative_tolerance",1e-6},{"full_visual_accuracy",false}};
        std::ofstream VOut(argv[3]);VOut<<Report.dump(2)<<'\n';std::cout<<Report.dump(2)<<'\n';
    }
    return 0;
 }
 catch(const std::exception& E){std::cerr<<E.what()<<'\n';return 1;}
}
