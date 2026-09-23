#include "../src/WraithXCOD/WraithXCOD/CWSplineBake.h"
#include <cassert>
#include <fstream>
#include <iostream>
using namespace CWSplineBake;

static json Fixture()
{
    const std::vector<double> identity={1,0,0,0,1,0,0,0,1};
    json instance={{"SplineInstanceIndex",1},{"modelXExtent",10},{"instanceLength",10},{"modelSplineOrigin",{0,0,0}},
        {"distFromStartNode",0},{"modelScale",1},{"upDownOffset",0},{"leftRightOffset",0},{"prefabScale",1},
        {"prefabOrigin",{0,0,0}},{"prefabAxisRowMajor",identity},{"segmentBegin",0},{"segmentEnd",1},{"spliningAxisType",0}};
    json segment={{"SegmentIndex",0},{"distFromStartNode",0},{"length",10},{"bezierEval",{0,0,0,10,0,0,0,0,0,0,0,0}},
        {"entBezierDerEval",{0,0,0,0,0,0,10,0,0}},{"entToAlignedRowMajor",identity},{"modelToWldRowMajor",identity},
        {"modelToWld_origin",{0,0,0}},{"bankAngleBezierEval",{0,0,0,0}}};
    return {{"status","captured_source_data"},{"instances",{{"readback_unchanged",true},{"stride",100},{"count",2}}},
        {"segments",{{"readback_unchanged",true},{"stride",192},{"count",1}}},{"Instances",{instance}},{"Segments",{segment}}};
}
int main(int argc,char** argv)
{
    try {
    auto doc=Fixture();Controls c(doc);
    for(V p:std::vector<V>{{-5,2,3},{5,2,3},{15,2,3}}) assert(Dot(Sub(c.Deform(p,1),p),Sub(c.Deform(p,1),p))<1e-20);
    V n{};assert(c.Normal({2,3,4},{0,0,1},1,n) && std::abs(n[2]-1)<1e-12);
    doc["Instances"][0]["instanceLength"]=20;Controls stretch(doc);
    assert(stretch.Normal({2,3,4},Unit({1,1,0}),1,n));assert(std::abs(n[0]-1/std::sqrt(5.0))<1e-9);
    doc["Segments"][0]["bankAngleBezierEval"][0]=3.141592653589793/2;Controls bank(doc);
    auto p=bank.Deform({2,2,3},1);assert(std::abs(p[1]-3)<1e-12 && std::abs(p[2]+2)<1e-12);
    bool rejected=false;doc["Instances"][0]["spliningAxisType"]=6;
    try {Controls bad(doc);} catch(const std::exception&) {rejected=true;} assert(rejected);
    doc=Fixture();doc["Segments"].push_back(doc["Segments"][0]);doc["Segments"][1]["SegmentIndex"]=1;
    doc["Segments"][0]["length"]=0;doc["segments"]["count"]=2;
    doc["Instances"][0]["segmentBegin"]=1;doc["Instances"][0]["segmentEnd"]=2;
    Controls reserved(doc);assert(std::abs(reserved.Deform({3,0,0},1)[0]-3)<1e-12);
    if(argc==3) {
        std::ifstream input(argv[1]);json captured;input>>captured;Controls live(captured);
        std::ifstream data(argv[2],std::ios::binary);uint32_t index,count=0;double maxError=0;
        while(data.read(reinterpret_cast<char*>(&index),4)) {
            V pos,expected,normal,expectedNormal;uint8_t checkNormal;
            data.read(reinterpret_cast<char*>(pos.data()),24);data.read(reinterpret_cast<char*>(expected.data()),24);
            data.read(reinterpret_cast<char*>(normal.data()),24);data.read(reinterpret_cast<char*>(expectedNormal.data()),24);
            data.read(reinterpret_cast<char*>(&checkNormal),1);if(!data)return 2;
            const auto actual=live.Deform(pos,index);
            for(size_t a=0;a<3;++a) maxError=(std::max)(maxError,std::abs(actual[a]-expected[a]));
            if(checkNormal) {
                if(!live.Normal(pos,normal,index,n))return 3;
                for(size_t a=0;a<3;++a)if(std::abs(n[a]-expectedNormal[a])>2e-6)return 4;
            }
            ++count;
        }
        std::cout<<json({{"vertices",count},{"max_position_difference",maxError},{"passed",maxError<1e-7}}).dump(2)<<std::endl;
        if(maxError>=1e-7)return 5;
    }
    } catch(const std::exception& e) {std::cerr<<e.what()<<std::endl;return 9;}
}
