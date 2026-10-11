"""Build the paper's current-payload cohort from the archived TLE records."""

import datetime as dt
import json
import os
import pathlib

import duckdb


ROOT = pathlib.Path(__file__).resolve().parents[1]
raw = ROOT / "data/raw"
sources = sorted(raw.glob("tle_*.parquet"))
catalog = raw / "satcat.csv"
if not sources or not catalog.exists():
    raise SystemExit("Data is missing. Run: python scripts/fetch_four_year_data.py")

output = ROOT / "data/current_payload_orbit_history.parquet"
temporary = output.with_suffix(".parquet.part")
connection = duckdb.connect()
try:
    connection.execute("SET TimeZone='UTC'")
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='1GB'")
    connection.read_parquet([str(path) for path in sources]).create_view("history")
    connection.read_csv(str(catalog), all_varchar=True).create_view("catalog")
    query = """
      SELECT h.* FROM history h
      JOIN catalog s ON h.norad_id=TRY_CAST(s.NORAD_CAT_ID AS BIGINT)
      WHERE s.OBJECT_TYPE='PAY'
        AND (s.DECAY_DATE IS NULL OR s.DECAY_DATE='')
        AND s.ORBIT_CENTER='EA'
        AND h.epoch >= TIMESTAMPTZ '2022-10-09'
        AND h.epoch < TIMESTAMPTZ '2026-10-10'
    """
    connection.sql(query).write_parquet(str(temporary), compression="zstd")
finally:
    connection.close()

os.replace(temporary, output)
record = {
    "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "output": str(output.relative_to(ROOT)),
    "output_bytes": output.stat().st_size,
    "archive_manifest": "data/raw/source-manifest.json",
    "archive_files": [path.name for path in sources],
    "satcat_snapshot": "data/raw/satcat-manifest.json",
    "cohort_rule": "Current SATCAT rows with OBJECT_TYPE=PAY, no decay date, and ORBIT_CENTER=EA; historical TLE epoch in [2022-10-09, 2026-10-10).",
    "interpretation": "A present-day catalog filter applied to historical orbit elements; it does not establish historical operational status.",
}
(ROOT / "data/current_payload_orbit_history.manifest.json").write_text(
    json.dumps(record, indent=2) + "\n"
)
print(f"Exported current payload orbit history ({output.stat().st_size / 1e9:.2f} GB)")
