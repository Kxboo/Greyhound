"""Reuse plane-defining points only for exactly equal normalized equations."""
import numpy as np

class CanonicalPlaneWriter:
    def __init__(self,basis=8192):self.basis=basis;self.cache={}
    def lines(self,equations,center,material):
        result=[]
        for plane in equations:
            negative=next(x for x in plane[:3] if x)!=abs(next(x for x in plane[:3] if x))
            canonical=-plane if negative else plane;key=tuple(float(x) for x in canonical)
            if key not in self.cache:
                n=canonical[:3];d=canonical[3];base=n*d;base=base+n*(d-n@base)
                axis=np.eye(3)[np.argmin(abs(n))];u=np.cross(n,axis);u*=self.basis/np.linalg.norm(u);v=np.cross(u,n);v*=self.basis/np.linalg.norm(v)
                self.cache[key]=['( '+' '.join(format(float(x),'.17g') for x in p)+' )' for p in (base,base+u,base+v)]
            points=self.cache[key];order=(0,2,1) if negative else (0,1,2)
            result.append(' '.join(points[i] for i in order)+f' {material} 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0')
        return result
