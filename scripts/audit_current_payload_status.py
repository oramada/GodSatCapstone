"""Cross-check current payload cohorts against the archived four-year history.

The CelesTrak SATCAT decay-date cohort and operational-status cohort answer
different questions. This report keeps them separate and measures how many
objects have orbital-element records in the locally archived time window.
"""
import collections
import csv
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTIVE_CODES = {'+', 'P', 'B', 'S', 'X'}


def main():
    raw = ROOT / 'data/raw'
    coverage = json.loads((ROOT / 'data/coverage.json').read_text())
    with (raw / 'satcat.csv').open(newline='') as stream:
        catalog = {int(row['NORAD_CAT_ID']): row for row in csv.DictReader(stream)
                   if row.get('NORAD_CAT_ID', '').isdigit()}
    with (ROOT / 'data/history_coverage.csv').open(newline='') as stream:
        history = {int(row['norad_id']): {
            'records': int(row['records']),
            'first_epoch': row['first_epoch'],
            'last_epoch': row['last_epoch'],
        } for row in csv.DictReader(stream)}
    active_gp = json.loads((raw / 'current_active_gp.json').read_text())
    active_gp_ids = {int(row['NORAD_CAT_ID']) for row in active_gp
                     if row.get('NORAD_CAT_ID') is not None}

    earth_payloads = {oid: row for oid, row in catalog.items()
                      if row.get('OBJECT_TYPE') == 'PAY'
                      and row.get('ORBIT_CENTER') == 'EA'}
    no_decay = {oid for oid, row in earth_payloads.items()
                if not row.get('DECAY_DATE')}
    active_status = {oid for oid, row in earth_payloads.items()
                     if row.get('OPS_STATUS_CODE') in ACTIVE_CODES
                     and not row.get('DECAY_DATE')}

    def summarize(ids):
        present = ids & history.keys()
        statuses = collections.Counter(
            (catalog.get(oid, {}).get('OBJECT_TYPE') or 'unknown',
             catalog.get(oid, {}).get('OPS_STATUS_CODE') or 'blank')
            for oid in ids)
        return {
            'catalog_ids': len(ids),
            'with_history_in_requested_window': len(present),
            'history_records_in_requested_window': sum(
                history[oid]['records'] for oid in present),
            'object_type_and_ops_status_counts': {
                f'{object_type}:{status}': count
                for (object_type, status), count in sorted(statuses.items())},
        }

    result = {
        'status': 'completed',
        'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'requested_history_window': {
            'start_inclusive': coverage['requested_start'],
            'end_exclusive': coverage['requested_end_exclusive'],
        },
        'sources': {
            'catalog': 'data/raw/satcat.csv',
            'historical_elements': 'data/raw/tle_2022.parquet through tle_2026.parquet; summary from data/coverage.json',
            'current_gp_snapshot': 'data/raw/current_active_gp.json',
        },
        'definitions': {
            'no_decay_earth_payload': 'SATCAT OBJECT_TYPE=PAY and ORBIT_CENTER=EA with DECAY_DATE blank; this does not prove the object is currently operational or that the latest orbit is valid.',
            'active_status_payload': 'No-decay Earth payload whose SATCAT OPS_STATUS_CODE is one of +, P, B, S, X.',
            'current_gp_snapshot': 'IDs listed in the local CelesTrak active GP JSON snapshot; this is an orbital-element availability group, not proof of operational mission status.',
        },
        'cohorts': {
            'all_no_decay_earth_payloads': summarize(no_decay),
            'active_status_no_decay_earth_payloads': summarize(active_status),
            'current_gp_snapshot_ids': summarize(active_gp_ids),
            'current_gp_snapshot_intersection_with_no_decay_payloads': summarize(active_gp_ids & no_decay),
            'all_archived_objects': {
                'catalog_ids': coverage['history']['objects'],
                'history_records_in_requested_window': coverage['history']['records'],
            },
        },
        'limitations': [
            'SATCAT status and decay fields are a catalog snapshot and may be incomplete or revised.',
            'A current GP element does not establish that a satellite is operational; it establishes only that an element is in the downloaded group snapshot.',
            'The historical TLE mirror has uneven per-object coverage and ends at its last archived epoch.',
            'Debris and rocket bodies remain in the all-object history, but are not included in payload-only cohorts.',
        ],
    }
    output = ROOT / 'data/current_payload_status_audit.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
