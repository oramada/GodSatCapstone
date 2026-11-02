"""Finish missing canonical quarterly cells with a checkpointed, reversible handoff."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import signal
import time

import torch

from godsat.dropout import run_dropout_study
from godsat.orbits import ROOT
from scripts.validation.audit_dropout_results import audit
from scripts.experiments.quarterly_cell_worker import checked_rows,compute_cell,validate_bound_sources
from scripts.experiments.run_dropout_campaign import sha256


def observe_worker(pid,start_ticks):
    proc=Path(f'/proc/{pid}')
    for attempt in range(3):
        try:
            fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
            if fields[19]!=str(start_ticks):return None
            if fields[0]=='Z':return 'Z'
            if (proc/'cwd').resolve()!=ROOT:raise ValueError('Worker working directory differs')
            command=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode()
            if 'scripts/experiments/run_dropout_campaign.py' not in command:
                raise ValueError('PID does not identify the original campaign runner')
            return fields[0]
        except FileNotFoundError:
            try:current=(proc/'stat').read_text().rsplit(')',1)[1].split()
            except FileNotFoundError:return None
            if current[19]!=str(start_ticks):return None
            if current[0]=='Z':return 'Z'
            if attempt==2:raise RuntimeError('Process metadata observation failed while exact worker remains live')


def checkpoint_rows(payload,design):
    rows,counts=checked_rows(payload,design)
    if not rows:raise ValueError('Empty checkpoint is not a completed-cell snapshot')
    steps=design['config']['duration_minutes']*60/design['config']['step_seconds']
    maximum=steps*design['config']['agents']
    for row in rows:
        attempts,trials,misses=(row[name] for name in ('attempts','dropout_trials','dropout_misses'))
        if (not all(math.isfinite(value) and value==int(value) for value in (attempts,trials,misses))
                or row['steps']!=steps or not 0<=misses<=trials<=attempts<=maximum
                or not math.isclose(row['dropout_rate_observed'],misses/max(trials,1),rel_tol=0,abs_tol=1e-12)
                or row['dropout_probability']==0 and misses!=0):
            raise ValueError('Impossible checkpoint observation counts')
    return rows,counts


def run(output,campaign,pid,start_ticks,work,workers=6):
    output,campaign,work=map(lambda p:Path(p).resolve(),(output,campaign,work))
    document=json.loads((output/'dropout_design.json').read_text());design=document['design']
    if hashlib.sha256(json.dumps(design,sort_keys=True).encode()).hexdigest()!=document['design_signature']:
        raise ValueError('Original design signature does not reconcile')
    if not 1<=workers<=8:raise ValueError('Worker count outside supported range')
    validate_bound_sources(design,campaign)
    pilot_path=work/'pilot.json';pilot=json.loads(pilot_path.read_text())
    if (pilot['status']!='passed_exact_complete_cell_pilot' or not pilot['all_fields_exact']
            or pilot['design_signature']!=document['design_signature']
            or pilot['worker_code_sha256']!=sha256(ROOT/'scripts/experiments/quarterly_cell_worker.py')
            or pilot['responses']!=1200):raise ValueError('Exact full-cell pilot required')
    receipt={'status':'preflight_complete','worker_pid':pid,'worker_start_ticks':start_ticks,
        'design_signature':document['design_signature'],'pilot_sha256':sha256(pilot_path),
        'controller_sha256':sha256(Path(__file__)),'workers':workers,'completed_cells':[],
        'scope':'Original frozen source, scenarios, models, seed grid and kernel. Only execution scheduling changes. Original worker remains stopped and resumable until the complete merged grid has finalized and passed integrity validation.'}
    work.mkdir(parents=True,exist_ok=True);receipt_path=work/'handoff.json'
    def save(stage,**extra):
        receipt.update(status=stage,**extra);tmp=receipt_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(receipt,indent=2)+'\n');tmp.replace(receipt_path)
        print(json.dumps({'stage':stage,**extra}),flush=True)
    def state():
        return observe_worker(pid,start_ticks)
    def restore_file(name,payload):
        path=output/name
        if payload is None:path.unlink(missing_ok=True)
        else:
            temp=path.with_name(path.name+'.handoff-restore.tmp');temp.write_bytes(payload);temp.replace(path)
    backups={};stopped=False;committed=False
    try:
        if (output/'dropout_summary.json').exists():
            result=json.loads((output/'dropout_summary.json').read_text())
            existing,_=checkpoint_rows((output/'dropout_responses.csv').read_bytes(),design)
            if result['status']=='completed' and result['design_signature']==document['design_signature'] and len(existing)==81600:
                save('original_finished_before_handoff');return receipt
            raise ValueError('Unexpected pre-existing incomplete summary')
        for attempt in range(10):
            current=state()
            if current is None or current=='Z':raise ValueError('Original worker ended before checkpoint handoff')
            if current in ('T','t'):raise ValueError('Original worker was already externally stopped')
            os.kill(pid,signal.SIGSTOP);stopped=True
            for _ in range(100):
                if state() in ('T','t'):break
                time.sleep(.02)
            else:raise ValueError('Worker did not enter the stopped state')
            try:
                for descriptor in Path(f'/proc/{pid}/fd').iterdir():
                    try:target=os.readlink(descriptor)
                    except FileNotFoundError:continue
                    if target.removesuffix(' (deleted)')==str(output/'dropout_responses.csv'):
                        raise ValueError('Original checkpoint writer is still open; resume and retry')
                payload=(output/'dropout_responses.csv').read_bytes();rows,counts=checkpoint_rows(payload,design)
                break
            except (ValueError,TypeError,KeyError):
                os.kill(pid,signal.SIGCONT);stopped=False;time.sleep(.5)
        else:raise ValueError('Could not capture a complete-cell checkpoint')
        expected={(date,regime) for date in design['dates'] for regime in design['regimes']}
        missing=sorted(expected-set(counts))
        if not missing:
            os.kill(pid,signal.SIGCONT);stopped=False;save('all_rows_already_present_original_resumed');return receipt
        backup_dir=work/'checkpoint';backup_dir.mkdir(parents=True,exist_ok=True)
        for name in ('dropout_responses.csv','dropout_design.json','dropout_summary.json',
                     'checkpoint_provenance.json','dropout_report.md','dropout_integrity_audit.json'):
            path=output/name;backups[name]=path.read_bytes() if path.exists() else None
            if backups[name] is not None:(backup_dir/name).write_bytes(backups[name])
        receipt['backup_sha256']={name:None if value is None else hashlib.sha256(value).hexdigest() for name,value in backups.items()}
        save('original_checkpoint_stopped_and_backed_up',source_rows=len(rows),source_cells=len(counts),missing_cells=missing)
        with ProcessPoolExecutor(max_workers=min(workers,len(missing)),mp_context=multiprocessing.get_context('spawn')) as pool:
            futures={pool.submit(compute_cell,design,campaign,date,regime):(date,regime) for date,regime in missing}
            for future in as_completed(futures):
                cell=futures[future];computed=future.result()
                if len(computed)!=1200:raise ValueError('Supplementary cell count differs')
                path=work/'cells'/f'{cell[0][:10]}-{cell[1]}.json';path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(computed,indent=2)+'\n')
                rows.extend(computed);receipt['completed_cells'].append({'date':cell[0],'regime':cell[1],
                    'rows':len(computed),'path':str(path.relative_to(ROOT)),'sha256':sha256(path)})
                save('computing_original_missing_cells',completed_cell_count=len(receipt['completed_cells']))
        validate_bound_sources(design,campaign)
        modes={name:index for index,name in enumerate(design['modes'])}
        rates={float(value):index for index,value in enumerate(design['rates'])}
        seeds={int(value):index for index,value in enumerate(design['model_seeds'])}
        rows.sort(key=lambda r:(r['date'],r['regime'],modes[r['mode']],int(r['replicate']),
                                rates[float(r['dropout_probability'])],seeds[int(r['model_seed'])]))
        fieldnames=next(csv.reader(io.StringIO(payload.decode())))
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=fieldnames);writer.writeheader();writer.writerows(rows)
        merged=stream.getvalue().encode();validated,full_counts=checkpoint_rows(merged,design)
        if len(validated)!=81600 or set(full_counts)!=expected:raise ValueError('Merged grid is not the complete original design')
        temporary=output/'dropout_responses.csv.handoff.tmp';temporary.write_bytes(merged);temporary.replace(output/'dropout_responses.csv')
        save('finalizing_complete_original_design',merged_rows=len(validated),merged_cells=len(full_counts))
        torch.set_num_threads(1)
        final=run_dropout_study(design['config'],campaign,output,rates=design['rates'],replicates=design['replicates'])
        integrity=audit(output)
        if final['design_signature']!=document['design_signature'] or integrity['status']!='completed_valid':
            raise ValueError('Finalized original design did not pass full integrity validation')
        committed=True
        save('complete_original_grid_committed_before_worker_replacement',
            final_response_sha256=sha256(output/'dropout_responses.csv'),
            final_summary_sha256=sha256(output/'dropout_summary.json'))
        if state() not in (None,'Z'):
            os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
            for _ in range(100):
                if state() in (None,'Z'):break
                time.sleep(.05)
            else:raise ValueError('Original stopped worker did not terminate after replacement')
        stopped=False
        save('completed_original_grid_parallel_handoff_final_audits_pending',
             original_worker_replaced_after_complete_grid=True)
        return receipt
    except BaseException as error:
        if not committed:
            for name,value in backups.items():restore_file(name,value)
            if stopped and state() not in (None,'Z'):os.kill(pid,signal.SIGCONT)
            save('failed_original_checkpoint_restored_worker_resumed',error=f'{type(error).__name__}: {error}')
        else:
            save('failed_after_commit_full_results_preserved',error=f'{type(error).__name__}: {error}')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--worker-pid',type=int,required=True);parser.add_argument('--worker-start',type=int,required=True)
    parser.add_argument('--work',type=Path,default=ROOT/'outputs/study-execution/quarterly-handoff')
    parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args();run(args.output,args.campaign,args.worker_pid,args.worker_start,args.work,args.workers)
