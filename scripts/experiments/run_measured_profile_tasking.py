"""Run paired weekly full-catalog sensitivity using audited CASSIOPE outages."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np

from godsat.orbits import ROOT
from scripts.validation.audit_full_catalog_tasking import audit as audit_results
from scripts.experiments.run_full_catalog_tasking import run as run_tasking, sha256


def validate_source_gate(data):
    data = Path(data)
    manifest = json.loads((data/'manifest.json').read_text())
    source = json.loads((data/'independent_audit.json').read_text())
    days = int(manifest.get('products_validated', 0))
    absent = int(manifest.get('days_not_published', 0))
    if (manifest.get('status') != 'completed' or manifest.get('failures')
            or days + absent != manifest.get('requested_days')
            or manifest.get('days_processed') != manifest.get('requested_days')
            or source.get('status') != 'passed_structural_and_statistical'
            or source.get('downloaded_days') != days or days < 1
            or not source.get('source_cdf_replay_requested')
            or source.get('source_cdf_days_replayed') != days
            or not source.get('publisher_absence_verification_requested')
            or source.get('publisher_absence_probes_verified') != absent
            or source.get('failures')):
        raise ValueError('Complete source-CDF replay and publisher-availability reconciliation are required')
    return source


def run(campaign, data, output, process='empirical-block'):
    campaign, data, output = map(lambda path: Path(path).resolve(), (campaign, data, output))
    source = validate_source_gate(data)
    profile_path = data/'dropout_profile_1minute.json'
    profile = json.loads(profile_path.read_text())
    if (profile.get('status') != 'completed'
            or profile.get('source_audit_sha256') != sha256(data/'independent_audit.json')
            or profile.get('source_acquisition_manifest_sha256') != sha256(data/'manifest.json')
            or [row['date'] for row in profile.get('per_day', [])] != source.get('validated_dates')):
        raise ValueError('Measured profile is not bound to the reconciled source archive')
    mask_audit = json.loads((data/'dropout_masks_independent_audit.json').read_text())
    mask_path = data/'dropout_masks_1minute.npz'
    if (mask_audit.get('status') != 'passed_independent_source_replay'
            or not mask_audit.get('profile_transition_and_bootstrap_statistics_verified')
            or mask_audit.get('source_profile_sha256') != sha256(profile_path)
            or mask_audit.get('mask_archive_sha256') != sha256(mask_path)
            or mask_audit.get('cadence_seconds') != 60):
        raise ValueError('Source masks and profile transition/interval statistics must pass independent validation')
    with np.load(mask_path, allow_pickle=False) as archive:
        masks = archive['dropout'].astype(bool)
        mask_dates = archive['dates'].astype(str).tolist()
    if (mask_dates != source['validated_dates'] or masks.shape != (len(mask_dates), 1440)
            or not np.isclose(masks.mean(), profile['one_minute_attitude_solution_dropout_rate'], atol=0, rtol=0)):
        raise ValueError('Source mask shape, dates, or measured rate differs')
    first, last = dt.date(2022, 10, 15), dt.date(2026, 10, 3)
    dates = [f'{first + dt.timedelta(days=7*index)}T00:00:00Z'
             for index in range((last-first).days//7 + 1)]
    empirical = process == 'empirical-block'
    if process not in {'empirical-block', 'fitted-markov'}:
        raise ValueError('Unknown outage process')
    result = run_tasking(output, dates, target_cohort='all', campaign=campaign,
        outage_rates=(0., float(profile['one_minute_attitude_solution_dropout_rate'])),
        dropout_profile=profile, dropout_profile_sha256=sha256(profile_path),
        dropout_profile_path=str(profile_path),
        empirical_dropout_masks=masks if empirical else None,
        empirical_dropout_metadata=mask_audit if empirical else None)
    audit = audit_results(output)
    return {'status': audit['status'], 'date_count': len(dates), 'process': process,
            'paired_cells': result['completed_date_regime_groups'],
            'response_rows': len(result['rows']), 'output': str(output),
            'interpretation': 'A measured one-spacecraft attitude-availability sequence applied as an outage reference to hypothetical tasking hosts; it is not a fleet reliability or ground-acquisition estimate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--data', type=Path, default=ROOT/'data/attitude/cassiope_epop')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--process', choices=('empirical-block', 'fitted-markov'), default='empirical-block')
    args = parser.parse_args()
    print(json.dumps(run(args.campaign, args.data, args.output, args.process), indent=2))


if __name__ == '__main__':
    main()
