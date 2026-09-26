#include "games/cold_war/placements/CWPlacementRotation.h"
#include <array>
#include <cassert>
#include <fstream>
#include <random>

std::array<double,4> Quaternion(double roll,double pitch,double yaw)
{
    constexpr double half=3.14159265358979323846/360;
    double cr=cos(roll*half),sr=sin(roll*half),cp=cos(pitch*half),sp=sin(pitch*half),cy=cos(yaw*half),sy=sin(yaw*half);
    return {sr*cp*cy-cr*sp*sy,cr*sp*cy+sr*cp*sy,cr*cp*sy-sr*sp*cy,cr*cp*cy+sr*sp*sy};
}
void Check(const float q[4])
{
    double e[3];CWPlacementRotation::EulerDegrees(q,e);
    auto rebuilt=Quaternion(e[0],e[1],e[2]);double norm=0,dot=0;
    for(int i=0;i<4;++i)norm+=double(q[i])*q[i];norm=sqrt(norm);
    for(int i=0;i<4;++i)dot+=q[i]/norm*rebuilt[i];
    double error=0;
    for(int i=0;i<4;++i)error+=pow(q[i]/norm-(dot<0?-rebuilt[i]:rebuilt[i]),2);
    assert(sqrt(error)<1e-7);
}
int main(int argc,char** argv)
{
    float captured[]={0.7071067690849304f,0,0.7071067690849304f,0};Check(captured);
    std::mt19937 random(3197);std::uniform_real_distribution<double> angle(-180,180);
    for(double pitch:{-90.,90.,-89.999999,89.999999,-89.999,89.999,0.,48.5})
        for(int n=0;n<1000;++n) {
            auto q=Quaternion(angle(random),pitch,angle(random));float f[4];
            for(int i=0;i<4;++i)f[i]=float(q[i]*(n%2?-1.0000001:0.9999999));Check(f);
        }
    for(float bad:{0.f,NAN}) {
        float q[4]={bad,0,0,0};double e[3];bool rejected=false;
        try{CWPlacementRotation::EulerDegrees(q,e);}catch(const std::exception&){rejected=true;}
        assert(rejected);
    }
    if(argc==3) {
        std::ifstream input(argv[1],std::ios::binary);std::ofstream output(argv[2],std::ios::binary);
        float q[4];while(input.read(reinterpret_cast<char*>(q),sizeof(q))) {
            Check(q);double e[3];CWPlacementRotation::EulerDegrees(q,e);
            output.write(reinterpret_cast<char*>(e),sizeof(e));
        }
        assert(input.eof() && output);
    }
}
