"""Audit trajectory gaps using the complete raw element archive.

The fixed-cadence exporter only loads a short daily lookback. Its null element
age therefore cannot distinguish no earlier archived element from an older
element beyond that loader window. This audit uses the raw archive's first
element epoch plus the independently recomputed freshness sensitivity counts.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib

import duckdb

from godsat.catalog_trajectory import catalog_object_ids
from godsat.orbits import ROOT


def ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def grid_index(boundary: dt.datetime, start: dt.datetime, step_us: int,
               sample_count: int) -> int:
    delta = boundary - start
    delta_us = ((delta.days * 86400 + delta.seconds) * 1_000_000
                + delta.microseconds)
    return max(0, min(sample_count, ceil_div(delta_us, step_us)))


def audit(root: pathlib.Path = ROOT, output: pathlib.Path | None = None,
          freshness_report: pathlib.Path | None = None,
          memory_limit: str = '3GB') -> dict:
    root = pathlib.Path(root).resolve()
    traj = root / 'outputs/catalog-trajectory-all-4hour-2022-2026'
    manifest = json.loads((traj / 'manifest.json').read_text())
    validation = json.loads((traj / 'validation.json').read_text())
    lifecycle_audit = json.loads(
        (root / 'outputs/catalog-orbit-availability-audit.json').read_text())
    freshness_path = pathlib.Path(freshness_report or
        root / 'outputs/catalog-freshness-sensitivity-confirmed-2026-10-10.json').resolve()
    freshness = json.loads(freshness_path.read_text())
    if manifest.get('status') != 'completed' or validation.get('status') != 'validated_complete':
        raise RuntimeError('The reference catalog trajectory export is not independently validated')
    if (lifecycle_audit.get('status') != 'completed_valid'
            or lifecycle_audit.get('trajectory_signature') != manifest.get('signature')
            or lifecycle_audit.get('trajectory_validation_signature') != validation.get('signature')):
        raise RuntimeError('The SATCAT lifecycle report does not match the validated trajectory export')
    if freshness.get('status') != 'completed' or not freshness.get(
            'source_freshness_counts_match_validated_baseline'):
        raise RuntimeError('The raw-source freshness sensitivity report is incomplete or invalid')
    if (freshness.get('source_revision') != manifest.get('source_revision')
            or freshness.get('baseline_export_signature') != manifest.get('signature')
            or freshness.get('baseline_validation_signature') != validation.get('signature')
            or freshness.get('scheduled_rows') != manifest.get('projected_rows')
            or freshness.get('start_inclusive') != manifest.get('start')
            or freshness.get('end_exclusive') != manifest.get('end_exclusive')
            or freshness.get('step_seconds') != manifest.get('step_seconds')
            or freshness.get('object_count') != manifest.get('object_count')):
        raise RuntimeError('Freshness report does not match the validated source and grid')

    thresholds = {int(row['max_element_age_hours']): int(row['fresh_source_slots'])
                  for row in freshness['thresholds']}
    required_thresholds = (72, 168, 336, 720)
    if any(age not in thresholds for age in required_thresholds):
        raise RuntimeError(f'Freshness report lacks required thresholds {required_thresholds}')

    start = dt.datetime.fromisoformat(manifest['start'])
    end = dt.datetime.fromisoformat(manifest['end_exclusive'])
    step_seconds = int(manifest['step_seconds'])
    step_us = step_seconds * 1_000_000
    sample_count = math.ceil((end - start).total_seconds() / step_seconds)
    object_ids = catalog_object_ids(root, start, end, float(manifest['max_age_hours']))
    if len(object_ids) != int(manifest['object_count']):
        raise AssertionError('Current indexed object cohort differs from validated trajectory manifest')

    raw_glob = (root / 'data/raw/tle_*.parquet').as_posix()
    db = duckdb.connect()
    try:
        db.execute('SET threads=2')
        db.execute(f"SET memory_limit='{memory_limit}'")
        db.execute('SET preserve_insertion_order=false')
        db.execute("SET temp_directory='/tmp/godsat-element-gap-audit-duckdb'")
        first_rows = db.execute(
            f"SELECT norad_id, min(epoch) AS first_epoch FROM read_parquet('{raw_glob}') "
            "WHERE norad_id IN (SELECT unnest(?)) GROUP BY norad_id",
            [object_ids]).fetchall()
    finally:
        db.close()
    first_epoch = {int(oid): epoch for oid, epoch in first_rows}
    if set(first_epoch) != set(object_ids):
        raise AssertionError('Some trajectory objects have no element anywhere in the raw archive')

    no_prior_by_lifecycle = {
        'before_launch': 0, 'catalog_lifetime_estimate': 0,
        'after_decay': 0, 'lifecycle_unknown': 0,
    }
    satcat_path = root / 'data/raw/satcat.csv'
    satcat = {}
    with satcat_path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            try:
                oid = int(row['NORAD_CAT_ID'])
            except (TypeError, ValueError):
                raise AssertionError('SATCAT contains an invalid NORAD ID')
            if oid in satcat:
                raise AssertionError(f'SATCAT contains duplicate NORAD ID {oid}')
            satcat[oid] = row

    no_prior_ever = 0
    for oid in object_ids:
        first = first_epoch[oid]
        first_slot = grid_index(first, start, step_us, sample_count)
        no_prior_ever += first_slot
        row = satcat.get(oid)
        try:
            launch = dt.date.fromisoformat(row['LAUNCH_DATE'].strip()) if row else None
        except (TypeError, ValueError):
            launch = None
        try:
            decay = dt.date.fromisoformat(row['DECAY_DATE'].strip()) if row and row['DECAY_DATE'].strip() else None
        except (TypeError, ValueError):
            decay = None
        if launch is None:
            no_prior_by_lifecycle['lifecycle_unknown'] += first_slot
            continue
        launch_time = dt.datetime.combine(launch, dt.time(), tzinfo=dt.timezone.utc)
        launch_index = grid_index(launch_time, start, step_us, sample_count)
        no_prior_by_lifecycle['before_launch'] += max(0, min(first_slot, launch_index))
        life_end = end
        if decay is not None:
            life_end = dt.datetime.combine(decay + dt.timedelta(days=1), dt.time(),
                                           tzinfo=dt.timezone.utc)
        life_end_index = grid_index(life_end, start, step_us, sample_count)
        no_prior_by_lifecycle['catalog_lifetime_estimate'] += max(
            0, min(first_slot, life_end_index) - launch_index)
        if decay is not None:
            no_prior_by_lifecycle['after_decay'] += max(0, first_slot - life_end_index)

    totals = int(manifest['projected_rows'])
    source_fresh_72 = thresholds[72]
    validation_fresh = int(validation['successful']) + int(validation['sgp4_errors'])
    if source_fresh_72 != validation_fresh:
        raise AssertionError('Raw 72-hour source count differs from validated success plus SGP4 errors')
    if sum(no_prior_by_lifecycle.values()) != no_prior_ever:
        raise AssertionError('Lifecycle partitions do not reconcile for no-prior-element slots')
    if source_fresh_72 + no_prior_ever > totals:
        raise AssertionError('No-prior and fresh-source rows exceed the grid')

    age_bands = {
        'element_age_at_most_72h': source_fresh_72,
        'element_age_over_72h_through_7d': thresholds[168] - thresholds[72],
        'element_age_over_7d_through_14d': thresholds[336] - thresholds[168],
        'element_age_over_14d_through_30d': thresholds[720] - thresholds[336],
        'prior_element_older_than_30d': totals - no_prior_ever - thresholds[720],
        'no_prior_element_anywhere_in_archive': no_prior_ever,
    }
    if any(count < 0 for count in age_bands.values()):
        raise AssertionError('Derived raw-source age band has a negative count')
    if sum(age_bands.values()) != totals:
        raise AssertionError('Raw-source first-element and freshness age bands do not partition grid')
    rejected_72h = totals - source_fresh_72
    if rejected_72h != int(validation['stale_or_missing']):
        raise AssertionError('72-hour source gaps do not match export stale/missing row count')

    availability = lifecycle_audit['totals']
    lifetime_gaps = int(availability['lifetime_stale_or_missing_rows'])
    lifetime_no_prior = no_prior_by_lifecycle['catalog_lifetime_estimate']
    if lifetime_no_prior > lifetime_gaps:
        raise AssertionError('Estimated lifetime no-prior rows exceed all lifetime gaps')
    lifetime_prior_over_age = lifetime_gaps - lifetime_no_prior
    life_gap_partition = {
        'no_prior_element_anywhere_in_archive': lifetime_no_prior,
        'prior_archived_element_exists_but_no_source_within_72h': lifetime_prior_over_age,
    }
    if sum(life_gap_partition.values()) != lifetime_gaps:
        raise AssertionError('Estimated-lifetime source-gap causes do not reconcile')

    report = {
        'status': 'completed_valid',
        'audited_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'trajectory_signature': manifest['signature'],
        'validation_signature': validation['signature'],
        'source_revision': manifest['source_revision'],
        'freshness_report': str(freshness_path.relative_to(root)),
        'grid': {key: manifest[key] for key in (
            'start', 'end_exclusive', 'step_seconds', 'object_count', 'projected_rows',
            'max_age_hours')},
        'validated_export_status_totals': {
            'propagated': int(validation['successful']),
            'sgp4_error_within_72h_source_freshness': int(validation['sgp4_errors']),
            'stale_or_missing_beyond_72h_source_freshness': int(validation['stale_or_missing']),
        },
        'raw_source_age_band_totals': age_bands,
        'raw_source_age_band_method': (
            'Freshness counts are independently recomputed from deduplicated raw NORAD/epoch '
            'records on the exact four-hour grid. The first archived element epoch identifies '
            'samples with no earlier element anywhere in the available archive. All remaining '
            'slots are split using the validated 72h, 7d, 14d, and 30d source-freshness counts.'),
        'no_prior_element_by_catalog_lifecycle': no_prior_by_lifecycle,
        'all_lifetime_72h_gaps': lifetime_gaps,
        'lifetime_gap_cause_totals': life_gap_partition,
        'lifetime_gap_cause_fractions': {
            key: value / lifetime_gaps if lifetime_gaps else None
            for key, value in life_gap_partition.items()},
        'reconciliation': {
            'raw_72h_freshness_matches_export_success_plus_errors': source_fresh_72 == validation_fresh,
            'raw_source_age_bands_partition_full_grid': sum(age_bands.values()) == totals,
            'raw_72h_gaps_match_export_stale_or_missing': rejected_72h == int(validation['stale_or_missing']),
            'lifecycle_no_prior_counts_match_global_total': sum(no_prior_by_lifecycle.values()) == no_prior_ever,
            'lifetime_gap_causes_partition_lifetime_gaps': sum(life_gap_partition.values()) == lifetime_gaps,
        },
        'interpretation': (
            'A null element_epoch in a daily export part means no element was loaded within that '
            'part’s short lookback; it does not prove there is no earlier record in the complete '
            'archive. Only the raw-source first-epoch and freshness reconstruction supports the '
            'no-prior versus over-age split. Elements older than 72 hours remain sensitivity '
            'candidates, not validated trajectory states.'),
    }
    output = pathlib.Path(output or root / 'outputs/catalog-element-gap-audit.json').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + '.tmp')
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    temp.replace(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--output', type=pathlib.Path)
    parser.add_argument('--freshness-report', type=pathlib.Path)
    parser.add_argument('--memory-limit', default='3GB')
    args = parser.parse_args()
    report = audit(args.root, args.output, args.freshness_report, args.memory_limit)
    print(json.dumps({'status': report['status'],
                      'raw_source_age_band_totals': report['raw_source_age_band_totals'],
                      'lifetime_gap_cause_totals': report['lifetime_gap_cause_totals'],
                      'output': str(args.output or args.root / 'outputs/catalog-element-gap-audit.json')},
                     indent=2))


if __name__ == '__main__':
    main()
