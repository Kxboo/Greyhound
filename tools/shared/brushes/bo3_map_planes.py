"""BO3 MAP plane formatting and readback shared by game converters."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import re
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


def read_map_planes(text):
    out = []
    for line in text.splitlines():
        groups = re.findall(r'\(\s*([^()]*)\)', line)
        if not groups:
            continue
        if len(groups) != 3:
            raise ValueError('Invalid face syntax')
        a, b, c = [np.array([float(x) for x in g.split()]) for g in groups]
        n = -np.cross(b-a, c-a)
        n /= np.linalg.norm(n)
        out.append([*n, float(n@a)])
    return out


def face_text(equations,center,material):
    lines=[]
    for plane in equations:
        n=plane[:3];d=plane[3]
        base=center+n*(d-n@center)
        axis=np.eye(3)[np.argmin(abs(n))]
        u=np.cross(n,axis);u*=128/np.linalg.norm(u)
        v=np.cross(u,n);v*=128/np.linalg.norm(v)
        text=' '.join('( '+' '.join(format(float(x),'.17g') for x in p)+' )'
                      for p in [base,base+u,base+v])
        lines.append(text+f' {material} 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0')
    return lines
