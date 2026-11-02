"""Probe unchanged upstream neighbor code and the source/port headless boundary.

Only MATLAB property annotations are removed from the class for Octave parsing.
The original control-flow guard is preserved. This cannot establish native
MATLAB/Mapping Toolbox parity or complete controller equivalence.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
UPSTREAM=Path('/home/omarramadan/Desktop/GoDSat-MnS-Framework')
PORT=Path('/home/omarramadan/Desktop/GodSAT/GoDSAT_Additional_IEEE_Experiments/production_godsat_octave')
OCTAVE=Path('/home/omarramadan/Desktop/GodSAT/.octave-env/bin/octave-cli')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def erase_property_annotations(source):
    out=[];edits=[];inside=False
    for number,line in enumerate(source.splitlines(),1):
        if re.match(r'^\s*properties(?:\s|$|\()',line):inside=True
        if inside:
            changed=re.sub(r'^(\s*\w+)\s+(?:\([^)]*\)\s+)?(?:double|logical)\b',r'\1',line)
            if changed!=line:edits.append({'line':number,'original':line,'compatibility':changed})
        else:changed=line
        out.append(changed)
        if inside and line.strip()=='end':inside=False
    return '\n'.join(out)+'\n',edits


def expected_neighbor(grid,row,col):
    best=(row,col);direction='goal'
    for dr,dc,label in [(-1,0,'up'),(1,0,'down'),(0,-1,'left'),(0,1,'right')]:
        r,c=row+dr,col+dc
        if 0<=r<len(grid) and 0<=c<len(grid[0]) and grid[r][c]>grid[best[0]][best[1]]:
            best=(r,c);direction=label
    return best[0],best[1],direction


def run(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    compat=output/'source-preserving-compat';compat.mkdir(exist_ok=True)
    original=UPSTREAM/'src/core/SatelliteRL.m'
    sanitized,edits=erase_property_annotations(original.read_text())
    (compat/'SatelliteRL.m').write_text(sanitized)
    helper=UPSTREAM/'src/core/findHighestNeighbor.m'
    shutil.copyfile(helper,compat/'findHighestNeighbor.m')
    # Support only gobjects(0), the native empty graphics placeholder used here.
    (compat/'gobjects.m').write_text("function out = gobjects(n)\n  assert(n == 0);\n  out = [];\nend\n")
    for file in (PORT/'compat').glob('*.m'):shutil.copyfile(file,compat/file.name)
    functions=output/'compat-functions';functions.mkdir(exist_ok=True)
    for file in compat.glob('*.m'):
        if file.name not in ['SatelliteRL.m','findHighestNeighbor.m']:shutil.copyfile(file,functions/file.name)
    with (UPSTREAM/'q_table.csv').open() as f:q=[[float(v) for v in r] for r in csv.reader(f)]
    grids=[q,np.zeros((3,3)).tolist(),[[0,3,0],[3,1,3],[0,3,0]],(-np.arange(9).reshape(3,3)).tolist()]
    rng=np.random.default_rng(19237)
    for rows,cols in [(1,1),(1,5),(5,1),(2,2),(3,4),(11,11)]:
        grids.extend(rng.integers(-5,6,(rows,cols)).tolist() for _ in range(10))
    cases=[]
    for gi,grid in enumerate(grids):
        for r in range(len(grid)):
            for c in range(len(grid[0])):cases.append({'grid':grid,'row':r+1,'col':c+1,'grid_index':gi})
    case_path=output/'neighbor-cases.json';case_path.write_text(json.dumps(cases))
    driver=output/'neighbor_probe.m'
    driver.write_text("""args = argv();
addpath(args{1});
cases = jsondecode(fileread(args{2}));
results = struct('row',{},'col',{},'direction',{});
for i=1:numel(cases)
  [neighbor, direction] = findHighestNeighbor(cases(i).grid, cases(i).row, cases(i).col);
  results(i).row = neighbor(1); results(i).col = neighbor(2); results(i).direction = direction;
end
fid = fopen(args{3}, 'w'); fputs(fid,jsonencode(results)); fclose(fid);
""")
    env=os.environ.copy();prefix=OCTAVE.parent.parent
    env.update(OCTAVE_HOME=str(prefix),OCTAVE_EXEC_HOME=str(prefix),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    results_path=output/'neighbor-results.json'
    p=subprocess.run([str(OCTAVE),'--no-history','--quiet',str(driver),str(compat),str(case_path),str(results_path)],
                     cwd=output,env=env,text=True,capture_output=True,timeout=120)
    (output/'neighbor-stdout.log').write_text(p.stdout);(output/'neighbor-stderr.log').write_text(p.stderr)
    if p.returncode:raise RuntimeError(p.stderr)
    results=json.loads(results_path.read_text())
    assert len(results)==len(cases)
    for case,result in zip(cases,results):
        r,c,d=expected_neighbor(case['grid'],case['row']-1,case['col']-1)
        assert (r+1,c+1,d)==(result['row'],result['col'],result['direction'])
    # Exercise the real upstream class's headless guard with a pending slew.
    probe=output/'headless_probe.m'
    probe.write_text("""args=argv(); addpath(args{3}); addpath(args{1});
