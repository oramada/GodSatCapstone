"""A conservative interchange for environmental observations and model outputs.

Samples remain at their supplied location and time. This module never fills a
missing weather, plasma, or magnetic measurement with a decorative default.
"""
import datetime as dt
import math

SCHEMA = 'godsat.environment.v1'
FIELDS = {
    'vertical_tec_tecu': (0, None),
    'electron_density_m3': (0, None),
    'magnetic_east_nt': (None, None),
    'magnetic_north_nt': (None, None),
    'magnetic_up_nt': (None, None),
    'cloud_fraction': (0, 1),
    'pressure_pa': (0, None),
    'temperature_k': (0, None),
    'neutral_density_kg_m3': (0, None),
}


def utc(value):
    stamp = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Environmental timestamps require an explicit UTC offset')
    return stamp.astimezone(dt.timezone.utc)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_environment(bundle):
    if not isinstance(bundle, dict) or bundle.get('schema') != SCHEMA:
        raise ValueError('Expected godsat.environment.v1')
    sources = bundle.get('sources')
    samples = bundle.get('samples')
    if not isinstance(sources, list) or not isinstance(samples, list) or len(samples) > 100000:
        raise ValueError('Environment requires sources and at most 100,000 samples')
    identifiers = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('Invalid environmental source')
        sid = source.get('id')
        if not isinstance(sid, str) or not sid or sid in identifiers:
            raise ValueError('Environmental source IDs must be unique nonempty strings')
        identifiers.add(sid)
        if source.get('kind') not in {'observed', 'modeled', 'illustrative'}:
            raise ValueError('Environmental source kind must be observed, modeled or illustrative')
        for field in ('name', 'reference'):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise ValueError(f'Environmental source requires {field}')
    for sample in samples:
        if not isinstance(sample, dict) or sample.get('source_id') not in identifiers:
            raise ValueError('Every environmental sample requires a known source_id')
        when = utc(sample['time_utc'])
        end = utc(sample['valid_until_utc'])
        if end < when:
            raise ValueError('Environmental validity cannot end before its sample time')
        for field, lo, hi in [('latitude_deg', -90, 90), ('longitude_deg', -180, 180),
                              ('altitude_km', -1, 100000)]:
            v = sample.get(field)
            if not finite(v) or not lo <= v <= hi:
                raise ValueError(f'Invalid environmental {field}')
        values = sample.get('values')
        if not isinstance(values, dict) or not values or not values.keys() <= FIELDS.keys():
            raise ValueError('Environmental values must use the documented unit-bearing fields')
        for key, value in values.items():
            lo, hi = FIELDS[key]
            if not finite(value) or (lo is not None and value < lo) or (hi is not None and value > hi):
                raise ValueError(f'Invalid environmental {key}')
        magnetic = {'magnetic_east_nt', 'magnetic_north_nt', 'magnetic_up_nt'}
        if magnetic & values.keys() and not magnetic <= values.keys():
            raise ValueError('Magnetic vectors require all three geodetic east/north/up components')
    return bundle


def active_samples(bundle, time_utc):
    """Return only samples whose explicit validity interval includes this time."""
    instant = utc(time_utc)
    return [sample for sample in bundle['samples']
            if utc(sample['time_utc']) <= instant <= utc(sample['valid_until_utc'])]


def ionospheric_group_delay_m(slant_tec_tecu, frequency_hz):
    """First-order group delay (ESA Navipedia); input is slant, not vertical TEC."""
    if not finite(slant_tec_tecu) or slant_tec_tecu < 0:
        raise ValueError('Slant TEC must be finite and nonnegative')
    if not finite(frequency_hz) or frequency_hz <= 0:
        raise ValueError('Frequency must be positive and finite')
    return 40.3e16 * slant_tec_tecu / frequency_hz**2
