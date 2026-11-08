"""Reproducible synthetic extended-force benchmark and paired sensitivities."""
import argparse
import copy
import hashlib
import json
import platform
import time
from pathlib import Path
import numpy as np
from scripts.studio.benchmark_numerical import experiment
from godsat.simulation.numerical import integrate_experiment
from godsat.simulation.atmosphere import SpaceWeather, MsisAtmosphere


def summary(values):
    return {'min':float(np.min(values)),'median':float(np.median(values)),'max':float(np.max(values))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects',type=int,default=1000)
    parser.add_argument('--drivers',type=Path)
    parser.add_argument('--output',type=Path,default=Path('outputs/extended-forces'))
    args=parser.parse_args()
    template=json.loads(Path('configs/numerical-extended.json').read_text())
    config=experiment(args.objects,step=10)
    config['gravity_model']=template['gravity_model']
    config['forces']=template['forces'].copy();config['forces']['drag']=bool(args.drivers)
    config['source']['reference']+='; hypothetical Cr=1.3 and radiation area=1.2 m²'
    for obj in config['objects']:obj.update(radiation_area_m2=1.2,radiation_coefficient=1.3)
    atmosphere=MsisAtmosphere(SpaceWeather(args.drivers)) if args.drivers else None
    start=time.perf_counter();scene,states=integrate_experiment(config,atmosphere);elapsed=time.perf_counter()-start
    scene['title']=f'Extended forces · {args.objects:,} synthetic spacecraft'
    small=copy.deepcopy(config);small['objects']=small['objects'][:min(16,args.objects)]
    # Each variant is paired against the same initial states and all other forces.
    _,reference=integrate_experiment(small,atmosphere)
    effects={}
    for label in ['higher_zonals','solar_radiation_pressure','schwarzschild']:
        variant=copy.deepcopy(small)
        if label=='higher_zonals':variant['gravity_model']['coefficients']={'2':variant['gravity_model']['coefficients']['2']}
        else:variant['forces'][label]=False
        _,other=integrate_experiment(variant,atmosphere)
        effects[label]=summary(np.linalg.norm(reference[-1,:,:3]-other[-1,:,:3],axis=1)*1000)
    convergence={}
    small['integration_step_seconds']=5;_,fine=integrate_experiment(small,atmosphere)
    small['integration_step_seconds']=2.5;_,finer=integrate_experiment(small,atmosphere)
    convergence['10_vs_5_s_max_m']=float(np.max(np.linalg.norm(reference[:,:,:3]-fine[:,:,:3],axis=2))*1000)
    convergence['5_vs_2.5_s_max_m']=float(np.max(np.linalg.norm(fine[:,:,:3]-finer[:,:,:3],axis=2))*1000)
    report={'schema':'godsat.extended-forces-benchmark.v1','scope':'Synthetic osculating initial states and spacecraft parameters. Paired displacements are model sensitivities, not tracking accuracy.',
        'objects':args.objects,'frames':len(scene['times']),'duration_seconds':config['duration_seconds'],
        'step_seconds':10,'run_seconds':elapsed,'platform':platform.platform(),
        'python':platform.python_version(),'paired_objects':len(small['objects']),
        'paired_final_displacement_m':effects,'convergence':convergence,
        'forces':config['forces'],'gravity_model':config['gravity_model'],'solar_radiation':scene['source']['solar_radiation'],
        'atmosphere':scene['source']['atmosphere'],'frame_transform':scene['source']['frame_transform'],
        'experiment_sha256':scene['source']['experiment_sha256'],'numerical_source_sha256':scene['source']['numerical_source_sha256'],
        'additional_forces_source_sha256':scene['source']['additional_forces_source_sha256'],
        'benchmark_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'initial.json').write_text(json.dumps(config,indent=2)+'\n')
    (args.output/'scene.json').write_text(json.dumps(scene,separators=(',',':'),allow_nan=False))
    (args.output/'benchmark.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:report[k] for k in ['objects','run_seconds','paired_final_displacement_m','convergence','solar_radiation']},indent=2))


if __name__=='__main__':main()
