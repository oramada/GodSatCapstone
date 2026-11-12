"""Lossless Float64 scene transport; the saved format remains canonical JSON."""
from array import array
from itertools import chain
import json
import struct
import sys

MIME = 'application/vnd.godsat.scene-f64'
MISSING = (float('nan'),) * 3


def encode_packed_scene(scene):
    objects, velocities, tracks = [], [], []
    for obj in scene['objects']:
        objects.append({k: v for k, v in obj.items() if k not in ('positions_km', 'velocities_km_s')})
        tracks.append(obj['positions_km'])
        has_velocity = 'velocities_km_s' in obj
        velocities.append(has_velocity)
        if has_velocity:
            tracks.append(obj['velocities_km_s'])
    header = json.dumps({'scene': {**scene, 'objects': objects}, 'velocities': velocities},
                        separators=(',', ':'), allow_nan=False).encode()
    numbers = array('d', chain.from_iterable(MISSING if row is None else row for track in tracks for row in track))
    if sys.byteorder != 'little':
        numbers.byteswap()
    return b''.join((b'GDS1', struct.pack('<I', len(header)), header, numbers.tobytes()))
