"""Canonical scene adapters. Positions retain their declared scientific frame.

Missing coordinates stay null. Observation status is never inferred from geometry.
"""
import csv
import datetime as dt
import json
import math
import zipfile
from pathlib import Path
from .catalog import MAX_BYTES, clean

VERSION = 'godsat.scene.v1'
MAX_FRAMES = 1200
MAX_OBJECTS = 20000
MAX_SAMPLES = 1200000


def base(title, frame, times, objects, source, *, _json_coordinates=False, **extra):
    if frame not in {'TEME', 'GCRS', 'ITRS'}: raise ValueError('Scene requires an explicit TEME, GCRS or ITRS frame')
    if not times: raise ValueError('Scene has no time samples')
    stamps = [dt.datetime.fromisoformat(str(t).replace('Z', '+00:00')) for t in times]
    if any(t.tzinfo is None for t in stamps) or any(a >= b for a, b in zip(stamps, stamps[1:])):
        raise ValueError('Scene timestamps must be timezone-aware and strictly increasing')
    if len(times) > MAX_FRAMES or len(objects) > MAX_OBJECTS or len(times)*len(objects) > MAX_SAMPLES:
        raise ValueError('Scene exceeds 1,200 frames, 20,000 objects or 1,200,000 position samples; export a bounded window')
    if len({o['id'] for o in objects}) != len(objects): raise ValueError('Object IDs must be unique')
    for obj in objects:
        if 'attitude' in obj:
            from .attitude import validate_attitude
            validate_attitude(obj['attitude'], frame, len(times))
        if not isinstance(obj['id'], str) or obj.get('kind') not in {'satellite', 'sensor', 'station'}:
            raise ValueError('Objects require string IDs and a supported kind')
        if len(obj['positions_km']) != len(times): raise ValueError('Position timeline does not match scene times')
        for p in obj['positions_km']:
            if p is not None and (len(p) != 3 or not all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in p)):
                raise ValueError('Positions must be finite three-vectors or null')
        if 'velocities_km_s' in obj:
            velocities = obj['velocities_km_s']
            if not isinstance(velocities, list) or len(velocities) != len(times):
                raise ValueError('Velocity timeline does not match scene times')
            for v in velocities:
                if v is not None and (len(v) != 3 or not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in v)):
                    raise ValueError('Velocities must be finite three-vectors in km/s or null')
    observations = extra.get('observations')
    if observations is not None:
        if len(observations) != len(times): raise ValueError('Observation timeline does not match scene times')
        ids = {o['id'] for o in objects}
        for row in observations:
            if row is None: continue
            if not isinstance(row, dict) or not isinstance(row.get('detected'), list) or any(i not in ids for i in row['detected']):
                raise ValueError('Detected IDs must refer to scene objects')
            for action in row.get('actions', []):
                if action.get('sensor') not in ids or action.get('target') not in ids:
                    raise ValueError('Actions must refer to scene objects')
    custody = extra.get('custody_seconds', 180)
    if 'ground_links' in extra:
        from godsat.simulation.links import validate_config
        validate_config(extra['ground_links'])
    if not isinstance(custody, (int, float)) or not math.isfinite(custody) or custody < 0:
        raise ValueError('Custody window must be finite and nonnegative')
    scene = {'schema': VERSION, 'title': title, 'frame': frame, 'units': 'km',
        'times': times, 'objects': objects, 'source': source, 'custody_seconds': 180,
        'observations': None, 'warnings': [], **extra}
    if not _json_coordinates:
        return clean(scene)
    # The JSON decoder owns these arrays, and validation above already checked
    # every coordinate. Copy and sanitize metadata without walking the arrays again.
    return {
        key: clean(value) if key != 'objects' else [
            {name: field if name in {'positions_km', 'velocities_km_s'} else clean(field)
             for name, field in obj.items()}
            for obj in objects
        ]
        for key, value in scene.items()
    }


