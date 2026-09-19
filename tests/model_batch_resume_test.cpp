#include "../src/WraithXCOD/WraithXCOD/ModelBatchResume.h"
#include <cassert>
#include <iostream>
#include <filesystem>
int main(int argc,char** argv)
{
    using namespace ModelBatchResume;
    using json=nlohmann::json;
    if(argc==3 && std::string(argv[1])=="--self-test")
    {
        const std::string Root=argv[2], Name="fixture_model";
        std::filesystem::create_directories(Directory(Root,Name));
        const auto File=Directory(Root,Name)+"/"+Name+".cast";
        uint32_t Header[10]={0x74736163,1,1,0,0x746f6f72,24,0,0,0,0};
        {std::ofstream Out(File,std::ios::binary);Out.write(reinterpret_cast<const char*>(Header),sizeof(Header));}
        json Ids={{Name,Name}}, Empty=json::object();
        assert(CompleteCast(File));
        assert(Completed(Root,Name,Ids,Empty,true));
        assert(!Completed(Root,Name,Ids,Empty,false));
        json Done={{Name,Files(Root,Name)}};
        assert(Done[Name].size()==1 && Completed(Root,Name,Ids,Done,false));
        auto Bad=Done;Bad[Name][0]["bytes"]=1;assert(!Completed(Root,Name,Ids,Bad,false));
        Bad=Done;Bad[Name][0]["file"]="../other.cast";assert(!Completed(Root,Name,Ids,Bad,false));
        auto Wrong=Ids;Wrong[Name]="other_model";assert(!Completed(Root,Name,Wrong,Done,false));
        {std::ofstream Out(File,std::ios::binary);Out.write(reinterpret_cast<const char*>(Header),20);}
        assert(!CompleteCast(File) && !Completed(Root,Name,Ids,Done,false));
        assert(!CompleteCast(Root+"/missing.cast"));
        std::cout<<"PASS: complete/truncated CAST, identity mismatch, LOD policy, checkpoint size, missing files and traversal\n";
        return 0;
    }
    assert(argc>1);
    const auto Root=std::string(argv[1]);
    std::ifstream Input(Root+"/"+"static_models.json"); json Rows; Input>>Rows;
    std::ifstream IdFile(Root+"/"+"model_identities.json"); json Ids; IdFile>>Ids;
    std::set<std::string> Names;
    for (const auto& Row:Rows) Names.insert(Row.value("SourceName",Row.at("Name").get<std::string>()));
    size_t Kept=0; const json Empty=json::object();
    for (const auto& Name:Names) if(Completed(Root,Name,Ids,Empty,true)) ++Kept;
    assert(Names.size()==1712 && Kept==1318);
    const std::string Name="p9_zm_ndu_gondola_grate_03";
    assert(!Completed(Root,Name,Ids,Empty,false)); // All LODs require a completed checkpoint.
    auto Entry=Files(Root,Name); assert(Entry.size()==1);
    json Done={{Name,Entry}};
    assert(Completed(Root,Name,Ids,Done,false));
    Done[Name][0]["bytes"]=1; assert(!Completed(Root,Name,Ids,Done,false));
    Done[Name][0]["file"]="../outside.cast";assert(!Completed(Root,Name,Ids,Done,false));
    auto Wrong=Ids;Wrong[Name]="different runtime identity";
    assert(!Completed(Root,Name,Wrong,Empty,true));
    assert(!Completed(Root,"p9_zm_ndu_grill_barbecue",Ids,Empty,true));
    assert(!CompleteCast(Root+"/"+"static_models.json"));
    assert(!CompleteCast(Root+"/"+"missing.cast"));
    std::cout<<"PASS: preserve 1318, remaining 394; identity mismatch, LOD policy, checkpoint size, missing files and traversal checked\n";
}
