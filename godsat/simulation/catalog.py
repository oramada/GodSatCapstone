"""Bounded, vectorized SGP4 windows from CCSDS/CelesTrak GP JSON or TLEs."""
import datetime as dt
import hashlib
import importlib.metadata
import json
from pathlib import Path
import warnings

import numpy as np
from sgp4 import omm
from sgp4.api import Satrec, SatrecArray, SGP4_ERRORS, jday

from godsat.studio.scene import base, MAX_SAMPLES, MAX_OBJECTS, MAX_FRAMES
from .environment import utc, validate_environment


def load_catalog(path, format='omm'):
    """Reject ambiguous duplicate identities; caller must choose a snapshot."""
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Catalog exceeds 64 MiB')
    raw = path.read_text()
    records = []
    if format == 'omm':
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError('GP JSON must contain a list of OMM records')
        for row in data:
            fields = dict(row)
            # CelesTrak documents these omitted, redundant defaults for GP JSON.
            for key, default in {'CENTER_NAME': 'EARTH', 'REF_FRAME': 'TEME',
                                 'TIME_SYSTEM': 'UTC', 'MEAN_ELEMENT_THEORY': 'SGP4'}.items():
                if fields.get(key, default) != default:
                    raise ValueError(f'Unsupported OMM {key}')
                fields.setdefault(key, default)
            fields.setdefault('OBJECT_ID', '')
            fields.setdefault('CLASSIFICATION_TYPE', 'U')
            fields.setdefault('EPHEMERIS_TYPE', 0)
            fields.setdefault('ELEMENT_SET_NO', 0)
            fields.setdefault('REV_AT_EPOCH', 0)
            sat = Satrec()
            omm.initialize(sat, fields)
            records.append((str(sat.satnum), str(fields.get('OBJECT_NAME', sat.satnum)), sat))
    elif format == 'tle':
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        i = 0
        while i < len(lines):
            name = None
            if not lines[i].startswith('1 '):
                name = lines[i].removeprefix('0 ')
                i += 1
            if i + 1 >= len(lines) or not lines[i].startswith('1 ') or not lines[i+1].startswith('2 '):
                raise ValueError('Expected matching TLE line 1 and line 2')
            first, second = lines[i:i+2]
            if first[2:7] != second[2:7]:
                raise ValueError('TLE identity mismatch')
            from sgp4.io import verify_checksum
            verify_checksum(first, second)
            sat = Satrec.twoline2rv(first, second)
            records.append((str(sat.satnum), name or str(sat.satnum), sat))
            i += 2
    else:
        raise ValueError('Catalog format must be omm or tle')
    if not records or len({row[0] for row in records}) != len(records):
        raise ValueError('Catalog must be nonempty with unique satellite IDs')
    source = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'format': format, 'objects': len(records)}
    sidecar = path.with_suffix('.source.json')
    if sidecar.is_file() and sidecar.stat().st_size < 1024*1024:
        provenance = json.loads(sidecar.read_text())
        if provenance.get('sha256') != source['sha256']:
            raise ValueError('Catalog download provenance does not match the input hash')
        source['download'] = provenance
    return records, source


def make_times(start, duration_seconds, step_seconds):
    start = utc(start)
    if not np.isfinite([duration_seconds, step_seconds]).all() or duration_seconds <= 0 or step_seconds <= 0:
        raise ValueError('Duration and cadence must be positive and finite')
    frames = int(np.ceil(duration_seconds / step_seconds)) + 1
    if frames > 1200:
        raise ValueError('Request at most 1,200 frames per window')
    offsets = np.minimum(np.arange(frames) * step_seconds, duration_seconds)
    return [start + dt.timedelta(seconds=float(v)) for v in offsets]


def propagate(records, times, max_age_hours=72):
    """Return TEME km, km/s, and codes. Never use elements before their epoch."""
    if not records or not times or len(records) > MAX_OBJECTS or len(times) > MAX_FRAMES or len(records)*len(times) > MAX_SAMPLES:
        raise ValueError('Propagation window exceeds the sample budget or is empty')
    if not np.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ValueError('Maximum element age must be positive and finite')
    times = [utc(t.isoformat() if hasattr(t, 'isoformat') else t) for t in times]
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError('Propagation times must be strictly increasing')
    jd, fraction = np.array([jday(t.year, t.month, t.day, t.hour, t.minute,
                                   t.second + t.microsecond / 1e6) for t in times]).T
    jd, fraction = np.ascontiguousarray(jd), np.ascontiguousarray(fraction)
    satellites = [row[2] for row in records]
    codes, position, velocity = SatrecArray(satellites).sgp4(jd, fraction)
    # Subtract split Julian parts separately to preserve precision.
    ages = np.array([((jd-s.jdsatepoch)+(fraction-s.jdsatepochF))*24 for s in satellites])
    codes = codes.astype(np.int16)
    codes[(ages < -1e-8)] = -2
    codes[(ages > max_age_hours)] = -1
    failed = (codes != 0) | ~np.isfinite(position).all(axis=2) | ~np.isfinite(velocity).all(axis=2)
    codes[(codes == 0) & failed] = -3
    position[failed] = np.nan
    velocity[failed] = np.nan
    return position, velocity, codes, ages


