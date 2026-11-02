"""Validate a completed or resumable dropout-study response CSV against its design."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import datetime as dt
import json
import pathlib
import re


def audit(output):
    output=pathlib.Path(output).resolve()
    design_path=output/'dropout_design.json'
    response_path=output/'dropout_responses.csv'
    if not design_path.is_file() or not response_path.is_file():
        raise FileNotFoundError('dropout_design.json and dropout_responses.csv are required')
    design_doc=json.loads(design_path.read_text())
    design=design_doc.get('design',{})
    dates=list(design.get('dates',[]));regimes=list(design.get('regimes',[]))
    modes=list(design.get('modes',[]));rates=[float(x) for x in design.get('rates',[])]
    replicates=int(design.get('replicates',0))
    model_seeds=list(map(int,design.get('model_seeds',[])))
    if not model_seeds:
        config=design.get('config',{})
        model_seeds=list(map(int,config.get('dropout_model_seeds',[])))
        if not model_seeds:
            match=re.search(r'(\d+)\.pt$',str(design.get('checkpoint','')))
            model_seeds=[int(match.group(1))] if match else [int(config.get('dropout_model_seed',101))]
    factors={(date,regime,mode,replicate,seed,rate)
        for date in dates for regime in regimes for mode in modes
        for replicate in range(replicates) for seed in model_seeds for rate in rates}
    if not factors:
        raise ValueError('dropout design has an empty or invalid treatment grid')

    before=response_path.stat()
    seen=set();cell_counts={};duplicates=0;unexpected=0;malformed=0;rows_read=0
    with response_path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            rows_read+=1
            try:
                key=(row['date'],row['regime'],row['mode'],int(row['replicate']),
                     int(row.get('model_seed') or model_seeds[0]),
                     float(row['dropout_probability']))
            except (KeyError,TypeError,ValueError):
                malformed+=1;continue
            if key not in factors:
                unexpected+=1;continue
            if key in seen:
                duplicates+=1;continue
            seen.add(key)
            cell=key[:2]
            cell_counts[cell]=cell_counts.get(cell,0)+1
    after=response_path.stat()
    changed_while_reading=(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns)
    expected_per_cell=replicates*len(modes)*len(rates)*len(model_seeds)
    expected_cells=len(dates)*len(regimes)
    completed_cells=sum(cell_counts.get((date,regime),0)==expected_per_cell
                        for date in dates for regime in regimes)
    summary_path=output/'dropout_summary.json'
    summary=json.loads(summary_path.read_text()) if summary_path.is_file() else None
    issues=[]
    if duplicates:issues.append('duplicate treatment rows')
    if unexpected:issues.append('rows outside the declared design')
    if malformed:issues.append('malformed response rows')
    if len(seen)!=len(factors):issues.append('missing design treatments')
    if summary and summary.get('design_signature')!=design_doc.get('design_signature'):
        issues.append('summary and design signatures differ')
    if summary and summary.get('status')!='completed':
        issues.append('summary is not marked completed')

    if changed_while_reading and summary is None:
        status='snapshot_in_progress'
    elif summary is not None:
        status='completed_valid' if not issues and rows_read==len(factors) else 'completed_invalid'
    elif not issues and rows_read==len(factors):
        status='all_rows_present_summary_pending'
    elif not duplicates and not unexpected and not malformed:
        status='partial_checkpoint'
    else:
        status='inconsistent_partial_checkpoint'
    report={
        'status':status,
        'audited_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'design_signature':design_doc.get('design_signature'),
        'date_count':len(dates),'regime_count':len(regimes),
        'outage_mode_count':len(modes),'rate_count':len(rates),
        'replicate_count':replicates,'model_seed_count':len(model_seeds),
        'expected_cells':expected_cells,'completed_cells':completed_cells,
        'expected_treatment_rows':len(factors),'rows_read':rows_read,
        'unique_valid_rows':len(seen),'missing_rows':len(factors)-len(seen),
        'duplicate_rows':duplicates,'unexpected_rows':unexpected,
        'malformed_rows':malformed,'changed_while_reading':changed_while_reading,
        'summary_present':summary is not None,'issues':issues,
    }
    report_path=output/'dropout_integrity_audit.json'
    tmp=report_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report,indent=2)+'\n');tmp.replace(report_path)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    report=audit(args.output)
    print(json.dumps(report,indent=2))
    if report['status']=='completed_invalid':
        raise SystemExit(1)


if __name__=='__main__':
    main()
