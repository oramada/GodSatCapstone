"""Fetch or normalize environmental inputs before offline playback."""
import argparse
import json
from pathlib import Path
from .providers import fetch_weather, fetch_glotec, igrf_bundle, ionex_bundle, write_bundle, download


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='provider',required=True)
    weather=sub.add_parser('weather')
    weather.add_argument('--latitude',type=float,required=True)
    weather.add_argument('--longitude',type=float,required=True)
    weather.add_argument('--time',help='Select the preceding hourly model sample for this UTC time, instead of current conditions')
    magnetic=sub.add_parser('igrf')
    magnetic.add_argument('--points',type=Path,required=True,help='JSON array of latitude_deg, longitude_deg, altitude_km')
    magnetic.add_argument('--time',required=True)
    ionex=sub.add_parser('ionex')
    ionex.add_argument('--input',type=Path,required=True,help='Uncompressed IONEX 1.x 2D TEC file')
    glotec=sub.add_parser('glotec')
    catalog=sub.add_parser('catalog')
    space_weather=sub.add_parser('space-weather')
    catalog.add_argument('--group',choices=['active','iridium-NEXT','stations'],default='active')
    for name,command in [('weather',weather),('igrf',magnetic),('ionex',ionex),('glotec',glotec),('catalog',catalog),('space-weather',space_weather)]:
        command.add_argument('--output',type=Path,required=True)
        if name not in {'catalog','space-weather'}: command.add_argument('--hold-seconds',type=float,default=0,help='Explicit sample hold; default exact epoch only')
    args=parser.parse_args()
    if args.provider=='weather': fetch_weather(args.latitude,args.longitude,args.output,args.hold_seconds,args.time)
    elif args.provider=='igrf': write_bundle(igrf_bundle(json.loads(args.points.read_text()),args.time,args.hold_seconds),args.output)
    elif args.provider=='ionex': write_bundle(ionex_bundle(args.input,args.hold_seconds),args.output)
    elif args.provider=='glotec': fetch_glotec(args.output,args.hold_seconds)
    elif args.provider=='space-weather':
        _,source=download('https://celestrak.org/SpaceData/SW-Last5Years.csv',args.output)
        args.output.with_suffix('.source.json').write_text(json.dumps(source,indent=2)+'\n')
    else:
        url=f'https://celestrak.org/NORAD/elements/gp.php?GROUP={args.group}&FORMAT=json'
        _,source=download(url,args.output)
        from .catalog import load_catalog
        records,_=load_catalog(args.output)
        source['objects']=len(records)
        args.output.with_suffix('.source.json').write_text(json.dumps(source,indent=2)+'\n')
    print(args.output)


if __name__=='__main__': main()