def position_derivatives(records, times, codes, difference_seconds=.25):
    """Differentiate the SGP4 *position curve* for Hermite interpolation.

    SGP4's returned state velocity need not exactly differentiate its position
    series (notably for deep-space terms). A centered numerical tangent avoids
    treating those two quantities as interchangeable in the display ephemeris.
    Offsets are internal evaluations, not additional valid catalog epochs.
    """
    dates=np.array([jday(t.year,t.month,t.day,t.hour,t.minute,t.second+t.microsecond/1e6) for t in times])
    jd=np.ascontiguousarray(dates[:,0]); fr=np.ascontiguousarray(dates[:,1])
    array=SatrecArray([r[2] for r in records]); h=difference_seconds/86400
    em,pm,_=array.sgp4(jd,np.ascontiguousarray(fr-h))
    ep,pp,_=array.sgp4(jd,np.ascontiguousarray(fr+h))
    derivatives=(pp-pm)/(2*difference_seconds)
    derivatives[(codes!=0)|(em!=0)|(ep!=0)]=np.nan
    return derivatives


def to_itrs(position, times, velocity=None):
    """Scientific frame conversion with bundled EOP and recorded warnings."""
    import astropy
    import astropy.units as u
    from astropy.coordinates import TEME, ITRS, CartesianRepresentation, CartesianDifferential
    from astropy.time import Time
    from astropy.utils import iers
    result = np.full_like(position, np.nan)
    velocities = np.full_like(velocity, np.nan) if velocity is not None else None
    with warnings.catch_warnings(record=True) as notices, iers.conf.set_temp('auto_download', False):
        warnings.simplefilter('always')
        t = Time(times)
        table = iers.earth_orientation_table.get()
        _, status = table.ut1_utc(t, return_status=True)
        for k in range(len(times)):
            valid = np.isfinite(position[:, k]).all(axis=1)
            if not valid.any():
                continue
            differential = None if velocity is None else CartesianDifferential(velocity[valid, k].T * u.km/u.s)
            xyz = CartesianRepresentation(position[valid, k].T * u.km, differentials=differential)
            transformed = TEME(xyz, obstime=t[k]).transform_to(ITRS(obstime=t[k]))
            result[valid, k] = transformed.cartesian.xyz.to_value(u.km).T
            if velocities is not None:
                velocities[valid, k] = transformed.velocity.d_xyz.to_value(u.km/u.s).T
        data_path = Path(table.meta.get('data_path', ''))
        provenance = {'library': 'Astropy', 'version': astropy.__version__,
                      'source_frame': 'TEME', 'target_frame': 'ITRS',
                      'earth_orientation_table': type(table).__name__,
                      'eop_status_codes': sorted(set(np.asarray(status).tolist())),
                      'eop_status_meaning': {'-2': 'beyond range', '-1': 'before range',
                                             '0': 'IERS B', '1': 'IERS A', '2': 'IERS A prediction'},
                      'eop_sha256': hashlib.sha256(data_path.read_bytes()).hexdigest() if data_path.is_file() else None,
                      'warnings': sorted({str(w.message) for w in notices})}
    return (result, provenance) if velocity is None else (result, velocities, provenance)


def build_scene(records, times, catalog_source, max_age_hours=72, frame='ITRS', environment=None, ground_links=None):
    position, _, codes, ages = propagate(records, times, max_age_hours)
    velocity = position_derivatives(records, times, codes)
    transform = None
    if frame == 'ITRS':
        position, velocity, transform = to_itrs(position, times, velocity)
    elif frame != 'TEME':
        raise ValueError('Simulation export frame must be ITRS or TEME')
    objects = []
    for j, (sid, name, sat) in enumerate(records):
        objects.append({'id': sid, 'name': name, 'kind': 'satellite',
                        'positions_km': [p.tolist() if np.isfinite(p).all() else None for p in position[j]],
                        'velocities_km_s': [v.tolist() if np.isfinite(v).all() else None for v in velocity[j]]})
    unique, counts = np.unique(codes, return_counts=True)
    code_counts = {str(int(c)): int(n) for c, n in zip(unique, counts)}
    source = {'kind': 'modeled', 'description': 'SGP4 propagation of supplied catalog mean elements; not measured positions.',
              'catalog': catalog_source, 'propagator': 'SGP4', 'sgp4_version': importlib.metadata.version('sgp4'),
              'gravity_constants': 'WGS72', 'max_element_age_hours': max_age_hours,
              'element_age_hours_range': [float(ages.min()), float(ages.max())],
              'status_counts': code_counts, 'status_meaning': {**{str(k): v for k, v in SGP4_ERRORS.items()},
                '-1': 'stale elements', '-2': 'future elements rejected', '-3': 'nonfinite state', '0': 'valid'},
              'frame_transform': transform,
              'velocity_derivation': 'Centered derivative of SGP4 position curve, +/- 0.25 seconds; transformed with the position to the scene frame. Not the independent SGP4 state-velocity output.',
              'interpolation': 'Cubic Hermite with position and velocity in the declared frame'}
    notes = ['Positions are predictions without an estimated covariance; no claim of operational tracking accuracy.',
             'Between-sample display interpolation is cubic Hermite. Validate interpolation error for your orbit regime and cadence.',
             'No attitude telemetry or detection history supplied.',
             'Environmental samples do not modify SGP4 forces; missing inputs stay unavailable.']
    if transform and (transform['warnings'] or any(v < 0 or v == 2 for v in transform['eop_status_codes'])):
        notes.append('Earth orientation uses predicted or out-of-range data; consult frame_transform provenance.')
    if any(code != '0' for code in code_counts):
        notes.append('Some states are unavailable; consult source.status_counts for stale, future or failed states.')
    extra = {}
    if ground_links is not None:extra['ground_links']=ground_links
    if environment is not None:
        extra['environment'] = validate_environment(environment)
    return base('Catalog satellite simulation', frame, [t.isoformat() for t in times], objects,
                source, warnings=notes, **extra)
