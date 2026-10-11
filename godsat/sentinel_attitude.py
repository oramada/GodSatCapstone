"""Download and parse public Copernicus Sentinel AUX_PROQUA attitude products."""
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import pathlib
import re
import tarfile
import time
import urllib.parse
import urllib.request

from astropy.time import Time

CATALOGUE='https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
DOWNLOAD='https://download.dataspace.copernicus.eu/odata/v1/Products'
TOKEN_URL='https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
GPS_EPOCH=dt.datetime(1980,1,6)
PLATFORM_NORAD={
    'S1A':39634,'S1B':41456,'S1C':62261,'S1D':66315,
    'S2A':40697,'S2B':42063,'S2C':60989,
    'S3A':41335,'S3B':43437,'S3C':100690,
}
COLLECTIONS={'S1':'SENTINEL-1','S2':'SENTINEL-2','S3':'SENTINEL-3'}
FIELDS=['norad_id','platform','epoch_utc','epoch_gps','q0','q1','q2','q3',
        'quaternion_norm','attitude_mode','source_flag','product_name']


def gps_to_utc(date_text,time_text):
    """Convert the product's GPS civil timestamp to a timezone-aware UTC string."""
    nominal=dt.datetime.strptime(date_text+' '+time_text,'%Y/%m/%d %H:%M:%S.%f')
    gps_seconds=(nominal-GPS_EPOCH).total_seconds()
    utc=Time(gps_seconds,format='gps').utc.to_datetime(timezone=dt.timezone.utc)
    return utc.isoformat().replace('+00:00','Z'),gps_seconds


def parse_product(payload,product_name,sample_seconds=1):
    """Parse a TGZ AUX_PROQUA product, optionally retaining every Nth UTC second."""
    if sample_seconds<1:raise ValueError('sample_seconds must be a positive integer')
    match=re.match(r'^(S[123][A-Z])_OPER_AUX_PROQUA_',product_name)
    if not match:raise ValueError(f'Not a supported Sentinel AUX_PROQUA product: {product_name}')
    platform=match.group(1)
    if platform not in PLATFORM_NORAD:raise ValueError(f'No verified NORAD mapping for {platform}')
    with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
        data_files=[m for m in archive.getmembers() if m.isfile() and m.name.upper().endswith('.DBL')]
        if len(data_files)!=1:raise ValueError(f'Expected one .DBL member, found {len(data_files)}')
        member=archive.extractfile(data_files[0])
        if member is None:raise ValueError('Could not read quaternion data block')
        lines=member.read().decode('ascii').splitlines()
    rows=[];sample_ms=sample_seconds*1000
    for line_number,line in enumerate(lines,1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        fields=line.split()
        if len(fields)!=8:raise ValueError(f'Unexpected quaternion row at data-block line {line_number}: {line!r}')
        date_text,time_text=fields[:2]
        q=[float(x) for x in fields[2:6]]
        mode=int(fields[6]);source=fields[7].lower()
        if source not in {'r','i','s'}:raise ValueError(f'Unknown quaternion source flag {source!r}')
        epoch_utc,gps_seconds=gps_to_utc(date_text,time_text)
        epoch_datetime=dt.datetime.fromisoformat(epoch_utc.replace('Z','+00:00'))
        if int(round(epoch_datetime.timestamp()*1000))%sample_ms:continue
        norm=math.sqrt(sum(x*x for x in q))
        rows.append({'norad_id':PLATFORM_NORAD[platform],'platform':platform,
            'epoch_utc':epoch_utc,'epoch_gps':gps_seconds,'q0':q[0],'q1':q[1],
            'q2':q[2],'q3':q[3],'quaternion_norm':norm,'attitude_mode':mode,
            'source_flag':source,'product_name':product_name})
    return rows


def list_products(start,end,platforms,timeout=60):
    start=dt.datetime.fromisoformat(start.replace('Z','+00:00')).astimezone(dt.timezone.utc)
    end=dt.datetime.fromisoformat(end.replace('Z','+00:00')).astimezone(dt.timezone.utc)
    if start>=end:raise ValueError('start must precede end')
    # AUX_PROQUA names and OData validity are day-aligned to GPS time. Expand
    # discovery by one day at either edge, then trim parsed samples to the exact
    # UTC request after applying GPS-UTC offsets.
    query_start=start-dt.timedelta(days=1);query_end=end+dt.timedelta(days=1)
    start_text=query_start.isoformat(timespec='seconds').replace('+00:00','Z')
    end_text=query_end.isoformat(timespec='seconds').replace('+00:00','Z')
    collections=sorted({COLLECTIONS[p[:2]] for p in platforms})
    coll_filter=' or '.join(f"Collection/Name eq '{name}'" for name in collections)
    filt=(f"Online eq true and ({coll_filter}) and "
        "Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType' and a/Value eq 'AUX_PROQUA') and "
        f"ContentDate/Start lt {end_text} and ContentDate/End ge {start_text}")
    params={'$filter':filt,'$top':'1000','$orderby':'ContentDate/Start'}
    url=CATALOGUE+'?'+urllib.parse.urlencode(params);products=[]
    while url:
        request=urllib.request.Request(url,headers={'Accept':'application/json'})
        with urllib.request.urlopen(request,timeout=timeout) as response:page=json.load(response)
        for item in page.get('value',[]):
            m=re.match(r'^(S[123][A-Z])_OPER_AUX_PROQUA_',item.get('Name',''))
            if m and m.group(1) in platforms:products.append(item)
        url=page.get('@odata.nextLink')
    # Product generation time appears in the filename before _V. Keep the
    # newest version for each platform and validity interval.
    selected={}
    for item in products:
        period=item.get('ContentDate',{})
        key=(item['Name'][:3],period.get('Start'),period.get('End'))
        if key not in selected or item['Name']>selected[key]['Name']:
            selected[key]=item
    return sorted(selected.values(),key=lambda p:(p['Name'][:3],p['ContentDate']['Start']))


def access_token(username=None,password=None,timeout=30):
    username=username or os.environ.get('CDSE_USERNAME')
    password=password or os.environ.get('CDSE_PASSWORD')
    if not username or not password:
        raise RuntimeError('Set CDSE_USERNAME and CDSE_PASSWORD in the environment to download Sentinel attitude products.')
    body=urllib.parse.urlencode({'client_id':'cdse-public','grant_type':'password',
        'username':username,'password':password}).encode()
    request=urllib.request.Request(TOKEN_URL,data=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request,timeout=timeout) as response:token=json.load(response)
    return token['access_token']


def _write_manifest(path,manifest):
    temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(manifest,indent=2)+'\n');temp.replace(path)


