import concurrent.futures, hashlib, json, pathlib, urllib.request
root=pathlib.Path(__file__).resolve().parents[1]/'data/raw'
repo='juliensimon/space-track-tle-history'
meta=json.load(urllib.request.urlopen(f'https://huggingface.co/api/datasets/{repo}'))
revision=meta['sha']
files=json.load(urllib.request.urlopen(f'https://huggingface.co/api/datasets/{repo}/tree/{revision}/data'))
files=[f for f in files if f['path'] in [f'data/tle_{y}.parquet' for y in range(2022,2027)]]
(root/'manifest.json').write_text(json.dumps({'repository':repo,'revision':revision,'files':files},indent=2))
def download(f):
    path=root/pathlib.Path(f['path']).name
    if not path.exists():
        tmp=path.with_suffix('.part')
        with urllib.request.urlopen(f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{f['path']}?download=true",timeout=120) as r, tmp.open('wb') as out:
            while chunk:=r.read(8*1024*1024): out.write(chunk)
        tmp.rename(path)
    hasher=hashlib.sha256()
    with path.open('rb') as source:
        while chunk:=source.read(8*1024*1024): hasher.update(chunk)
    digest=hasher.hexdigest()
    assert path.stat().st_size==f['size'] and digest==f['lfs']['oid'],path
    print(f'{path.name}: verified {path.stat().st_size} bytes',flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(download,files))
