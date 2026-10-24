"""Export a selected satellite's reconstructed historical SGP4 trajectory."""
import argparse
import json

from godsat.trajectory import export_trajectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--norad', type=int, required=True)
    parser.add_argument('--start', required=True, help='UTC ISO timestamp, e.g. 2026-10-01T00:00:00Z')
    parser.add_argument('--end', required=True, help='UTC ISO timestamp, exclusive')
    parser.add_argument('--step-seconds', type=int, default=60)
    parser.add_argument('--max-age-hours', type=float, default=72)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = export_trajectory(args.norad, args.start, args.end, args.output,
                               args.step_seconds, args.max_age_hours)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
