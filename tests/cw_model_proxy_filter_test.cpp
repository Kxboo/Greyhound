#include "../src/WraithXCOD/WraithXCOD/CWModelProxyFilter.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace CWModelProxyFilter;
void Check(bool B) {if(!B)throw std::runtime_error("proxy filter check failed");}
json Row(const std::string& N,int D,int I)
{return {{"Name",N},{"District",D},{"ReferenceIndex",I},{"BoundsMin",{{"X",0},{"Y",0},{"Z",0}}},{"BoundsMax",{{"X",10},{"Y",10},{"Z",10}}}};}
int main(int argc,char** argv)
{
 try {
    if(argc==5)
    {
        json R,M,D;std::ifstream(argv[1])>>R;std::ifstream(argv[2])>>M;std::ifstream(argv[3])>>D;
        std::map<std::string,Model> C;for(auto I=M.begin();I!=M.end();++I)
            C[I.key()]={I.value().at("lods").get<uint32_t>(),I.value().at("surfaces").get<uint32_t>(),
                I.value().at("triangles").get<uint64_t>(),I.value().value("baked_proxy_shader",false)?BakedAtlasTechnique:0};
        std::map<uint32_t,Box> B;for(const auto& E:D.at("districts"))B[E.at("district").get<uint32_t>()]=E.at("bounds").get<Box>();
        json E=json::array();auto Report=Apply(R,C,B,E);const std::string P=argv[4];
        std::ofstream(P+"/static_models.json")<<R.dump();std::ofstream(P+"/excluded_proxies.json")<<E.dump(2);
        std::ofstream(P+"/proxy-filter-report.json")<<Report.dump(2);
        Report.erase("decisions");std::cout<<Report.dump()<<"\n";return 0;
    }
    std::map<std::string,Model> C={{"proxy",{1,1,100,BakedAtlasTechnique}},
        {"simple",{1,1,12,0}},{"a",{1,3,500,0}},{"b",{2,4,600,0}},{"c",{1,8,700,0}}};
    std::map<uint32_t,Box> B={{7,{0,0,0,10,10,10}}};
    json R=json::array({Row("proxy",2,0),Row("simple",2,1),Row("a",7,0),Row("b",7,1),Row("c",7,2),Row("a",7,3)});
    auto Original=R;json E=json::array();auto Report=Apply(R,C,B,E);Check(E.size()==1&&R.size()==5&&E[0]["Name"]=="proxy");
    // A spline extending far below the static replacement must not dilute the
    // overlap score; its geometry also must not supply replacement evidence.
    R=Original;auto S=Row("a",7,4);S["RequiresSplineDeformation"]=true;
    S["BoundsMin"]["Z"]=-1000;R.push_back(S);B[7]={0,0,-1000,10,10,10};E=json::array();
    Report=Apply(R,C,B,E);Check(E.size()==1 && R.size()==6 && R.back()["RequiresSplineDeformation"]==true);
    R=json::array({Original[0],S});E=json::array();Apply(R,C,B,E);Check(E.empty());
    R=Original;E=json::array();B.clear();Apply(R,C,B,E);Check(E.empty()&&R.size()==6);
    B[7]={100,100,100,110,110,110};Apply(R,C,B,E);Check(E.empty());
    B[7]={0,0,0,10,10,10};C["proxy"].Technique=0;Apply(R,C,B,E);Check(E.empty());
    C["proxy"].Technique=BakedAtlasTechnique;C["proxy"].Lods=2;Apply(R,C,B,E);Check(E.empty());
    C["proxy"].Lods=1;C["proxy"].Triangles=100000;Apply(R,C,B,E);Check(E.empty());
    std::cout<<"PASS: supported proxy, simple model retained, missing/disjoint/insufficient replacement, nonmatching signature\n";
 }catch(const std::exception& E){std::cerr<<E.what()<<"\n";return 1;}
}
