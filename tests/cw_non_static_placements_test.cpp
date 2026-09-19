#include "../src/WraithXCOD/WraithXCOD/CWNonStaticPlacements.h"
#include <iostream>
#include <limits>
using namespace CWNonStaticPlacements;
void Check(bool V) {if(!V)throw std::runtime_error("non-static placement test failed");}
json Property(const char* Key,int Type,const char* Field,const json& Value)
{return {{"key",{{"text",Key}}},{"type_tag",Type},{Field,Value},{"raw_value_hex","preserved"}};}
int main()
{
    try
    {
        json E={{"index",7},{"record_vector_candidates",{{1.25,2.5,3.0},{0.0,90.0,0.0}}},
            {"properties",json::array({
                Property("classname",2,"string_candidate",{{"text","script_model"},{"terminated",true}}),
                Property("model",4,"asset_hash_candidate","0xf000000000000123"),
                Property("origin",3,"vector_candidate",{1.0,3.0,3.0}),
                Property("angles",3,"vector_candidate",{0.0,90.0,0.0}),
                Property("modelscale",2,"string_candidate",{{"text","1.5"},{"terminated",true}}),
                Property("unknown",99,"raw_value_hex","deadbeef")})}};
        const auto ConvertOne=[&](const json& Row,const Resolver& Resolve=Resolver([](uint64_t H){return H==0x123?"known_model":"";}))
        {return Convert({{"source_name_hash","0xabc"},{"entities",json::array({Row})}},"entitylist",Resolve);};
        auto R=ConvertOne(E);const auto M=R["models"][0];
        Check(R["models"].size()==1 && M["Name"]=="known_model" && M["ModelHash"]=="0x123");
        Check(M["Position"]["X"]==1.25 && M["Position"]["Y"]==2.5 && M["ModelScale"]["Z"]==1.5);
        Check(std::abs(M["RotationQuaternion"]["Z"].get<double>()-std::sqrt(0.5))<1e-12);
        Check(M["SourceEntityId"]=="0xabc:entitylist:7" && M["RotationDegrees"]["Z"]==90);
        Check(R["entities"]["class_script_model.json"][0]["properties"]==E["properties"]);
        auto Unresolved=ConvertOne(E,[](uint64_t){return std::string();});
        Check(Unresolved["models"][0]["Name"]=="xmodel_123" && !Unresolved["models"][0]["NameResolved"].get<bool>());
        auto Bad=E;Bad["record_vector_candidates"][0][0]=20;
        Check(ConvertOne(Bad)["models"].empty());
        Bad=E;Bad["properties"].push_back(E["properties"][1]);Check(ConvertOne(Bad)["models"].empty());
        Bad=E;Bad["properties"][4]["string_candidate"]["text"]="1.5junk";Check(ConvertOne(Bad)["models"].empty());
        Bad=E;Bad["properties"][4]["string_candidate"]["text"]="nan";Check(ConvertOne(Bad)["models"].empty());
        Bad=E;Bad["properties"][1]=Property("model",2,"string_candidate",{{"text","*12"},{"terminated",true}});Check(ConvertOne(Bad)["models"].empty());
        Bad=E;Bad["properties"][0]["string_candidate"]["text"]="reflection_probe";Bad["properties"].erase(1);
        R=ConvertOne(Bad);Check(R["models"].empty() && R["entity_count"]==1);
        Check(R["entities"]["class_reflection_probe.json"][0]["BO3ProbeKeys"]["origin"][0]==1.25);
        Check(ClassFile("../CON") == "class_%2E%2E%2FCON.json");
        Check(ClassFile("a/b")!=ClassFile("a%2Fb"));
        auto Q=Quaternion({90,0,0});Check(std::abs(Q["Y"].get<double>()-std::sqrt(0.5))<1e-12);
        Check(Convert({{"entities",json::array()}},"entitylist",[](uint64_t){return std::string();})["models"].empty());
        std::cout<<"PASS: precision, pitch/yaw quaternion, hashes, joins, typed evidence, invalid transforms/scales, duplicate keys, class paths, reflection mapping\n";
        return 0;
    }
    catch(const std::exception& E) {std::cerr<<E.what()<<'\n';return 1;}
}
