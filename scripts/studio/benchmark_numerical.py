"""Synthetic spacecraft experiment with recorded real space-weather drivers."""
import argparse
import copy
import csv
import json
import platform
import time
from pathlib import Path
import numpy as np
from godsat.simulation.numerical import MU,RADIUS,integrate_experiment
from godsat.simulation.atmosphere import SpaceWeather,MsisAtmosphere


def experiment(count,duration=3600,step=10):
    objects=[];r=RADIUS+400;speed=np.sqrt(MU/r);inc=np.deg2rad(53)
    for j in range(count):
        phase=2*np.pi*j/count;raan=2*np.pi*(j%6)/6
        x,y,z=np.cos(phase),np.sin(phase)*np.cos(inc),np.sin(phase)*np.sin(inc)
        vx,vy,vz=-np.sin(phase),np.cos(phase)*np.cos(inc),np.cos(phase)*np.sin(inc)
        rotate=lambda a,b,c:[float(a*np.cos(raan)-b*np.sin(raan)),float(a*np.sin(raan)+b*np.cos(raan)),float(c)]
        objects.append({'id':f'synthetic-{j+1}','name':f'Synthetic numerical {j+1}',
            'position_gcrs_km':rotate(r*x,r*y,r*z),'velocity_gcrs_km_s':rotate(speed*vx,speed*vy,speed*vz),
            'mass_kg':120.,'drag_area_m2':1.2,'drag_coefficient':2.2})
    return {'schema':'godsat.numerical.v1','frame':'GCRS','epoch':'2026-11-08T18:55:00Z',
        'duration_seconds':duration,'integration_step_seconds':step,'output_step_seconds':60,
        'forces':{'j2':True,'drag':True,'third_bodies':True},
        'source':{'kind':'illustrative','reference':'Generated circular LEO initial states and hypothetical mass/area/Cd; not catalog or measured spacecraft states'},
        'objects':objects}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects',type=int,default=1000)
    parser.add_argument('--drivers',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('outputs/numerical-benchmark'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    config=experiment(args.objects);(args.output/'initial.json').write_text(json.dumps(config,indent=2)+'\n')
    atmosphere=MsisAtmosphere(SpaceWeather(args.drivers))
    start=time.perf_counter();scene,states=integrate_experiment(config,atmosphere);elapsed=time.perf_counter()-start
    scene['title']=f'NRLMSIS drag · {args.objects:,} synthetic spacecraft'
    (args.output/'scene.json').write_text(json.dumps(scene,separators=(',',':'),allow_nan=False))
    baseline=copy.deepcopy(config);baseline['forces']['drag']=False
    no_drag,reference=integrate_experiment(baseline);no_drag['title']=f'No-drag comparison · {args.objects:,} synthetic spacecraft'
    (args.output/'scene-no-drag.json').write_text(json.dumps(no_drag,separators=(',',':'),allow_nan=False))
    displacement=np.linalg.norm(states[-1,:,:3]-reference[-1,:,:3],axis=1)*1000
    with (args.output/'drag-comparison.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['object_index','object_id','delta_position_m'])
        writer.writerows((j+1,o['id'],float(displacement[j])) for j,o in enumerate(config['objects']))
    smaller=copy.deepcopy(config);smaller['objects']=smaller['objects'][:min(16,args.objects)];smaller['integration_step_seconds']=5
    _,refined=integrate_experiment(smaller,atmosphere)
    convergence=np.linalg.norm(states[:,:len(smaller['objects']),:3]-refined[:,:,:3],axis=2)*1000
    report={'scope':'Synthetic initial states and spacecraft properties; actual pinned space-weather input. Drag displacement is model sensitivity, not measured orbit error.',
        'platform':platform.platform(),'python':platform.python_version(),'objects':args.objects,'duration_seconds':3600,
        'integration_step_seconds':10,'frames':len(scene['times']),'coupled_run_seconds':elapsed,
        'force_evaluations':scene['source']['force_evaluations'],
        'drag_displacement_m':{'min':float(displacement.min()),'median':float(np.median(displacement)),'max':float(displacement.max())},
        'half_step_comparison':{'objects':len(smaller['objects']),'maximum_position_difference_m':float(convergence.max())},
        'atmosphere':scene['source']['atmosphere'],'frame_transform':scene['source']['frame_transform']}
    (args.output/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
