"""Compare JSON and Float64 transport on one verified catalog window."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from godsat.studio.service import StudioService


def main():
    manifest = Path(sys.argv[1]).resolve()
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    service = StudioService(Path.cwd(), manifest.parent)
    service.catalog.scan()
    identity = next(key for key, path in service.catalog.paths.items() if path == manifest)
    with tempfile.TemporaryDirectory() as tmp:
        for packed in (False, True):
            fmt = 'packed' if packed else 'json'
            for attempt in ('first', 'repeat'):
                start = time.perf_counter()
                body = service.scene_response(identity, index, include_sky=False, packed=packed)
                print(json.dumps(dict(format=fmt, attempt=attempt, seconds=time.perf_counter()-start, bytes=len(body))), flush=True)
            (Path(tmp) / fmt).write_bytes(body)
        subprocess.run(['node', '--input-type=module', '-e', '''
import {readFileSync} from 'node:fs';
import {deepStrictEqual} from 'node:assert/strict';
import {decodePackedScene} from './web/studio/packed-scene.js';
const text=readFileSync(process.argv[1]+'/json','utf8'),raw=readFileSync(process.argv[1]+'/packed');
const buffer=raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength);
const expected=JSON.parse(text);deepStrictEqual(decodePackedScene(buffer),expected);
const decodeTimes={};
for(const [name,decode] of [['json',()=>JSON.parse(text)],['packed',()=>decodePackedScene(buffer)]]){
 const samples=[];for(let i=0;i<9;i++){const t=performance.now();decode();samples.push(performance.now()-t);}
 decodeTimes[name]=samples.sort((a,b)=>a-b)[4];
}
console.log(JSON.stringify({equivalent:true,objects:expected.objects.length,frames:expected.times.length,decodeMedianMs:decodeTimes}));
''', tmp], check=True)


if __name__ == '__main__':
    main()
