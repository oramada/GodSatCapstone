"""Bound whole-window attitude unavailability without assigning states to unpublished days."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def bounds(known_samples, unavailable_samples, requested_samples):
    if not 0 < known_samples <= requested_samples or not 0 <= unavailable_samples <= known_samples:
        raise ValueError('Known and unavailable sample counts must reconcile to the requested window')
    missing = requested_samples-known_samples
    return {'observed_samples': known_samples, 'unobserved_samples': missing,
            'observed_unavailable_samples': unavailable_samples,
            'published_sample_unavailability_fraction': unavailable_samples/known_samples,
            'whole_window_unavailability_fraction_bounds': [unavailable_samples/requested_samples,
                (unavailable_samples+missing)/requested_samples]}


def audit(data):
    names = ['manifest.json', 'independent_audit.json', 'dropout_profile_1minute.json',
             'dropout_masks_independent_audit.json']
    paths = {name: data/name for name in names}
    loaded = {name: json.loads(path.read_text()) for name, path in paths.items()}
    manifest, source, profile, masks = [loaded[name] for name in names]
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if (source.get('status') != 'passed_structural_and_statistical' or source.get('failures')
            or masks.get('status') != 'passed_independent_source_replay'
            or profile.get('source_audit_sha256') != sha(paths['independent_audit.json'])
            or profile.get('source_acquisition_manifest_sha256') != sha(paths['manifest.json'])
            or masks.get('source_profile_sha256') != sha(paths['dropout_profile_1minute.json'])):
        raise ValueError('Current source and mask audit bindings are required')
    first = dt.date.fromisoformat(manifest['requested_start_utc'])
    end = dt.date.fromisoformat(manifest['requested_end_exclusive_utc'])
    days = (end-first).days
    expected = {(first+dt.timedelta(days=index)).isoformat() for index in range(days)}
    published = source['validated_dates']; absent = manifest['not_published_dates']
    if (len(set(published)) != len(published) or len(set(absent)) != len(absent)
            or set(published)&set(absent) or set(published)|set(absent) != expected
            or manifest.get('failures') or source.get('publisher_absence_probes_verified') != len(absent)
            or source.get('source_cdf_days_replayed') != len(published)
            or masks.get('dates_checked') != len(published)):
        raise ValueError('Published/unpublished dates do not reconcile to the complete requested window')
    hz = bounds(source['totals']['samples'], source['totals']['invalid_quaternion_seconds'], days*86400)
    minute = bounds(masks['sample_count_checked'], masks['dropout_count_recomputed'], days*1440)
    if hz['observed_samples'] != len(published)*86400 or minute['observed_samples'] != len(published)*1440:
        raise ValueError('Observed cadence samples do not reconcile to validated complete UTC days')
    return {'status': 'passed_date_reconciliation_and_missingness_bounds', 'requested_days': days,
            'published_days': len(published), 'publisher_unpublished_days': len(absent),
            'one_hz': hz, 'one_minute': minute,
            'published_day_bootstrap_ci95': profile['one_minute_dropout_rate_date_cluster_bootstrap_ci95'],
            'source_receipts': [{'path': str(path), 'sha256': sha(path)} for path in paths.values()],
            'interpretation': 'Deterministic missing-data bounds for the requested window: lower assigns all unobserved samples available; upper assigns all unobserved samples unavailable. No state is asserted for an unpublished day. These are not confidence intervals. The published-day bootstrap interval is conditional on observed days. Attitude-solution unavailability on one spacecraft is not hardware failure or fleet-wide ground-acquisition probability.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT/'data/attitude/cassiope_epop')
    args = parser.parse_args(); result = audit(args.data)
    (args.data/'archive_coverage_bounds.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
