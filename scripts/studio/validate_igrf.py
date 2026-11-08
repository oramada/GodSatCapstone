"""Compare IGRF adapter with the separate official Fortran implementation.

Supply NOAA's https://www.ngdc.noaa.gov/IAGA/vmod/igrf14.f as --source.
Requires gfortran. Writes a compact reference fixture; no network in unit tests.
"""
import argparse
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
from godsat.simulation.providers import igrf_bundle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('outputs/igrf-validation'))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    raw=args.source.read_bytes(); text=raw.decode('ascii')
    start=text.lower().index('      subroutine igrf14syn')
    subroutine=args.output/'igrf14syn.f'; subroutine.write_text(text[start:])
    driver=args.output/'driver.f90'
    driver.write_text('''program reference
implicit none
real(8) :: year, lat, lon, alt, x, y, z, total
integer :: status
do
 read(*,*,iostat=status) year, lat, lon, alt
 if (status /= 0) exit
 call igrf14syn(0,year,1,alt,90d0-lat,lon,x,y,z,total)
 write(*,'(4ES25.16)') x,y,z,total
end do
end program
''')
    runner=args.output/'igrf-reference'
    subprocess.run(['gfortran','-std=legacy',str(driver),str(subroutine),'-o',str(runner)],check=True)
    points=[dict(latitude_deg=lat,longitude_deg=lon,altitude_km=alt) for lat,lon,alt in itertools.product([-80.,-45.,0.,45.,80.],[-120.,0.,120.],[0.,400.,2000.])]
    rows=[]
    for year in [1900,1950,2000,2025]:
        commands=''.join(f'{year} {p["latitude_deg"]} {p["longitude_deg"]} {p["altitude_km"]}\n' for p in points)
        result=subprocess.run([str(runner.resolve())],input=commands,text=True,capture_output=True,check=True)
        reference=[list(map(float,line.split())) for line in result.stdout.splitlines()]
        if len(reference)!=len(points): raise RuntimeError('Unexpected Fortran output')
        bundle=igrf_bundle(points,f'{year}-01-01T00:00:00Z')
        for point,ref,actual in zip(points,reference,bundle['samples']):
            enu=[ref[1],ref[0],-ref[2]]
            actual=actual['values']; error=max(abs(actual[k]-v) for k,v in zip(['magnetic_east_nt','magnetic_north_nt','magnetic_up_nt'],enu))
            rows.append({'year':year,**point,'reference_enu_nt':enu,'max_component_error_nt':error})
    report={'source':'https://www.ngdc.noaa.gov/IAGA/vmod/igrf14.f',
        'source_sha256':hashlib.sha256(raw).hexdigest(),'compiler':subprocess.check_output(['gfortran','--version'],text=True).splitlines()[0],
        'cases':len(rows),'maximum_component_error_nt':max(r['max_component_error_nt'] for r in rows),
        'scope':'Implementation agreement for main-field synthesis only; not comparison with measured magnetic field',
        'reference':rows}
    (args.output/'reference.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='reference'},indent=2))
    if report['maximum_component_error_nt']>.1: raise RuntimeError('IGRF implementation agreement exceeds 0.1 nT')


if __name__=='__main__':main()
