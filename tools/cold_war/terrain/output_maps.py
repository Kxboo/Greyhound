"""Convert the captured composition shader's outputs to conventional maps.

Normals in this CS are in a flat terrain projection frame. The model's UV V
points toward -world Y after the CAST importer flips V, hence the green flip.
How CW projects these detail normals onto its adaptive terrain is separate.
"""
import numpy as np
from scipy.ndimage import distance_transform_edt


def decode_normal(encoded):
    q=(np.asarray(encoded,dtype=np.float32)-np.float32(.5))*np.float32(4)
    length2=np.sum(q*q,axis=-1,keepdims=True)
    xy=q*np.sqrt(np.maximum(np.float32(0),np.float32(1)-length2*np.float32(.25)))
    return np.concatenate([xy,np.float32(1)-length2*np.float32(.5)],axis=-1)


def to_maps(outputs):
    color,packed,extra=outputs
    valid=color[...,3]>.5
    normal=decode_normal(packed[...,:2])
    normal[...,1]*=-1
    maps=dict(c=color[...,:3],n=normal*np.float32(.5)+np.float32(.5),
              g=np.float32(1)-packed[...,2],o=extra[...,0])
    # Shader holes have conspicuous debug defaults. Geometry already removes
    # holes, so extend nearby valid shading for filtering at remaining edges.
    if not valid.any():
        maps=dict(c=np.full_like(color[...,:3],.5),n=np.broadcast_to([.5,.5,1],normal.shape),
                  g=np.zeros_like(extra[...,0]),o=np.ones_like(extra[...,0]))
    elif not valid.all():
        indices=distance_transform_edt(~valid,return_distances=False,return_indices=True)
        maps={k:np.where(valid[...,None],a,a[tuple(indices)]) if a.ndim==3 else np.where(valid,a,a[tuple(indices)]) for k,a in maps.items()}
    return {k:np.uint8(np.clip(a,0,1)*255+.5) for k,a in maps.items()},valid
