"""Download public ILRS CRD normal-point records for a selected target."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import pathlib
import re
import time
import urllib.error
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[2]
BASE='https://edc.dgfi.tum.de/pub/slr/data/npt_crd_v2/lageos1'
START=dt.date(2022,10,9)
END=dt.date(2026,10,9)
OUT=ROOT/'data/ground_sensor/ilrs_lageos1_npt'

def get(url,timeout=30):
    req=urllib.request.Request(url,headers={'User-Agent':'GoDSAT-research/1.0 (ILRS public archive research)'} )
    with urllib.request.urlopen(req,timeout=timeout) as response:return response.read()

def list_daily(year, target='lageos1'):
    url=f'https://edc.dgfi.tum.de/pub/slr/data/npt_crd_v2/{target}/{year}/'
    html=get(url).decode('utf-8','replace')
    dates=[]
    for path in re.findall(r'href=["\']([^"\']+)',html):
        name=path.rsplit('/',1)[-1]
        match=re.fullmatch(re.escape(target)+r'_(\d{8})\.np2',name)
        if not match:continue
        day=dt.datetime.strptime(match.group(1),'%Y%m%d').date()
        if START<=day<=END:dates.append((day,path))
    return url,sorted(dates)

def download(item):
    year,day,path=item;folder=OUT/str(year);folder.mkdir(parents=True,exist_ok=True)
    target=folder/path.rsplit('/',1)[-1]
    was_present=target.is_file() and target.stat().st_size>0
    if was_present:
        body=target.read_bytes()
    else:
        url='https://edc.dgfi.tum.de'+path
        last=None
        for attempt in range(4):
            try:
                body=get(url)
                # The public archive uses both upper- and lower-case CRD headers.
                if not body[:16].lstrip().lower().startswith(b'h1 crd'):raise ValueError(f'Unexpected CRD header in {url}')
                tmp=target.with_suffix(target.suffix+'.tmp');tmp.write_bytes(body);tmp.replace(target);last=None;break
            except (OSError,urllib.error.URLError,ValueError) as error:
                last=error;time.sleep(0.5*(attempt+1))
        if last is not None:return {'date':day.isoformat(),'path':str(target.relative_to(ROOT)),'status':'error','error':str(last)}
    return {'date':day.isoformat(),'path':str(target.relative_to(ROOT)),'bytes':len(body),
            'sha256':hashlib.sha256(body).hexdigest(),'status':'present' if was_present else 'downloaded'}

def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',default='lageos1',help='lowercase ILRS archive target slug, e.g. lageos2, lares, starlette')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z0-9]+',args.target):
        raise SystemExit('Target slug must contain lowercase letters and digits only')
    OUT=ROOT/f'data/ground_sensor/ilrs_{args.target}_npt'
    OUT.mkdir(parents=True,exist_ok=True)
    listing={};items=[]
    for year in range(START.year,END.year+1):
        url,days=list_daily(year,args.target);listing[str(year)]={'url':url,'daily_files_found':len(days)}
        items.extend((year,day,path) for day,path in days)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(download,item) for item in items]
        for i,future in enumerate(concurrent.futures.as_completed(futures),1):
            result=future.result();results.append(result)
            if i%100==0:print(f'{i}/{len(items)} ILRS daily files checked',flush=True)
    results.sort(key=lambda x:x['date'])
    manifest={'status':'completed' if all(r['status']!='error' for r in results) else 'partial',
        'source':'International Laser Ranging Service (ILRS), EUROLAS Data Center (EDC)',
        'base_url':f'https://edc.dgfi.tum.de/pub/slr/data/npt_crd_v2/{args.target}',
        'record_format':'CRD version 2 normal-point files (.np2)',
        'target_archive_slug':args.target,'requested_start':START.isoformat(),'requested_end_inclusive':END.isoformat(),
        'year_directories':listing,'expected_calendar_days':(END-START).days+1,
        'files_found':len(results),'files_missing_from_listing':(END-START).days+1-len(results),
        'files_with_errors':sum(r['status']=='error' for r in results),
        'total_bytes':sum(r.get('bytes',0) for r in results),'attribution':'Acknowledge ILRS and the EUROLAS Data Center in publications using this data.',
        'limitations':['This is satellite laser ranging for one selected target; it is not a representative sensor sample for all satellites or sensor modalities.',
            'Normal-point files contain station-specific ranging sessions and do not expose missed acquisition opportunities, so their cadence alone is not a dropout probability.',
            'Retain CRD correction flags and supplementary records when estimating calibrated range residuals.'],
        'files':results}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:manifest[k] for k in ['status','expected_calendar_days','files_found','files_missing_from_listing','files_with_errors','total_bytes']},indent=2))

if __name__=='__main__':main()
