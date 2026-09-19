#pragma once
#include "CWProbeBounds.h"
#include "CWLightSettings.h"

// Measured 688-byte light records. Ten independently authored lights match
// GUID +0x48, position +0x68, and the signed basis below (map_capture_09).
namespace CWLightPlacements
{
    using namespace CWProbeBounds;
    inline json Decode(const uint8_t* P,size_t Size)
    {
        if(Size!=688)return {{"PlacementValidated",false},{"Error","expected 688-byte light record"}};
        const auto Position=V(P,0x68),Up=V(P,0x74),Back=V(P,0x80),Right=V(P,0x8C);
        const std::array<V3,3> Axes={V3{-Back[0],-Back[1],-Back[2]},V3{-Right[0],-Right[1],-Right[2]},Up};
        bool Valid=Finite(Position);
        for(int J=0;J<3;++J)for(int K=0;K<3;++K)
            if(!Finite(Axes[J])||std::abs(Dot(Axes[J],Axes[K])-(J==K?1.0:0.0))>0.002)Valid=false;
        const V3 Cross={Axes[0][1]*Axes[1][2]-Axes[0][2]*Axes[1][1],Axes[0][2]*Axes[1][0]-Axes[0][0]*Axes[1][2],Axes[0][0]*Axes[1][1]-Axes[0][1]*Axes[1][0]};
        if(std::abs(Dot(Cross,Axes[2])-1)>0.002)Valid=false;
        const double XY=std::hypot(Axes[0][0],Axes[0][1]),Degrees=180/3.14159265358979323846;
        const V3 Angles={std::atan2(-Axes[0][2],XY)*Degrees,
            (XY>1e-6?std::atan2(Axes[0][1],Axes[0][0]):std::atan2(-Axes[1][0],Axes[1][1]))*Degrees,
            (XY>1e-6?std::atan2(Axes[1][2],Axes[2][2]):0)*Degrees};
        json Result={{"PlacementValidated",Valid},{"Guid",U32(P,0x48)},
            {"Position",Valid?json(Position):json(nullptr)},{"AnglesPitchYawRoll",Valid?json(Angles):json(nullptr)},
            {"LocalAxesInWorld",Axes},{"Up",Up},{"Back",Back},{"Right",Right},
            {"LayoutEvidence","ten authored GUID/position/orientation matches; +0x74 is up, not forward"},
            {"BO3",{{"classname","light"},{"origin",Valid?json(Position):json(nullptr)},
                {"angles",Valid?json(Angles):json(nullptr)},{"PRIMARY_TYPE",nullptr},
                {"status","placement reference only; light type and appearance conversion not included"}}}};
        const auto Settings=CWLightSettings::Decode(P,Size);
        for(auto It=Settings.begin();It!=Settings.end();++It)
            if(It.key()=="BO3"){if(Valid)Result["BO3"].update(It.value());}
            else Result[It.key()]=It.value();
        return Result;
    }
}
