"""Probe Sentinel AUX_PROQUA retrieval without downloading product payloads."""
from __future__ import annotations
import argparse, datetime as dt, json, os, pathlib, urllib.error, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
INVENTORY=ROOT/'data/attitude/sentinel_quaternions/catalog_inventory.json'
CATALOGUE='https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
DOWNLOAD='https://download.dataspace.copernicus.eu/odata/v1/Products'
S3='https://eodata.dataspace.copernicus.eu'
LEGACY='https://scihub.copernicus.eu/gnss/search?q=platformname%3ASentinel-3A%20AND%20producttype%3AAUX_PROQUA'
UA='GoDSAT-research-data-access-audit/1.0'

def bounded_get(url, headers=None, timeout=25):
    request=urllib.request.Request(url,headers={'Range':'bytes=0-1023','User-Agent':UA,**(headers or {})})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            body=response.read(1024)
            return {'status_code':response.status,'content_type':response.headers.get('Content-Type'),
                    'range_bytes_read':len(body),'body_prefix':body[:200].decode('utf-8','replace')}
    except urllib.error.HTTPError as error:
        body=error.read(1024)
        return {'status_code':error.code,'content_type':error.headers.get('Content-Type'),
                'range_bytes_read':len(body),'body_prefix':body[:200].decode('utf-8','replace')}
    except Exception as error:
        return {'error_type':type(error).__name__,'error':str(error)[:300]}

def run(output:pathlib.Path):
    inventory=json.loads(INVENTORY.read_text())
    products=[p for values in inventory['products_by_platform'].values() for p in values]
    sample=min(products,key=lambda p:int(p['content_length']))
    product_id=sample['id']
    catalog=bounded_get(f'{CATALOGUE}({product_id})?$select=Id,Name,S3Path,ContentLength')
    record={'audit_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'inventory_path':str(INVENTORY.relative_to(ROOT)),
        'inventory_catalogued_utc':inventory['catalogued_utc'],
        'inventory_window':{'start':inventory['requested_start_utc'],'end_exclusive':inventory['requested_end_exclusive_utc']},
        'inventory_products':len(products),'inventory_content_bytes':sum(int(p['content_length']) for p in products),
        'sample_product':sample,'credential_presence':{'CDSE_USERNAME':bool(os.environ.get('CDSE_USERNAME')),'CDSE_PASSWORD':bool(os.environ.get('CDSE_PASSWORD'))},
        'probes':{'public_catalogue_product_metadata':catalog}}
    if catalog.get('status_code')==200:
        try:
            with urllib.request.urlopen(f'{CATALOGUE}({product_id})?$select=Id,Name,S3Path,ContentLength',timeout=25) as response:
                detail=json.load(response)
            record['probes']['odata_product_download_without_token']=bounded_get(f'{DOWNLOAD}({product_id})/$value')
            s3_path=detail.get('S3Path')
            record['sample_product']['s3_path']=s3_path
            if s3_path:
                record['probes']['s3_object_without_keys']=bounded_get(S3+s3_path)
        except Exception as error:
            record['probes']['odata_metadata_parse_error']=f'{type(error).__name__}: {str(error)[:300]}'
    record['probes']['legacy_pod_catalogue']=bounded_get(LEGACY)
    record['interpretation']='Metadata discovery is public. This audit reads at most 1 KiB from each retrieval endpoint and never writes product bytes. Authenticated product retrieval remains dependent on CDSE credentials or valid S3 access keys.'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(record,indent=2)+'\n')
    return record

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=pathlib.Path,default=ROOT/'data/attitude/sentinel_quaternions/access_audit.json');args=parser.parse_args();path=args.output if args.output.is_absolute() else ROOT/args.output;result=run(path);print(json.dumps({'output':str(path),'inventory_products':result['inventory_products'],'inventory_content_bytes':result['inventory_content_bytes'],'probes':result['probes']},indent=2))
if __name__=='__main__':main()
