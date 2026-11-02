
# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from godsat.sentinel_attitude import PLATFORM_NORAD,download_attitude


def main():
    parser=argparse.ArgumentParser(description='Fetch official Sentinel AUX_PROQUA quaternion products from Copernicus.')
    parser.add_argument('--start',default='2022-10-09T00:00:00Z')
    parser.add_argument('--end',default='2026-10-10T00:00:00Z',help='exclusive UTC end')
    parser.add_argument('--platforms',nargs='+',choices=sorted(PLATFORM_NORAD),default=['S1A'])
    parser.add_argument('--sample-seconds',type=int,default=60,
        help='keep one sample every N seconds while preserving the original TGZ products')
    parser.add_argument('--output',default='data/attitude/sentinel_quaternions')
    args=parser.parse_args()
    result=download_attitude(args.start,args.end,args.platforms,args.output,args.sample_seconds)
    print(f"{result['product_count']} products; {result['records_parsed']:,} parsed samples; {args.output}")


if __name__=='__main__':main()
