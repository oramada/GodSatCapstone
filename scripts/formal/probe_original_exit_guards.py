"""Exercise actual source/port early-exit paths without graphics or propagation.

Consumes the source-preserving, property-type-erased class from the prior probe.
Calls public updateFOV directly: this is not a reachable full-scenario trace or
an assertion of MATLAB runtime parity. No controller control flow is rewritten.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import hashlib
import json
import os
from pathlib import Path
import subprocess

from scripts.formal.probe_original_controller import ROOT, UPSTREAM, PORT, OCTAVE, erase_property_annotations


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run():
    output = ROOT / 'outputs/faithful-reproduction-20261027/exit-guard-probes'
    output.mkdir(parents=True, exist_ok=True)
    compat = output.parent / 'controller-probes/source-preserving-compat'
    source = UPSTREAM / 'src/core/SatelliteRL.m'
    expected, edits = erase_property_annotations(source.read_text())
    assert (compat / 'SatelliteRL.m').read_text() == expected
    driver = output / 'exit_guards.m'
    driver.write_text('''args=argv(); addpath(args{1});
guards={'invalid_global_index','empty_position','lost_los','landed_target','confirmed_handoff'};
results=struct([]); n=0;
for g=1:numel(guards)
 for count=0:2
  sat=SatelliteRL(); sat.ID=1;
  sat.ellipsoid=struct('SemimajorAxis',6378); sat.rEcef=[7000;0;0];
  sat.baseLookVec=[0;1;0]; sat.hQtable=[];
  sat.useQtableTracking=true; sat.trackTargetIdx=1; sat.qLostCounter=2;
  sat.trackTargetGlobalIdx=1; sat.trackTargetPos=[6999;0;0];
  sat.currentOwnerArray=1; sat.trackLockedGlobalIdx=0;
  initial=zeros(3,4); initial(3,4)=2;
  if count>=1, initial(1,1)=1; end
  if count>=2, initial(2,2)=1; end
  SatelliteRL.setClaimMap(initial);
  switch guards{g}
   case 'invalid_global_index', sat.trackTargetGlobalIdx=[];
   case 'empty_position', sat.trackTargetPos=[];
   case 'lost_los', sat.trackTargetPos=[-7000;0;0];
   case 'landed_target'
    sat.trackLockedGlobalIdx=1; targets=struct('hasLanded',true);
   case 'confirmed_handoff'
    sat.currentOwnerArray=2;
    sats=repmat(struct('useQtableTracking',false,'trackTargetIdx',0,'trackTargetGlobalIdx',[]),1,2);
    sats(2).useQtableTracking=true; sats(2).trackTargetIdx=1; sats(2).trackTargetGlobalIdx=1;
  end
  sat.updateFOV(1,[true,true]);
  n=n+1;
  results(n).guard=guards{g}; results(n).initial_own_claim_count=count;
  results(n).qmode=sat.useQtableTracking; results(n).track_index=sat.trackTargetIdx;
  results(n).lost_counter=sat.qLostCounter; results(n).locked_index=sat.trackLockedGlobalIdx;
  results(n).slew_pending=sat.slewInProgress; results(n).desired=sat.desiredLookVec;
  results(n).claim_map_unchanged=isequal(initial,SatelliteRL.getClaimMap());
  results(n).own_claims_after=sum(SatelliteRL.getClaimMap()(:)==1);
  results(n).implementation=which('SatelliteRL');
 end
end
fid=fopen(args{2},'w'); fputs(fid,jsonencode(results)); fclose(fid);
''')
    env = os.environ.copy()
    env.update(OCTAVE_HOME=str(OCTAVE.parent.parent), OCTAVE_EXEC_HOME=str(OCTAVE.parent.parent),
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    observations = {}
    for name, directory in [('source', compat), ('port', PORT / 'src/core')]:
        path = output / (name + '-results.json')
        p = subprocess.run([str(OCTAVE), '--no-history', '--quiet', str(driver), str(directory), str(path)],
                           cwd=output, env=env, text=True, capture_output=True, timeout=120)
        (output / (name + '-stdout.log')).write_text(p.stdout)
        (output / (name + '-stderr.log')).write_text(p.stderr)
        if p.returncode:
            raise RuntimeError(p.stderr)
        rows = json.loads(path.read_text())
        assert len(rows) == 15
        for row in rows:
            assert not row['qmode'] and row['track_index'] == 0 and row['lost_counter'] == 0
            assert row['slew_pending'] and row['desired'] == [-1, 0, 0]
            assert row['claim_map_unchanged']
            assert row['own_claims_after'] == row['initial_own_claim_count']
        observations[name] = rows
    def behavior(rows):
        return [{k: v for k, v in row.items() if k != 'implementation'} for row in rows]
    assert behavior(observations['source']) == behavior(observations['port'])
    receipt = {
        'status': 'source_and_port_match_on_15_early_exit_fixtures',
        'implementations_tested': 2, 'fixtures_per_implementation': 15,
        'guards': sorted({r['guard'] for r in observations['source']}),
        'own_claims_retained_in_nonzero_claim_fixtures': 20,
        'finding': 'All five tested early Q-mode exits reset mode/index/counter and command nadir slew, but preserve the claim map, including any pre-existing claims owned by the exiting satellite.',
        'scope': 'Public-method synthetic state fixtures under Octave; not a proof that these states occur in the published scenario, cause a performance deficit, or match native MATLAB. Refresh-claim lemmas do not describe these exit paths.',
        'source_sha256': sha(source), 'compatibility_sha256': sha(compat / 'SatelliteRL.m'),
        'port_sha256': sha(PORT / 'src/core/SatelliteRL.m'),
        'driver_sha256': sha(driver), 'script_sha256': sha(__file__),
        'property_annotation_edits': edits,
        'result_sha256': {name: sha(output / (name + '-results.json')) for name in observations},
    }
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    r = run()
    print(json.dumps({k: r[k] for k in ['status', 'implementations_tested', 'fixtures_per_implementation', 'finding']}))
