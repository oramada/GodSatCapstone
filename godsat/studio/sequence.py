"""Lazy, content-verified playback windows in an artifact's own directory."""
import hashlib
import json
from pathlib import Path
from .scene import decode_json_scene, load_scene, MAX_FRAMES, MAX_OBJECTS
from .catalog import MAX_BYTES

VERSION='godsat.sequence.v1'


def roster_hash(objects):
    rows=[]
    for o in objects:
        row=[o['id'],o['kind']]
        if 'attitude' in o:row.append({k:v for k,v in o['attitude'].items() if k!='quaternions'})
        rows.append(row)
    return hashlib.sha256(json.dumps(rows,separators=(',',':'),sort_keys=True).encode()).hexdigest()


def boundary_hash(objects,index):
    rows=[]
    for o in objects:
        row=[o['id'],o['positions_km'][index],o.get('velocities_km_s',[None]*len(o['positions_km']))[index]]
        if 'attitude' in o:row.append(o['attitude']['quaternions'][index])
        rows.append(row)
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def load_manifest(path, json_bytes=None):
    path=Path(path)
    if path.stat().st_size>2*1024*1024: raise ValueError('Sequence manifest exceeds 2 MiB')
    if json_bytes is not None and len(json_bytes)>2*1024*1024: raise ValueError('Sequence manifest exceeds 2 MiB')
    value=json.loads(path.read_text() if json_bytes is None else json_bytes)
    if value.get('schema')!=VERSION: raise ValueError('Not a playback sequence')
    windows=value.get('windows')
    if not isinstance(windows,list) or not 1<=len(windows)<=10000: raise ValueError('Sequence requires 1–10,000 windows')
    if value.get('frame') not in {'ITRS','TEME','GCRS'}: raise ValueError('Invalid sequence frame')
    if type(value.get('objects')) is not int or not 1<=value['objects']<=MAX_OBJECTS: raise ValueError('Invalid sequence object count')
    offset=0; previous=None; previous_state=None; filenames=set()
    for window in windows:
        if type(window.get('frames')) is not int or not 2<=window['frames']<=MAX_FRAMES: raise ValueError('Invalid window frame count')
        if window.get('offset')!=offset: raise ValueError('Window offsets must overlap by exactly one frame')
        if previous is not None and previous!=window.get('start'): raise ValueError('Sequence windows must share a boundary epoch')
        if previous_state is not None and previous_state!=window.get('start_state_sha256'): raise ValueError('Sequence boundary state changed')
        name=window.get('file')
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.json') or name in {'.','..'}:
            raise ValueError('Window must be a JSON file in the manifest directory')
        if name in filenames: raise ValueError('Window filenames must be unique')
        filenames.add(name)
        for key in ['sha256','start_state_sha256','end_state_sha256']:
            digest=window.get(key)
            if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest): raise ValueError('Window requires SHA-256 hashes')
        from datetime import datetime
        start=datetime.fromisoformat(window['start'].replace('Z','+00:00'))
        end=datetime.fromisoformat(window['end'].replace('Z','+00:00'))
        if start.tzinfo is None or end.tzinfo is None or end<=start: raise ValueError('Invalid window epochs')
        offset+=window['frames']-1; previous=window['end']; previous_state=window.get('end_state_sha256')
    if value.get('total_frames')!=offset+1: raise ValueError('Sequence total does not match its windows')
    return value


def read_verified_window(manifest_path, index, manifest):
    """Read a bounded byte snapshot and check its digest even on a cache hit."""
    manifest_path=Path(manifest_path)
    if type(index) is not int or not 0<=index<len(manifest['windows']): raise ValueError('Window index outside sequence')
    window=manifest['windows'][index]; file=manifest_path.parent/window['file']
    if file.is_symlink() or not file.resolve().is_relative_to(manifest_path.parent.resolve()): raise ValueError('Window cannot be a symlink or escape its directory')
    if file.stat().st_size>MAX_BYTES: raise ValueError('Window exceeds 64 MiB')
    with file.open('rb') as stream: raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise ValueError('Window exceeds 64 MiB')
    if hashlib.sha256(raw).hexdigest()!=window['sha256']: raise ValueError('Window content hash changed')
    return file,raw


def decode_window(manifest, index, identity, file, raw, *, value=None):
    window=manifest['windows'][index]
    scene=load_scene(file,json_bytes=raw) if value is None else decode_json_scene(file,value)
    if scene['frame']!=manifest['frame'] or len(scene['objects'])!=manifest['objects'] or roster_hash(scene['objects'])!=manifest['roster_sha256']:
        raise ValueError('Window object roster or reference frame changed')
    if scene['observations'] is not None: raise ValueError('Catalog sequences require unknown observations; saved detection histories need explicit cross-window custody state')
    if len(scene['times'])!=window['frames'] or scene['times'][0]!=window['start'] or scene['times'][-1]!=window['end']:
        raise ValueError('Window timeline does not match manifest')
    if boundary_hash(scene['objects'],0)!=window.get('start_state_sha256') or boundary_hash(scene['objects'],-1)!=window.get('end_state_sha256'):
        raise ValueError('Window boundary state does not match manifest')
    scene['source']['artifact_id']=identity
    scene['source']['sha256']=window['sha256']
    scene['sequence']={'id':identity,'index':index,'offset':window['offset'],
        'total_frames':manifest['total_frames'],'start':manifest['windows'][0]['start'],'end':manifest['windows'][-1]['end'],
        'windows':[{'offset':w['offset'],'frames':w['frames']} for w in manifest['windows']]}
    return scene


def load_window(manifest_path, index, identity):
    manifest=load_manifest(manifest_path)
    file,raw=read_verified_window(manifest_path,index,manifest)
    return decode_window(manifest,index,identity,file,raw)
