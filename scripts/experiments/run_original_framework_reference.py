"""Execute a separately identified upstream-derived Octave GoDSAT reference case."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_metrics(metrics, threshold):
    fraction = float(metrics['custody_fraction'])
    live, custody = int(metrics['live_ticks']), int(metrics['custody_ticks'])
    if not 0<=fraction<=1 or live<=0 or not 0<=custody<=live:
        raise ValueError('Invalid reference custody denominator or count')
    if not math.isclose(fraction,custody/live,abs_tol=1e-12,rel_tol=0):
        raise ValueError('Reference custody fraction does not reproduce from ticks')
    if bool(metrics['failure']) != (fraction<threshold):raise ValueError('Reference threshold flag mismatch')
    if custody>int(metrics['q_active_ticks']) or custody>int(metrics['availability_ticks']):
        raise ValueError('Firm custody exceeds available Q-tracking ticks')
    for key in ['handoff_count','handoff_latency_s','qmode_reacquisition_s','claimmap_conflicts']:
        if not math.isfinite(float(metrics[key])) or float(metrics[key])<0:
            raise ValueError(f'Invalid reference metric {key}')


def run(upstream, port, octave, trajectory, campaign, output, seeds):
    upstream,port,octave,trajectory,campaign,output = [path.resolve() for path in [upstream,port,octave,trajectory,campaign,output]]
    if output.exists() and any(output.iterdir()):raise FileExistsError(f'Nonempty reference output: {output}')
    if digest(upstream/'q_table.csv')!=digest(port/'q_table.csv'):
        raise ValueError('Reference port does not use the inventoried upstream Q table')
    source_files = sorted(port.rglob('*.m'))+[port/'q_table.csv',port/'LICENSE.upstream']
    receipts = [{'path':str(path),'sha256':digest(path)} for path in source_files]
    revision = subprocess.run(['git','-C',str(upstream),'rev-parse','HEAD'],text=True,capture_output=True,check=True).stdout.strip()
    version = subprocess.run([str(octave),'--version'],text=True,capture_output=True,check=True).stdout.splitlines()[0]
    output.mkdir(parents=True,exist_ok=True)
    target,config_path = output/'input_trajectory.csv',output/'campaign.json'
    shutil.copyfile(trajectory,target);shutil.copyfile(campaign,config_path)
    config=json.loads(config_path.read_text())
    environment=os.environ.copy();home=octave.parent.parent
    environment.update(OCTAVE_HOME=str(home),OCTAVE_EXEC_HOME=str(home),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    results=[]
    for seed in seeds:
        destination=output/f'seed-{seed}.json'
        command=[str(octave),'--no-history','--quiet',str(port/'run_campaign_cli.m'),
                 str(target),str(config_path),str(seed),str(destination)]
        process=subprocess.run(command,cwd=output,env=environment,text=True,capture_output=True,timeout=1200)
        (output/f'seed-{seed}.stdout.log').write_text(process.stdout)
        (output/f'seed-{seed}.stderr.log').write_text(process.stderr)
        if process.returncode or not destination.exists():
            raise RuntimeError(f'Octave reference failed for seed {seed}: {process.stderr[-1500:]}')
        metrics=json.loads(destination.read_text());validate_metrics(metrics,config['failure_custody_threshold'])
        results.append({'seed':seed,'metrics':metrics,'output_sha256':digest(destination)})
        print(json.dumps({'seed':seed,'custody_fraction':metrics['custody_fraction'],
                          'live_ticks':metrics['live_ticks'],'custody_ticks':metrics['custody_ticks']}),flush=True)
    if any(digest(Path(row['path']))!=row['sha256'] for row in receipts):
        raise ValueError('Original reference port changed during execution')
    comparisons=['custody_fraction','handoff_count','handoff_latency_s','qmode_reacquisition_s','claimmap_conflicts']
    result={'status':'completed_and_tick_metrics_reconciled',
        'upstream_root':str(upstream),'upstream_commit':revision,'port_root':str(port),
        'runtime':version,'runtime_executable':str(octave),'reference_source_files':receipts,
        'q_table_sha256':digest(port/'q_table.csv'),'trajectory_original':str(trajectory),
        'trajectory_sha256':digest(target),'campaign_sha256':digest(config_path),'results':results,
        'different_seed_outputs_identical_on_selected_metrics':all(
            row['metrics'][key]==results[0]['metrics'][key] for row in results for key in comparisons),
        'scope':'Execution and tick-metric consistency reference for the existing upstream-derived dual-FOV/gradient/Q-table Octave port. Uses its fixed constructed constellation and supplied elapsed-time trajectory convention. It is not a catalog-history run, a new performance estimate, MATLAB/Mapping Toolbox bitwise parity, an actor-critic equivalence proof, or compliance with the missing factorial-design PDF. The borrowed reference failure threshold is not a verified requirement of that PDF.'}
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['upstream','port','octave','trajectory','campaign','output']:
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--seeds',default='101,211')
    args=parser.parse_args();run(args.upstream,args.port,args.octave,args.trajectory,args.campaign,args.output,
        [int(seed) for seed in args.seeds.split(',')])


if __name__=='__main__':main()
