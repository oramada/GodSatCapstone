"""Summarize historical payload records and IDs by approximate orbit regime."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import csv
import pathlib
import duckdb

ROOT=pathlib.Path(__file__).resolve().parents[2]
SOURCE=ROOT/'data/current_payload_orbit_history.parquet'
OUTPUT=ROOT/'data/orbit_regime_coverage.csv'

QUERY="""
WITH elements AS (
 SELECT year(epoch) AS year, norad_id, eccentricity,
   power(398600.4418 / power(mean_motion * 2 * pi() / 86400, 2), 1.0/3.0) - 6378.135 AS sma_alt_km,
   power(398600.4418 / power(mean_motion * 2 * pi() / 86400, 2), 1.0/3.0) * (1 + eccentricity) - 6378.135 AS apogee_km
 FROM read_parquet(?) WHERE mean_motion > 0
), regimes AS (
 SELECT year, norad_id, CASE
   WHEN eccentricity >= 0.25 AND apogee_km > 2000 THEN 'heo'
   WHEN sma_alt_km BETWEEN 33786 AND 37786 AND eccentricity < 0.25 THEN 'geo'
   WHEN sma_alt_km >= 2000 AND sma_alt_km < 33786 THEN 'meo'
   WHEN sma_alt_km < 2000 AND apogee_km < 2000 THEN 'leo'
   ELSE 'other' END AS regime FROM elements
)
SELECT year, regime, count(*) AS element_records, count(DISTINCT norad_id) AS catalog_ids
FROM regimes GROUP BY year,regime ORDER BY year,regime
"""

def main():
    db=duckdb.connect()
    db.execute("SET TimeZone='UTC'");db.execute("SET threads=2");db.execute("SET memory_limit='1GB'")
    rows=db.execute(QUERY,[str(SOURCE)]).fetchall()
    with OUTPUT.open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['year','regime','element_records','catalog_ids']);writer.writerows(rows)
    print(f'Wrote {len(rows)} year/regime groups to {OUTPUT}')

if __name__=='__main__':main()
