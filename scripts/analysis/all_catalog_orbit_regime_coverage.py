"""Count all archived orbital-element records and catalog IDs by year/regime."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import csv
import json
import pathlib

import duckdb


ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'data/raw/tle_*.parquet'
OUTPUT = ROOT / 'data/all_catalog_orbit_regime_coverage.csv'
JSON_OUTPUT = ROOT / 'data/all_catalog_orbit_regime_coverage.json'
START = '2022-10-09T00:00:00+00:00'
END = '2026-10-10T00:00:00+00:00'

QUERY = """
WITH elements AS (
 SELECT year(epoch) AS calendar_year, norad_id, eccentricity, mean_motion,
   power(398600.4418 / power(mean_motion * 2 * pi() / 86400, 2), 1.0/3.0)
     - 6378.135 AS sma_alt_km,
   power(398600.4418 / power(mean_motion * 2 * pi() / 86400, 2), 1.0/3.0)
     * (1 + eccentricity) - 6378.135 AS apogee_km
 FROM read_parquet(?)
 WHERE epoch >= ? AND epoch < ?
), classified AS (
 SELECT calendar_year, norad_id, CASE
   WHEN mean_motion <= 0 THEN 'unknown'
   WHEN eccentricity >= 0.25 AND apogee_km > 2000 THEN 'heo'
   WHEN sma_alt_km BETWEEN 33786 AND 37786 AND eccentricity < 0.25 THEN 'geo'
   WHEN sma_alt_km >= 2000 AND sma_alt_km < 33786 THEN 'meo'
   WHEN sma_alt_km < 2000 AND apogee_km < 2000 THEN 'leo'
   ELSE 'other'
 END AS regime FROM elements
)
SELECT calendar_year, regime, count(*) AS element_records,
       count(DISTINCT norad_id) AS catalog_ids
FROM classified
GROUP BY calendar_year, regime
ORDER BY calendar_year, regime
"""


def main():
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute('SET threads=2')
    db.execute("SET memory_limit='1GB'")
    rows = db.execute(QUERY, [str(SOURCE), START, END]).fetchall()
    expected = db.execute(
        'SELECT count(*) FROM read_parquet(?) WHERE epoch >= ? AND epoch < ?',
        [str(SOURCE), START, END]).fetchone()[0]
    db.close()
    if sum(int(row[2]) for row in rows) != expected:
        raise AssertionError('Orbit-regime bins do not cover every source record in the requested interval')

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['calendar_year', 'regime', 'element_records', 'catalog_ids'])
        writer.writerows(rows)
    report = {
        'status': 'completed',
        'source': 'data/raw/tle_*.parquet',
        'start_inclusive': START,
        'end_exclusive': END,
        'element_records_total': int(expected),
        'classification': 'Approximate mean-element altitude/eccentricity bins; not official catalog classes.',
        'records_by_year_and_regime': [
            {'calendar_year': int(year), 'regime': regime,
             'element_records': int(records), 'catalog_ids': int(catalog_ids)}
            for year, regime, records, catalog_ids in rows],
        'total_element_records_by_regime': {
            regime: sum(int(row[2]) for row in rows if row[1] == regime)
            for regime in sorted({row[1] for row in rows})},
        'limitations': [
            'A catalog ID may appear in multiple regime bins across years as its elements change.',
            'The archive contains payloads, debris, and rocket bodies; it is not a list of active satellites only.',
        ],
    }
    JSON_OUTPUT.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Wrote {len(rows)} year/regime groups to {OUTPUT} and {JSON_OUTPUT}')


if __name__ == '__main__':
    main()
