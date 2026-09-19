#include "../src/WraithXCOD/WraithXCOD/CWStaticPlacementFilter.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace CWStaticPlacementFilter;
void Check(bool V) { if (!V) throw std::runtime_error("Static placement selection failed"); }
int main(int argc, char** argv)
{
    try
    {
        json Rows = json::array({
            {{"Name","shared"},{"RequiresSplineDeformation",true},{"SplineInstanceIndex",0},{"Position",{1,2,3}}},
            {{"Name","shared"},{"RequiresSplineDeformation",false},{"SplineInstanceIndex",nullptr},{"Position",{4,5,6}}},
            {{"Name","legacy_spline"},{"SplineInstanceIndex",42}},
            {{"Name","sentinel"},{"SplineInstanceIndex",0xFFFFFFFFu}},
            {{"Name","legacy_rigid"}},
            {{"Name","negative_sentinel"},{"SplineInstanceIndex",-1}}});
        const auto Original=Rows; json Deferred;
        const auto Report=Separate(Rows,Deferred);
        Check(Rows==json::array({Original[1],Original[3],Original[4],Original[5]}));
        Check(Deferred==json::array({Original[0],Original[2]}));
        Check(Report["exported_instances"]==4 && Report["deferred_spline_instances"]==2);
        Check(Report["exported_unique_models"]==4); // Rigid use of a shared model remains.
        const auto Again=Rows; Separate(Rows,Deferred); Check(Rows==Again && Deferred.empty());
        Rows=json::array({Original[0]});Separate(Rows,Deferred);Check(Rows.empty()&&Deferred.size()==1);
        Rows=json::array();Separate(Rows,Deferred);Check(Rows.empty()&&Deferred.empty());
        if (argc==2)
        {
            std::ifstream Input(argv[1]);Input>>Rows;
            if (!Rows.is_array()) Rows=Rows.at("StaticModels");
            const auto Captured=Rows; const auto Live=Separate(Rows,Deferred);
            size_t Kept=0,Skipped=0;
            for(const auto& R:Captured)
                if(RequiresSpline(R))Check(Deferred.at(Skipped++)==R);
                else Check(Rows.at(Kept++)==R);
            Check(Kept+Skipped==Captured.size());
            std::cout<<Live.dump()<<"\n";
        }
        std::cout<<"PASS: shared identity, source fields/order, zero-index spline, legacy index, sentinels, empty/all-spline, idempotence\n";
    }
    catch(const std::exception& E){std::cerr<<E.what()<<"\n";return 1;}
}
