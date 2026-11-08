"""Synthetic capacity benchmark, not validation against measured satellite truth.

Run: .venv/bin/python -m scripts.studio.benchmark_simulation --objects 10000
"""
import argparse
import datetime as dt
import json
import platform
import time
from pathlib import Path
import numpy as np
from sgp4.api import Satrec, WGS72
from godsat.simulation.catalog import build_scene, make_times, propagate, to_itrs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', type=int, default=10000)
    parser.add_argument('--step', type=float, default=20)
    parser.add_argument('--output', type=Path, default=Path('outputs/simulation-benchmark'))
    args = parser.parse_args()
    start = dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc)
    records = []
    for j in range(args.objects):
        satellite = Satrec()
        # Variety of circular/low-eccentricity LEO planes. All explicitly synthetic.
        epoch = (start - dt.datetime(1949, 12, 31, tzinfo=dt.timezone.utc)).total_seconds()/86400
        satellite.sgp4init(WGS72, 'i', j+1, epoch, .00001, 0, 0, .001,
                          0, np.deg2rad(53+(j % 4)*10), 2*np.pi*(j%100)/100,
                          (14.5+(j%10)*.1)*2*np.pi/1440, 2*np.pi*(j//100)/max(1,args.objects/100))
        records.append((str(j+1), f'SYNTHETIC {j+1}', satellite))
    times = make_times(start.isoformat(), 600, args.step)
    t0 = time.perf_counter()
    scene = build_scene(records, times, {'kind': 'synthetic', 'description': 'Generated capacity-test elements'})
    elapsed = time.perf_counter()-t0
    scene['source']['kind'] = 'illustrative'
    scene['title'] = f'Synthetic capacity test · {args.objects:,} objects'
    scene['warnings'].insert(0, 'All identities and orbits are synthetic. This is a capacity test, not a real constellation.')
    t0 = time.perf_counter()
    payload = json.dumps(scene, allow_nan=False, separators=(',', ':')).encode()
    serialization = time.perf_counter()-t0
    # Direct SGP4 at off-grid instants is independent of the interpolation path.
    phases = [.1, .25, .5, .75, .9]
    reference_times = [times[k]+(times[k+1]-times[k])*phase for k in range(len(times)-1) for phase in phases]
    truth, _, _, _ = propagate(records[:100], reference_times)
    truth, _ = to_itrs(truth, reference_times)
    endpoints=np.array([o['positions_km'] for o in scene['objects'][:100]])
    velocities=np.array([o['velocities_km_s'] for o in scene['objects'][:100]])
    linear=[]; hermite=[]; cases=[]
    for c, (k, u) in enumerate((k,u) for k in range(len(times)-1) for u in phases):
        h=(times[k+1]-times[k]).total_seconds(); p=endpoints[:,k]; q=endpoints[:,k+1]
        straight=(1-u)*p+u*q
        curved=(2*u**3-3*u**2+1)*p+(u**3-2*u**2+u)*h*velocities[:,k]+(-2*u**3+3*u**2)*q+(u**3-u**2)*h*velocities[:,k+1]
        linear.extend(np.linalg.norm(straight-truth[:,c],axis=1)*1000)
        hermite.extend(np.linalg.norm(curved-truth[:,c],axis=1)*1000)
        cases.append({'step':k+u,'positions_km':truth[:,c].tolist()})
    report = {'scope': 'Synthetic end-to-end scene preparation; excludes HTTP, browser and GPU. Off-grid errors compare display interpolation to direct SGP4/Astropy, not measured truth.',
              'platform': platform.platform(), 'python': platform.python_version(),
              'objects': args.objects, 'frames': len(times), 'cadence_seconds': args.step,
              'build_seconds': elapsed, 'serialize_seconds': serialization, 'bytes': len(payload),
              'status_counts': scene['source']['status_counts'],
              'interpolation_reference': 'Direct SGP4 + Astropy ITRS at five fractions of every interval, first 100 synthetic objects',
              'interpolation_linear_max_m': float(np.max(linear)),
              'interpolation_linear_rms_m': float(np.sqrt(np.mean(np.square(linear)))),
              'interpolation_hermite_max_m': float(np.max(hermite)),
              'interpolation_hermite_rms_m': float(np.sqrt(np.mean(np.square(hermite)))),
              'frame_transform': scene['source']['frame_transform']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'scene.json').write_bytes(payload)
    (args.output/'interpolation-reference.json').write_text(json.dumps({'scene':{**scene,'objects':scene['objects'][:100]},'cases':cases},separators=(',',':')))
    (args.output/'benchmark.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