ellipsoid=referenceEllipsoid('grs80','km');
sat=SatelliteRL('probe',[2000,.1,90,50,270,0],(0:2:6)',398600.4418,2*pi/86164.0905,ellipsoid);
sat.hSat=[]; sat.baseLookVec=[1;0;0]; sat.desiredLookVec=[0;1;0]; sat.slewInProgress=true;
sat.setQtable(ones(11,11),1);
sat.fovHalfAngle=deg2rad(5);sat.fov2HalfAngle=deg2rad(20);sat.fovNumRays=0; sat.showQtable=false;
sat.setSpatialMatrix(zeros(90,180),linspace(-90,88,90)',linspace(-180,178,180)');
SatelliteRL.setClaimMap(zeros(90,180));
before=sat.baseLookVec;
sat.updatePosition(2,[],[],[],{},false);
result=struct('pending_slew_unchanged',isequal(before,sat.baseLookVec),'before',before,'after',sat.baseLookVec,'lastUpdateIdx',sat.lastUpdateIdx,'qmode',sat.useQtableTracking,'implementation',which('SatelliteRL'));
fid=fopen(args{2},'w');fputs(fid,jsonencode(result));fclose(fid);
""")
    headless_path=output/'source-headless-result.json'
    h=subprocess.run([str(OCTAVE),'--no-history','--quiet',str(probe),str(compat),str(headless_path),str(functions)],cwd=output,env=env,text=True,capture_output=True,timeout=120)
    (output/'headless-stdout.log').write_text(h.stdout);(output/'headless-stderr.log').write_text(h.stderr)
    if h.returncode:raise RuntimeError(h.stderr)
    headless=json.loads(headless_path.read_text())
    assert headless['pending_slew_unchanged']
    port_path=output/'port-headless-result.json'
    hport=subprocess.run([str(OCTAVE),'--no-history','--quiet',str(probe),str(PORT/'src/core'),str(port_path),str(functions)],cwd=output,env=env,text=True,capture_output=True,timeout=120)
    (output/'port-headless-stdout.log').write_text(hport.stdout);(output/'port-headless-stderr.log').write_text(hport.stderr)
    if hport.returncode:raise RuntimeError(hport.stderr)
    port_result=json.loads(port_path.read_text())
    assert not port_result['pending_slew_unchanged']
    separation=float(np.rad2deg(np.arccos(np.clip(np.dot(headless['after'],port_result['after']),-1,1))))
    assert separation>1
    report={'status':'passed_upstream_neighbor_differential_and_source_headless_probe',
        'upstream_commit':subprocess.check_output(['git','-C',str(UPSTREAM),'rev-parse','HEAD'],text=True).strip(),
        'upstream_helper_sha256':sha(helper),'copied_helper_sha256':sha(compat/'findHighestNeighbor.m'),
        'upstream_class_sha256':sha(original),'sanitized_class_sha256':sha(compat/'SatelliteRL.m'),
        'property_annotation_edits':edits,'octave_executable':str(OCTAVE),
        'neighbor_cases_checked':len(cases),'actual_qtable_cells_checked':len(q)*len(q[0]),
        'qtable_sha256':sha(UPSTREAM/'q_table.csv'),'source_headless_behavior':headless,
        'existing_port_headless_behavior':port_result,'same_input_boresight_separation_deg':separation,
        'port_class_sha256':sha(PORT/'src/core/SatelliteRL.m'),
        'cases_sha256':sha(case_path),'results_sha256':sha(results_path),
        'conclusion':'The unchanged upstream neighbor helper matches the independent strict-scan implementation on every supplied cell/case. The original headless updatePosition preserves a pending slew without advancing FOV state. The existing compatibility port deliberately calls updateFOV in headless mode, so its headless control flow is not identical to upstream.',
        'scope':'Component differential tests and a concrete source headless behavior probe under property-type-erased Octave parsing with explicit geodetic/empty-graphics compatibility helpers. Not native MATLAB bitwise parity, not a full controller equivalence proof, and not a reproduction of the unavailable seven-factor actor–critic baseline.'}
    (output/'original-controller-probe.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'outputs/faithful-reproduction-20261027/controller-probes')
    args=p.parse_args();r=run(args.output);print(json.dumps({'status':r['status'],'cases':r['neighbor_cases_checked'],'headless':r['source_headless_behavior']}))