def demo_scene(root, system=False):
    """Illustrative geometry using pinned identities and configured site coordinates."""
    root = Path(root)
    sites = json.loads((root/'configs/ground-tracking-sites.json').read_text())['sites']
    members = json.loads((root/'configs/iridium-next-membership.json').read_text())['members']
    times = [(dt.datetime(2026, 9, 15, tzinfo=dt.timezone.utc)+dt.timedelta(minutes=i)).isoformat() for i in range(13)]
    objects = []
    chosen_sites = sites if system else sites[:1]
    for site in chosen_sites:
        xyz = [x/1000 for x in site['solutions'][-1]['xyz_m']]
        objects.append({'id': str(-int(site['site_id'])), 'name': site['name'], 'kind': 'station', 'positions_km': [xyz]*len(times)})
    # Small demonstration passes the first station. This is not a TLE trajectory.
    p = objects[0]['positions_km'][0]
    norm = math.sqrt(sum(x*x for x in p)); up = [x/norm for x in p]
    east = [-up[1], up[0], 0]; en = math.hypot(*east[:2]); east = [x/en for x in east]
    count = len(members) if system else 1
    for j, member in enumerate(members[:count]):
        positions = []
        for k in range(len(times)):
            if system:
                inclination = math.radians(86.4); a = 2*math.pi*(j%11)/11+k*.063; raan = (j//11)*math.pi/6
                x, y, z = math.cos(a), math.sin(a)*math.cos(inclination), math.sin(a)*math.sin(inclination)
                positions.append([7158*(x*math.cos(raan)-y*math.sin(raan)), 7158*(x*math.sin(raan)+y*math.cos(raan)), 7158*z])
            else:
                angle = (k-6)*.08
                positions.append([7158*(up[i]*math.cos(angle)+east[i]*math.sin(angle)) for i in range(3)])
        objects.append({'id': str(member['norad_id']), 'name': member['name'], 'kind': 'satellite', 'positions_km': positions})
    observations = []
    for k in range(13):
        observations.append({'detected': [o['id'] for o in objects[len(chosen_sites):] if k < 4 or k >= 10],
            'actions': [{'sensor': objects[j]['id'], 'target': objects[len(chosen_sites)+j%count]['id']} for j in range(len(chosen_sites))],
            'cause': 'Illustrative imposed dropout' if 4 <= k < 10 else 'Illustrative successful observation'})
    return base('Constellation demonstration' if system else 'When a satellite disappears from the tracker', 'ITRS', times, objects,
        {'kind': 'illustrative', 'description': 'Pinned Iridium NEXT names and published station coordinates; constructed orbits and imposed observations. Not a saved experiment.'},
        observations=observations, warnings=['Orbit, Earth-pointing pose and dropout sequence are illustrative. No attitude telemetry or measured atmosphere is used.'])


def load_scene(path, json_bytes=None):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES: raise ValueError('Export a scene window below 64 MiB before replay')
    if path.suffix == '.npz':
        with zipfile.ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > 256*1024*1024:
                raise ValueError('Uncompressed scenario exceeds 256 MiB; export a smaller window')
        import numpy as np
        with np.load(path, allow_pickle=False) as a:
            required = {'states', 'ids', 'times', 'agents'}
            if not required.issubset(a.files): raise ValueError('NPZ is not a scenario: requires states, ids, times and agents')
            if a['states'].ndim != 3 or a['states'].shape[-1] < 3: raise ValueError('Invalid scenario state shape')
            value = {'ids': a['ids'].tolist(), 'times': a['times'].tolist(), 'agents': int(a['agents']),
                'positions_km': a['states'][:, :, :3].tolist(), 'frame': 'TEME'}
            sidecar = path.with_suffix('.json')
            if sidecar.is_file(): value['frame'] = json.loads(sidecar.read_text()).get('frame', 'TEME')
        return replay_scene(value, path.name)
    if path.suffix == '.json':
        if json_bytes is not None and len(json_bytes)>MAX_BYTES: raise ValueError('JSON exceeds 64 MiB')
        value = json.loads(path.read_text() if json_bytes is None else json_bytes)
        return decode_json_scene(path, value)
    if path.suffix in {'.csv', '.parquet'}:
        if path.suffix == '.csv':
            with path.open(newline='') as f:
                rows = []
                for row in csv.DictReader(f):
                    rows.append(row)
                    if len(rows) > 200000: raise ValueError('Export a trajectory window below 200,000 rows')
        else:
            import pyarrow.parquet as pq
            pf = pq.ParquetFile(path)
            if pf.metadata.num_rows > 200000: raise ValueError('Export a trajectory window below 200,000 rows')
            rows = pf.read().to_pylist()
        return table_scene(rows, path.name)
    raise ValueError('This format has no spatial adapter. Open the processed product in the inspector.')


def decode_json_scene(path, value):
    """Normalize an already parsed scene or legacy replay."""
    if isinstance(value, dict) and value.get('schema') == VERSION:
        if value.get('units') != 'km': raise ValueError('Scene coordinates must use kilometers')
        extra = {}
        if 'ground_links' in value:extra['ground_links']=value['ground_links']
        if 'environment' in value:
            from godsat.simulation.environment import validate_environment
            extra['environment'] = validate_environment(value['environment'])
        result = base(value['title'], value['frame'], value['times'], value['objects'], value['source'], _json_coordinates=True,
            observations=value.get('observations'), custody_seconds=value.get('custody_seconds', 180), warnings=value.get('warnings', []), **extra)
        if result['observations'] is not None and len(result['observations']) != len(result['times']):
            raise ValueError('Observation timeline does not match scene times')
        return result
    if isinstance(value, dict) and {'positions_km', 'times', 'ids'} <= value.keys():
        config_path = path.parent/'config.json'
        if not config_path.is_file() and path.parent.name == 'replays': config_path = path.parent.parent/'config.json'
        if config_path.is_file() and config_path.stat().st_size < MAX_BYTES:
            config = json.loads(config_path.read_text())
            value.setdefault('custody_seconds', config.get('custody_seconds', 180))
        return replay_scene(value, path.name)
    raise ValueError('This JSON is not a scene or replay. Open it in the artifact inspector.')


def replay_scene(value, name):
    positions, ids, times = value['positions_km'], value['ids'], value['times']
    agents = int(value.get('agents', 0))
    if not 0 <= agents <= len(ids): raise ValueError('Invalid sensor count')
    if len(positions) != len(times) or any(len(p) != len(ids) for p in positions): raise ValueError('Replay dimensions do not agree')
    valid = value.get('valid')
    objects = []
    for j, oid in enumerate(ids):
        track = []
        for k, frame in enumerate(positions):
            p = frame[j]
            ok = p is not None and len(p) >= 3 and all(v is not None and math.isfinite(v) for v in p[:3])
            if valid is not None: ok = ok and bool(valid[k][j])
            track.append(p[:3] if ok else None)
        objects.append({'id': str(oid), 'name': ('Station ' if int(oid)<0 else 'NORAD ')+str(abs(int(oid))),
            'kind': 'station' if int(oid)<0 else ('sensor' if j < agents else 'satellite'), 'positions_km': track})
    trace = value.get('trace'); obs = None
    if trace is not None:
        obs = [None]*len(times)
        for row in trace:
            k = int(row['step'])
            if not 0 <= k < len(times): raise ValueError('Trace step outside trajectory timeline')
            detected = [objects[agents+int(j)]['id'] for j in row['detected'] if 0 <= int(j) < len(ids)-agents]
            actions = [{'sensor': objects[i]['id'], 'target': objects[agents+int(j)]['id']}
                for i, j in enumerate(row.get('actions', [])[:agents]) if 0 <= int(j) < len(ids)-agents]
            obs[k] = {'detected': detected, 'actions': actions, 'cause': 'Saved policy trace; a missed return alone does not identify its cause',
                'metrics': {k: v for k, v in row.items() if k not in {'detected', 'actions'}}}
    return base(name, value.get('frame', 'TEME'), times, objects, {'kind': 'saved', 'description': name}, observations=obs,
        custody_seconds=value.get('custody_seconds', 180), warnings=['No attitude telemetry attached; spacecraft pose is an Earth-pointing illustration.'] +
        ([] if obs else ['No observation trace attached. Tracking status is unknown; trajectories alone do not establish custody.']))


def table_scene(rows, name):
    if not rows: raise ValueError('Table is empty')
    keys = rows[0].keys()
    frame = next((f for f in ('TEME', 'GCRS', 'ITRS') if all(f'{c}_{f.lower()}_km' in keys for c in 'xyz')), None)
    time_key = next((k for k in ('time_utc', 'epoch', 'timestamp_utc', 'epoch_utc') if k in keys), None)
    if frame is None or time_key is None or 'norad_id' not in keys:
        raise ValueError('No geocentric state columns with explicit frame and time. Use the inspector for angular observations, attitude or metrics.')
    times = sorted({str(row[time_key].isoformat() if hasattr(row[time_key], 'isoformat') else row[time_key]) for row in rows})
    ids = sorted({str(row['norad_id']) for row in rows})
    table = {(str(row[time_key].isoformat() if hasattr(row[time_key], 'isoformat') else row[time_key]), str(row['norad_id'])): row for row in rows}
    pos = []
    for t in times:
        line = []
        for oid in ids:
            row = table.get((t, oid)); p = None
            if row:
                try: p = [float(row[f'{c}_{frame.lower()}_km']) for c in 'xyz']
                except (ValueError, TypeError): pass
                if row.get('sgp4_error') not in (None, '', 0, '0'): p = None
            line.append(p)
        pos.append(line)
    return replay_scene({'times': times, 'ids': ids, 'positions_km': pos, 'frame': frame}, name)
