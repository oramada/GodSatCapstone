"""Export long catalog runs as independently bounded, overlapping windows."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from .catalog import build_scene
from .environment import utc
from godsat.studio.scene import MAX_FRAMES, MAX_SAMPLES
from godsat.studio.sequence import VERSION, roster_hash, boundary_hash


def window_schedule(start,duration,step,window_seconds,objects):
    if type(objects) is not int or not 1<=objects<=20000: raise ValueError('Sequence requires 1–20,000 objects')
    if not all(math.isfinite(v) and v>0 for v in [duration,step,window_seconds]): raise ValueError('Duration, cadence and window length must be positive')
    start=utc(start)
    intervals=math.ceil(duration/step)
    per_window=min(math.floor(window_seconds/step),MAX_FRAMES-1,MAX_SAMPLES//objects-1)
    if per_window<1: raise ValueError('Window must contain at least two samples within the memory budget')
    if math.ceil(intervals/per_window)>10000: raise ValueError('Sequence exceeds 10,000 windows')
    for offset in range(0,intervals,per_window):
        stop=min(offset+per_window,intervals)
        yield offset,[start+dt.timedelta(seconds=min(i*step,duration)) for i in range(offset,stop+1)]


def export_sequence(records,source,start,duration,step,window_seconds,output,max_age_hours=72,frame='ITRS',environment=None,ground_links=None):
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    manifest={'schema':VERSION,'title':'Catalog satellite simulation sequence','frame':frame,
        'objects':len(records),'source':source,'windows':[]}
    for index,(offset,times) in enumerate(window_schedule(start,duration,step,window_seconds,len(records))):
        local_environment=None if environment is None else {**environment,'samples':[row for row in environment['samples']
            if utc(row['time_utc'])<=times[-1] and utc(row['valid_until_utc'])>=times[0]]}
        scene=build_scene(records,times,source,max_age_hours,frame,local_environment,ground_links)
        raw=json.dumps(scene,allow_nan=False,separators=(',',':')).encode()
        if len(raw)>64*1024*1024: raise ValueError('Window exceeds 64 MiB; decrease --window-seconds')
        name=f'{output.stem}-window-{index:05d}.json'
        destination=output.parent/name; temporary=destination.with_suffix('.json.tmp')
        temporary.write_bytes(raw); temporary.replace(destination)
        manifest['windows'].append({'file':name,'offset':offset,'frames':len(times),
            'start':scene['times'][0],'end':scene['times'][-1],'sha256':hashlib.sha256(raw).hexdigest(),
            'start_state_sha256':boundary_hash(scene['objects'],0),'end_state_sha256':boundary_hash(scene['objects'],-1)})
        manifest['roster_sha256']=roster_hash(scene['objects'])
        manifest['total_frames']=offset+len(times)
        print(f'Window {index+1}: {name} ({len(raw):,} bytes)',flush=True)
    temporary=output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(manifest,indent=2)+'\n'); temporary.replace(output)
    return manifest
