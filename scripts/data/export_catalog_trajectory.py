"""Export resumable fixed-cadence SGP4 tracks for every overlapping catalog ID."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import json
import math
import pathlib

from godsat.catalog_trajectory import (catalog_object_ids, duration_samples,
    export_catalog_trajectory)
from godsat.orbits import ROOT, utc
from godsat.trajectory import source_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True, help='UTC ISO timestamp, inclusive')
    parser.add_argument('--end', required=True, help='UTC ISO timestamp, exclusive')
    parser.add_argument('--step-seconds', type=int, default=3600,
        help='Cadence must divide one day; default: 3600')
    parser.add_argument('--max-age-hours', type=float, default=72)
    parser.add_argument('--output', default=str(ROOT/'data/catalog_ephemeris_all'))
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--plan', action='store_true', help='Print cohort and row counts without writing')
    args = parser.parse_args()
    root=pathlib.Path(args.root).resolve()
    start,end=utc(args.start),utc(args.end)
    if start>=end:
        parser.error('--start must be before --end')
    if args.step_seconds<=0 or 86_400%args.step_seconds:
        parser.error('--step-seconds must be a positive divisor of 86400')
    if args.max_age_hours<0:
        parser.error('--max-age-hours must be nonnegative')
    ids=catalog_object_ids(root,start,end,args.max_age_hours)
    samples=duration_samples(start,end,args.step_seconds)
    if args.plan:
        print(json.dumps({'status':'planned','start_inclusive':start.isoformat(),
            'end_exclusive':end.isoformat(),'step_seconds':args.step_seconds,
            'object_count':len(ids),'samples_per_object':samples,
            'projected_rows':len(ids)*samples,
            'daily_parts':math.ceil((end-start).total_seconds()/86400),
            'source_revision':source_revision(root)},indent=2))
        return
    def progress(manifest):
        print(json.dumps({'status':'running','parts_written':manifest['parts_written'],
            'records_written':manifest['records_written'],
            'projected_rows':manifest['projected_rows']}),flush=True)
    result=export_catalog_trajectory(args.start,args.end,args.output,
        args.step_seconds,args.max_age_hours,root,progress)
    print(json.dumps({key:result[key] for key in ('status','object_count',
        'projected_rows','completed_rows','successful','sgp4_errors',
        'stale_or_missing','parts_written')},indent=2))


if __name__=='__main__':
    main()
