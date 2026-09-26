#pragma once
#include <cmath>
#include <stdexcept>

namespace CWPlacementRotation
{
    // Rz(yaw) * Ry(pitch) * Rx(roll); output X=roll, Y=pitch, Z=yaw.
    // Float quaternions must be normalized before building the rotation matrix.
    // At the pitch singularity choose roll=0 and retain the coupled yaw/roll
    // rotation instead of evaluating two unstable atan2(0,0) expressions.
    inline void EulerDegrees(const float Q[4], double Out[3])
    {
        double x=Q[0],y=Q[1],z=Q[2],w=Q[3];
        const double length=std::sqrt(x*x+y*y+z*z+w*w);
        if(!std::isfinite(length) || length<=1e-12)
            throw std::runtime_error("Invalid placement quaternion");
        x/=length;y/=length;z/=length;w/=length;
        const double r00=1-2*(y*y+z*z),r10=2*(x*y+w*z),r20=2*(x*z-w*y);
        const double cp=std::hypot(r00,r10);
        constexpr double degrees=57.2957795130823208768;
        Out[1]=std::atan2(-r20,cp)*degrees;
        if(cp>1e-7) {
            Out[0]=std::atan2(2*(y*z+w*x),1-2*(x*x+y*y))*degrees;
            Out[2]=std::atan2(r10,r00)*degrees;
        } else {
            Out[0]=0;
            Out[2]=std::atan2(-2*(x*y-w*z),1-2*(x*x+z*z))*degrees;
        }
    }
}
