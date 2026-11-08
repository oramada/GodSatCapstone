"""Build direct-propagation references for a stratified subset of a real scene."""
import argparse
import datetime as dt
import json
from pathlib import Path
import numpy as np
from godsat.simulation.catalog import load_catalog, propagate, to_itrs
from godsat.simulation.environment import utc
from godsat.studio.scene import load_scene


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--scene',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    scene=load_scene(args.scene); records,source=load_catalog(args.catalog)
    if source['sha256']!=scene['source']['catalog']['sha256']:
        raise ValueError('Scene and catalog hashes differ')
    objects={o['id']:o for o in scene['objects'] if all(p is not None for p in o['positions_km'])}
    available=[r for r in records if r[0] in objects]
    if len(available)<1: raise ValueError('No continuously valid objects')
    selected={available[i][0] for i in np.linspace(0,len(available)-1,min(100,len(available)),dtype=int)}
    # Include extreme eccentricities and mean motions; do not validate only circular LEO.
    for key in (lambda r:r[2].ecco, lambda r:r[2].no_kozai):
        order=sorted(available,key=key)
        selected.update(r[0] for r in order[:10]+order[-10:])
    records=[r for r in available if r[0] in selected]
    times=[utc(t) for t in scene['times']]
    specs=[(k,u) for k in range(len(times)-1) for u in (.1,.25,.5,.75,.9)]
    epochs=[times[k]+(times[k+1]-times[k])*u for k,u in specs]
    p,_,codes,_=propagate(records,epochs,scene['source']['max_element_age_hours'])
    if np.any(codes): raise ValueError('Off-grid propagation failed; inspect input window')
    if scene['frame']=='ITRS': p,_=to_itrs(p,epochs)
    elif scene['frame']!='TEME': raise ValueError('Only SGP4 export frames are supported')
    cases=[{'step':k+u,'positions_km':p[:,i].tolist()} for i,(k,u) in enumerate(specs)]
    subset={**scene,'objects':[objects[r[0]] for r in records]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'scene':subset,'cases':cases},allow_nan=False,separators=(',',':')))
    print(json.dumps({'objects':len(records),'samples':len(records)*len(specs),
        'eccentricity_range':[min(r[2].ecco for r in records),max(r[2].ecco for r in records)],
        'catalog_sha256':source['sha256'],'output':str(args.output)},indent=2))


if __name__=='__main__':main()
