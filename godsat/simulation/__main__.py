"""Export a bounded simulation window for the existing Studio artifact browser."""
import argparse
import hashlib
import json
from pathlib import Path
from .catalog import load_catalog, make_times, build_scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--format', choices=['omm', 'tle'], default='omm')
    parser.add_argument('--start', required=True, help='ISO timestamp with UTC offset')
    parser.add_argument('--duration', type=float, default=600, help='Window seconds')
    parser.add_argument('--step', type=float, default=10, help='Sample cadence seconds')
    parser.add_argument('--max-age-hours', type=float, default=72)
    parser.add_argument('--frame', choices=['ITRS', 'TEME'], default='ITRS')
    parser.add_argument('--environment', type=Path, action='append', default=[])
    parser.add_argument('--ground-links', type=Path, help='Ground-station and radio-path configuration')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--window-seconds', type=float, help='Export an overlapping-window sequence instead of a single scene')
    args = parser.parse_args()
    records, source = load_catalog(args.catalog, args.format)
    ground_links=None
    if args.ground_links:
        from .links import validate_config
        if args.ground_links.stat().st_size>1024*1024:parser.error('Ground-link configuration exceeds 1 MiB')
        ground_links=validate_config(json.loads(args.ground_links.read_text()))
        ground_links['input_sha256']=hashlib.sha256(args.ground_links.read_bytes()).hexdigest()
    bundle = None
    if args.environment:
        from .environment import validate_environment
        bundle = {'schema': 'godsat.environment.v1', 'sources': [], 'samples': []}
        for path in args.environment:
            if path.stat().st_size > 32*1024*1024:
                parser.error('Environmental input exceeds 32 MiB')
            value = validate_environment(json.loads(path.read_text()))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            bundle['sources'].extend([{**s, 'input_sha256': digest} for s in value['sources']])
            bundle['samples'].extend(value['samples'])
        validate_environment(bundle)
    if args.window_seconds is not None:
        from .sequence import export_sequence
        manifest=export_sequence(records,source,args.start,args.duration,args.step,args.window_seconds,args.output,args.max_age_hours,args.frame,bundle,ground_links)
        print(f'{args.output}: {len(records):,} satellites, {len(manifest["windows"])} windows')
        return
    scene = build_scene(records, make_times(args.start, args.duration, args.step), source,
                        args.max_age_hours, args.frame, bundle, ground_links)
    raw = json.dumps(scene, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > 64*1024*1024:
        parser.error('Scene exceeds 64 MiB; shorten the simulation window')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    print(f'{args.output}: {len(records):,} satellites, {len(scene["times"])} frames, {len(raw):,} bytes')


if __name__ == '__main__':
    main()
