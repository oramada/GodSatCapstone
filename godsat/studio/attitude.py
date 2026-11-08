"""Explicit Hamilton xyzw rotations from spacecraft body axes to scene axes."""
import math


def validate_attitude(value, frame, count):
    if not isinstance(value, dict):
        raise ValueError('Attitude must be a record')
    if value.get('frame') != frame or value.get('direction') != 'body_to_reference' or value.get('order') != 'xyzw':
        raise ValueError('Attitude requires scene frame, body_to_reference direction and xyzw Hamilton order')
    source = value.get('source')
    if not isinstance(source, dict) or source.get('kind') not in {'observed', 'modeled', 'illustrative'} or not isinstance(source.get('reference'), str) or not source['reference'].strip():
        raise ValueError('Attitude requires a source kind and reference')
    axes = value.get('body_axes')
    if not isinstance(axes, dict) or set(axes) != {'x', 'y', 'z'} or any(not isinstance(v, str) or not v.strip() for v in axes.values()):
        raise ValueError('Attitude requires descriptions of right-handed body x, y and z axes')
    rows = value.get('quaternions')
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError('Attitude timeline must match scene times')
    for q in rows:
        if q is None:
            continue
        if not isinstance(q, list) or len(q) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in q):
            raise ValueError('Attitude requires finite four-vectors or null')
        if abs(sum(v*v for v in q)-1) > 1e-6:
            raise ValueError('Attitude quaternions must have unit norm')
    return value
