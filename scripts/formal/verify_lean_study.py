"""Build Lean proofs, audit theorem axioms and bind finite designs to real CSVs.

Never reports original-controller or empirical-baseline equivalence merely
because mathematical/specification theorems compile.
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
import subprocess
import datetime as dt
from fractions import Fraction

ROOT=Path(__file__).resolve().parents[2]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(lake,elan_home,output):
    project=ROOT/'formal';output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    if elan_home:env['ELAN_HOME']=str(elan_home)
    declarations=[]
    for path in sorted((project/'GoDSAT').glob('*.lean')):
        if path.name in ['AxiomAudit.lean','Export.lean']:continue
        text=path.read_text()
        uncommented=re.sub(r'/\-.*?\-/','',text,flags=re.S)
        uncommented=re.sub(r'--[^\n]*','',uncommented)
        if re.search(r'\b(sorry|admit|axiom|native_decide|unsafe)\b',uncommented):
            raise ValueError('Untrusted proof escape in '+str(path))
        namespace=re.search(r'^namespace\s+([\w.]+)',text,re.M).group(1)
        declarations.extend(namespace+'.'+name for name in re.findall(r'^theorem\s+(\w+)',text,re.M))
    axiom_file=project/'GoDSAT/AxiomAudit.lean'
    axiom_file.write_text('import GoDSAT\n\n'+''.join('#print axioms '+name+'\n' for name in declarations))
    def run(args,label):
        path=output/(label+'.log')
        with path.open('w') as stream:
            process=subprocess.run([str(lake),*args],cwd=project,env=env,text=True,stdout=stream,stderr=subprocess.STDOUT)
        contents=path.read_text()
        if process.returncode:raise RuntimeError(label+' failed: '+contents[-4000:])
        return contents
    version=run(['env','lean','--version'],'lean-version').strip()
    run(['build'],'lean-full-build')
    axioms=run(['env','lean','GoDSAT/AxiomAudit.lean'],'lean-axioms')
    if any(word in axioms for word in ['sorryAx','ofReduceBool','ofReduceNat']):
        raise ValueError('Unchecked decision or admitted theorem in axiom audit')
    audited={}
    for name in declarations:
        match=re.search(re.escape(name)+r"' depends on axioms:\s*\[([^\]]*)\]",axioms,re.S)
        if match:deps=[x.strip() for x in match.group(1).split(',') if x.strip()]
        elif re.search(re.escape(name)+r"' does not depend on any axioms",axioms):deps=[]
        else:raise ValueError('Missing kernel axiom output for '+name)
        if set(deps)-{'propext','Classical.choice','Quot.sound'}:raise ValueError('Unexpected axiom: '+name)
        audited[name]=deps
    exported=run(['env','lean','--run','GoDSAT/Export.lean'],'lean-specification-export')
    # The executable's final line is the JSON object, separate from warnings.
    specification=json.loads(next(line for line in reversed(exported.splitlines()) if line.startswith('{')))
    (output/'checked-finite-specification.json').write_text(json.dumps(specification,indent=2)+'\n')
    probes=output/'controller-probes'
    probe=json.loads((probes/'original-controller-probe.json').read_text())
    assert sha(probes/'neighbor-cases.json')==probe['cases_sha256']
    assert sha(probes/'neighbor-results.json')==probe['results_sha256']
    source_root=Path('/home/omarramadan/Desktop/GoDSat-MnS-Framework')
    assert sha(source_root/'q_table.csv')==probe['qtable_sha256']
    with (source_root/'q_table.csv').open() as f:q=[Fraction(v) for row in csv.reader(f) for v in row]
    assert [int(value*10000) for value in q]==[int(v) for v in specification['original_qtable_scaled']]
    neighbor=json.loads((probes/'neighbor-results.json').read_text())[:121]
    assert [11*(int(row['row'])-1)+int(row['col'])-1 for row in neighbor]==specification['original_neighbor_outputs']
    for key,file in [('source_observation','source-headless-result.json'),('port_observation','port-headless-result.json')]:
        observed=json.loads((probes/file).read_text())['after']
        assert [Fraction(str(x)) for x in observed]==[Fraction(int(n),int(d)) for n,d in specification[key]]
    bindings=[]
    for name in ['paper-reference-cpu-20261024','all-orbits-active-hosts-cpu-20261024','governing-design-physical-leo-20261025']:
        folder=ROOT/'outputs'/name
        with (folder/'screening_design.csv').open() as f:screen=list(csv.DictReader(f))
        assert len(screen)==16 and len({int(r['standard_order']) for r in screen})==16
        for row in screen:
            assert [int(float(row[k])) for k in 'ABCDEFG']==specification['screening'][int(row['standard_order'])]
        with (folder/'rsm_design.csv').open() as f:ccd=list(csv.DictReader(f))
        actual=[]
        for row in ccd:
            a,b,c=[int(float(row[k])) for k in ['x1','x2','x3']]
            actual.append([1,a,b,c,a*a,b*b,c*c,a*b,a*c,b*c])
        assert sorted(actual)==sorted(specification['ccd'])
        bindings.append({'campaign':name,'screen_rows_checked':16,'ccd_rows_checked':15,
            'screening_csv_sha256':sha(folder/'screening_design.csv'),'ccd_csv_sha256':sha(folder/'rsm_design.csv'),
            'scope':'Exact executed design coordinates match the Lean-exported specification. This is not controller or sensor equivalence.'})
    sources={str(path.relative_to(ROOT)):sha(path) for path in sorted(project.rglob('*.lean')) if '.lake' not in path.parts}
    for name in ['lakefile.toml','lake-manifest.json','lean-toolchain']:
        sources[str((project/name).relative_to(ROOT))]=sha(project/name)
    for name in ['neighbor-cases.json','neighbor-results.json','source-headless-result.json',
                 'port-headless-result.json','original-controller-probe.json']:
        sources[str((probes/name).relative_to(ROOT))]=sha(probes/name)
    for name in ['scripts/formal/verify_lean_study.py','scripts/formal/probe_original_controller.py',
                 'formal/generate_ccd_certificate.py','formal/generate_original_neighbor_certificate.py']:
        sources[name]=sha(ROOT/name)
    bad=output/'rejected-paper-claims.lean'
    bad.write_text('''import GoDSAT

theorem printed_alias_relation_would_be_false :
    ∀ r : Fin 16, GoDSAT.Design.aliasColumn r 121 = 1 := by decide

theorem single_center_cannot_supply_positive_pure_error :
    GoDSAT.ResponseSurface.pureErrorAvailable 15 15 := by
  change (15 : Nat) < 15
  decide
''')
    negative=subprocess.run([str(lake),'env','lean',str(bad.resolve())],cwd=project,env=env,text=True,capture_output=True)
    rejection=negative.stdout+negative.stderr
    (output/'negative-controls.log').write_text(rejection)
    if negative.returncode==0 or rejection.count('is false')!=2:
        raise ValueError('False paper claims were not rejected for the expected mathematical reasons')
    negative_receipt={'status':'expected_false_paper_claims_rejected_by_Lean','exit_code':negative.returncode,
        'source_sha256':sha(bad),'log_sha256':sha(output/'negative-controls.log'),
        'scope':'Expected compiler failures outside the accepted proof library; not admitted as theorems.'}
    (output/'negative-controls.json').write_text(json.dumps(negative_receipt,indent=2)+'\n')
    result={'status':'kernel_checked_mathematical_proofs_with_explicit_boundaries',
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'lean_version':version,
        'lake_executable':str(lake),'elan_home':str(elan_home) if elan_home else None,
        'source_hashes':sources,'theorems_checked':len(declarations),'theorem_axioms':audited,
        'design_csv_bindings':bindings,'source_pdf_sha256':sha((ROOT/'docs/papers/methodology.pdf')),
        'original_helper_binding':{'native_helper_differential_cases':probe['neighbor_cases_checked'],
            'qtable_cells_Lean_outputs_match':121,'headless_counterexample_matches_observations':True,
            'boresight_separation_degrees':probe['same_input_boresight_separation_deg'],
            'scope':'The finite certificate matches recorded source/helper observations; it does not establish complete native MATLAB/controller equivalence.'},
        'negative_controls':negative_receipt,
        'not_proved':['Physical/model assumptions hold for real spacecraft','Error independence, homoscedasticity or model adequacy','Original-controller/full Python equivalence','Published actor–critic baseline reproduction','Empirical custody or energy gains'],
        'conditional_theorem':'GoDSAT.Refinement.conditional_trace_refinement requires a separately established actual one-step implementation relation. It is not instantiated as original-controller equivalence.',
        'scope':'Kernel-checked finite design/CCD mathematics, real quadratic algebra, conditional model invariants and conditional transition-system reasoning. No custom axioms, admitted proofs or native decision axioms accepted.'}
    (output/'lean-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lake',type=Path,default=Path.home()/'.elan/bin/lake')
    p.add_argument('--elan-home',type=Path);p.add_argument('--output',type=Path,default=ROOT/'outputs/faithful-reproduction-20261027')
    args=p.parse_args();r=verify(args.lake,args.elan_home,args.output)
    print(json.dumps({'status':r['status'],'theorems':r['theorems_checked'],'design_bindings':len(r['design_csv_bindings'])}))
