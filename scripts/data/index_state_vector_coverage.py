"""Build a per-object coverage index for the resumable all-catalog state export.

The index links the complete historical element inventory to whatever state
vector partitions are committed at run time. Its JSON sidecar records whether
the parquet count agreed with the exporter manifest during the scan.
"""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import datetime as dt
import json
import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[2]


def sql_string(value):
    """Quote a filesystem path as a DuckDB SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def build(root=ROOT, output=None):
    root = pathlib.Path(root).resolve()
    source = root / 'data/historical_state_vectors_all'
    manifest_path = source / 'manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(f'Missing exporter manifest: {manifest_path}')
    manifest_before = json.loads(manifest_path.read_text())
    parts_glob = str(source / 'year=*/part-*.parquet')
    if not list(source.glob('year=*/part-*.parquet')):
        raise FileNotFoundError(f'No committed state-vector partitions under {source}')

    output = pathlib.Path(output or root / 'data/state_vector_object_coverage.csv')
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + '.tmp')
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute('SET threads=2')
    db.execute("SET memory_limit='1GB'")
    parquet_sql = sql_string(parts_glob)
    history_sql = sql_string(root / 'data/history_coverage.csv')
    archive_sql = sql_string(root / 'data/raw/tle_*.parquet')
    start_sql = sql_string(manifest_before['start'])
    end_sql = sql_string(manifest_before['end_exclusive'])
    temp_sql = sql_string(temp)
    years = range(int(manifest_before['start'][:4]),
                  int(manifest_before['end_exclusive'][:4]) + 1)
    yearly_columns = []
    yearly_select = []
    for year in years:
        history_column = f'historical_element_rows_{year}'
        state_column = f'state_vector_rows_{year}'
        yearly_columns.extend([
            f'coalesce(y.{history_column}, 0) AS {history_column}',
            f'coalesce(y.{state_column}, 0) AS {state_column}',
        ])
        yearly_select.extend([
            f'sum(historical_rows) FILTER (WHERE calendar_year = {year}) AS {history_column}',
            f'sum(state_rows) FILTER (WHERE calendar_year = {year}) AS {state_column}',
        ])
    yearly_columns_sql = ',\n                '.join(yearly_columns)
    yearly_select_sql = ',\n                    '.join(yearly_select)
    try:
        db.execute(f'''COPY (
            WITH states AS (
                SELECT norad_id, count(*) AS state_vector_rows,
                    min(epoch) AS first_state_epoch,
                    max(epoch) AS last_state_epoch,
                    count(*) FILTER (WHERE sgp4_error = 0) AS successful_states,
                    count(*) FILTER (WHERE sgp4_error <> 0) AS failed_states
                FROM read_parquet({parquet_sql}) GROUP BY norad_id
            ), element_years AS (
                SELECT norad_id, year(epoch)::INTEGER AS calendar_year,
                    count(*) AS historical_rows
                FROM read_parquet({archive_sql})
                WHERE epoch >= CAST({start_sql} AS TIMESTAMPTZ)
                  AND epoch < CAST({end_sql} AS TIMESTAMPTZ)
                GROUP BY norad_id, calendar_year
            ), state_years AS (
                SELECT norad_id, year(epoch)::INTEGER AS calendar_year,
                    count(*) AS state_rows
                FROM read_parquet({parquet_sql}) GROUP BY norad_id, calendar_year
            ), yearly_counts AS (
                SELECT norad_id, {yearly_select_sql}
                FROM (
                    SELECT coalesce(h.norad_id, s.norad_id) AS norad_id,
                        coalesce(h.calendar_year, s.calendar_year) AS calendar_year,
                        coalesce(h.historical_rows, 0) AS historical_rows,
                        coalesce(s.state_rows, 0) AS state_rows
                    FROM element_years h FULL OUTER JOIN state_years s
                        USING (norad_id, calendar_year)
                ) yearly GROUP BY norad_id
            )
            SELECT h.norad_id,
                h.records AS historical_element_rows,
                h.first_epoch AS first_element_epoch,
                h.last_epoch AS last_element_epoch,
                coalesce(s.state_vector_rows, 0) AS state_vector_rows,
                s.first_state_epoch, s.last_state_epoch,
                coalesce(s.successful_states, 0) AS successful_states,
                coalesce(s.failed_states, 0) AS failed_states,
                CASE WHEN h.records > 0
                    THEN coalesce(s.state_vector_rows, 0)::DOUBLE / h.records
                    ELSE NULL END AS materialized_fraction,
                {yearly_columns_sql}
            FROM read_csv_auto({history_sql}) h
            LEFT JOIN states s USING (norad_id)
            LEFT JOIN yearly_counts y USING (norad_id)
            ORDER BY h.norad_id
        ) TO {temp_sql} (FORMAT CSV, HEADER, DELIMITER ',')''')
        parquet_rows = db.execute(f'SELECT count(*) FROM read_parquet({parquet_sql})').fetchone()[0]
        temp_csv_sql = sql_string(temp)
        object_count = db.execute(f'SELECT count(*) FROM read_csv_auto({temp_csv_sql})').fetchone()[0]
        totals = db.execute(f'''SELECT
            coalesce(sum(historical_element_rows),0),
            coalesce(sum(state_vector_rows),0),
            coalesce(sum(successful_states),0),
            coalesce(sum(failed_states),0),
            count(*) FILTER (WHERE state_vector_rows > 0),
            count(*) FILTER (WHERE state_vector_rows = historical_element_rows),
            count(*) FILTER (WHERE state_vector_rows = 0)
            FROM read_csv_auto({temp_csv_sql})''').fetchone()
        (historical_rows, indexed_rows, successful_rows, failed_rows,
         objects_with_states, fully_materialized_objects,
         objects_without_states) = totals
    finally:
        db.close()
    temp.replace(output)

    manifest_after = json.loads(manifest_path.read_text())
    stable_signature = manifest_before.get('signature') == manifest_after.get('signature')
    matches = stable_signature and parquet_rows == manifest_after.get('records_written') == indexed_rows
    summary = {
        'status': 'completed' if matches else 'snapshot_mismatch',
        'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'cohort': manifest_after.get('cohort'),
        'export_status': manifest_after.get('status'),
        'export_signature': manifest_after.get('signature'),
        'manifest_records_written': manifest_after.get('records_written'),
        'parquet_records_scanned': parquet_rows,
        'indexed_state_rows': indexed_rows,
        'historical_element_rows_indexed': historical_rows,
        'successful_state_rows': successful_rows,
        'failed_state_rows': failed_rows,
        'historical_objects_indexed': object_count,
        'objects_with_any_states': objects_with_states,
        'objects_with_all_historical_states': fully_materialized_objects,
        'objects_without_materialized_states': objects_without_states,
        'yearly_source_state_count_columns': [
            {'year': year,
             'historical_rows': f'historical_element_rows_{year}',
             'state_rows': f'state_vector_rows_{year}',
             'export_complete': bool(manifest_after.get('years', {}).get(str(year), {}).get('complete', False))}
            for year in years],
        'index_csv': str(output.relative_to(root) if output.is_relative_to(root) else output),
        'snapshot_matches_manifest': matches,
        'model': manifest_after.get('model'),
        'frame': manifest_after.get('frame'),
        'limitations': [
            'The index describes reconstructed states at source element epochs, not fixed-cadence continuous trajectories.',
            'During an active export, rerun if snapshot_matches_manifest is false.',
            'Unmaterialized objects or intervals remain represented by their historical element coverage only.',
        ],
    }
    sidecar = output.with_suffix('.json')
    sidecar.write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--output')
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output), indent=2))


if __name__ == '__main__':
    main()