def download_attitude(start,end,platforms,output,sample_seconds=60,timeout=120):
    platforms=sorted(set(platforms))
    unknown=set(platforms)-PLATFORM_NORAD.keys()
    if unknown:raise ValueError(f'Unsupported Sentinel platforms: {sorted(unknown)}')
    token=access_token();token_refresh_at=time.monotonic()+480;products=list_products(start,end,platforms)
    requested_start=dt.datetime.fromisoformat(start.replace('Z','+00:00')).astimezone(dt.timezone.utc)
    requested_end=dt.datetime.fromisoformat(end.replace('Z','+00:00')).astimezone(dt.timezone.utc)
    output=pathlib.Path(output).expanduser().resolve();raw_dir=output/'raw';parsed_dir=output/'parsed'
    raw_dir.mkdir(parents=True,exist_ok=True);parsed_dir.mkdir(parents=True,exist_ok=True)
    manifest_path=output/'manifest.json'
    signature=json.dumps({'start':start,'end':end,'platforms':platforms,'sample_seconds':sample_seconds},sort_keys=True)
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest.get('request_signature')!=signature:raise ValueError('Output folder belongs to another request')
    else:
        manifest={'status':'running','source':'Copernicus Data Space Ecosystem AUX_PROQUA',
            'request_signature':signature,'start_utc':start,'end_exclusive_utc':end,
            'platforms':platforms,'sample_seconds':sample_seconds,'products':{},
            'limitations':['Covers Sentinel missions only, not the full satellite catalog.',
                'Product SOURCE flags distinguish real, interpolated, and simulated attitude samples.',
                'GPS timestamps are converted to UTC using Astropy leap-second data.']}
    completed=manifest['products']
    for index,product in enumerate(products,1):
        name=product['Name'];product_id=product['Id'];safe=name.replace('/','_')
        raw_path=raw_dir/(safe+'.TGZ');parsed_path=parsed_dir/(safe+f'_every{sample_seconds}s.csv.gz')
        if name in completed and parsed_path.is_file() and raw_path.is_file():continue
        if time.monotonic()>=token_refresh_at:
            token=access_token();token_refresh_at=time.monotonic()+480
        request=urllib.request.Request(f'{DOWNLOAD}({product_id})/$value',headers={'Authorization':f'Bearer {token}'})
        with urllib.request.urlopen(request,timeout=timeout) as response:payload=response.read()
        digest=hashlib.sha256(payload).hexdigest();tmp=raw_path.with_suffix('.TGZ.part');tmp.write_bytes(payload);tmp.replace(raw_path)
        rows=parse_product(payload,name,sample_seconds)
        rows=[row for row in rows if requested_start<=dt.datetime.fromisoformat(row['epoch_utc'].replace('Z','+00:00'))<requested_end]
        parsed_tmp=parsed_path.with_suffix(parsed_path.suffix+'.part')
        with gzip.open(parsed_tmp,'wt',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
        parsed_tmp.replace(parsed_path)
        completed[name]={'product_id':product_id,'validity':product.get('ContentDate'),
            'raw_file':str(raw_path.relative_to(output)),'raw_bytes':len(payload),'sha256':digest,
            'parsed_file':str(parsed_path.relative_to(output)),'parsed_records':len(rows),
            'quaternion_source_counts':{source:sum(row['source_flag']==source for row in rows) for source in ['r','i','s']}}
        manifest['products']=completed;manifest['status']='running';_write_manifest(manifest_path,manifest)
        print(f'[{index}/{len(products)}] {name}: {len(rows):,} samples',flush=True)
    manifest['status']='completed';manifest['product_count']=len(completed)
    manifest['records_parsed']=sum(item['parsed_records'] for item in completed.values())
    manifest['completed_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    _write_manifest(manifest_path,manifest)
    return manifest
