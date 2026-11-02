import csv
import io
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts.experiments.finish_quarterly_parallel import checkpoint_rows,observe_worker


def sample():
    design={'dates':['2026-01-01'],'regimes':['leo'],'modes':['independent'],
        'replicates':1,'model_seeds':[101],'rates':[0.,.2],
        'config':{'dropout_seed':7441,'duration_minutes':1,'step_seconds':60,'agents':1}}
    base={'date':'2026-01-01','regime':'leo','mode':'independent','replicate':0,
        'seed':7441,'model_seed':101,'custody_continuity':.5,'observable_custody':.5,
        'slew_energy_proxy':.1,'false_track_proxy':0.,'conflict_rate':0.,'objective':.4,
        'valid_target_fraction':1.,'dropout_rate_observed':0.,'dropout_trials':1,
        'dropout_misses':0,'attempts':1,'steps':1,'dropout_probability':0.}
    return design,[base,{**base,'dropout_probability':.2}]


def encode(rows):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode()


def test_checkpoint_requires_complete_unique_cells_before_handoff():
    design,rows=sample()
    assert len(checkpoint_rows(encode(rows),design)[0])==2
    with pytest.raises(ValueError,match='incomplete'):checkpoint_rows(encode(rows[:1]),design)
    with pytest.raises(ValueError,match='keys'):checkpoint_rows(encode(rows+[rows[0]]),design)
    with pytest.raises(ValueError,match='Empty'):checkpoint_rows(encode(rows).splitlines()[0]+b'\n',design)


@pytest.mark.parametrize('change',[{'seed':1},{'custody_continuity':float('nan')},
                                  {'dropout_misses':2},{'attempts':-1}])
def test_handoff_rejects_corrupt_checkpoint_values(change):
    design,rows=sample();rows[0].update(change)
    with pytest.raises(ValueError):checkpoint_rows(encode(rows),design)


@pytest.mark.skipif(not Path('/proc/self/stat').exists(),reason='Linux process lifecycle regression')
def test_exited_worker_is_observed_without_resolving_its_removed_cwd():
    process=subprocess.Popen([sys.executable,'-c','pass'])
    try:
        deadline=time.monotonic()+5
        while True:
            fields=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()
            if fields[0]=='Z':break
            assert time.monotonic()<deadline
            time.sleep(.01)
        start=int(fields[19])
        assert observe_worker(process.pid,start)=='Z'
    finally:process.wait(timeout=5)
    assert observe_worker(process.pid,start) is None
