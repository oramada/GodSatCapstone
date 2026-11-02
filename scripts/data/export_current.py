"""Build the paper's current-payload cohort from the archived TLE records."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import datetime as dt
import hashlib
import json
import os
import pathlib

import duckdb


def sha256_file(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


ROOT = pathlib.Path(__file__).resolve().parents[2]
raw = ROOT / "data/raw"
sources = sorted(raw.glob("tle_*.parquet"))
catalog = raw / "satcat.csv"
if not sources or not catalog.exists():
    raise SystemExit("Data is missing. Run: python scripts/data/fetch_four_year_data.py")

# Never silently export a partial history while other annual inputs are still
# downloading. Full checksum verification is performed by the fetch command.
expected = json.loads((raw / "source-manifest.json").read_text())
for item in expected["files"]:
    path = raw / pathlib.PurePosixPath(item["path"]).name
    if not path.is_file() or path.stat().st_size != item["lfs"]["size"]:
        raise SystemExit(f"Archive input missing or incomplete: {path.name}. "
                         "Run: python scripts/data/fetch_four_year_data.py")
sources = [raw / pathlib.PurePosixPath(item["path"]).name for item in expected["files"]]

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
    "output_sha256": sha256_file(output),
    "archive_manifest": "data/raw/source-manifest.json",
    "archive_manifest_sha256": sha256_file(raw / "source-manifest.json"),
    "archive_verification_receipt_sha256": (
        sha256_file(raw / "manifest.json") if (raw / "manifest.json").is_file() else None
    ),
    "archive_files": [path.name for path in sources],
    "satcat_snapshot": "data/raw/satcat-manifest.json",
    "satcat_csv_sha256": sha256_file(catalog),
    "cohort_rule": "Current SATCAT rows with OBJECT_TYPE=PAY, no decay date, and ORBIT_CENTER=EA; historical TLE epoch in [2022-10-09, 2026-10-10).",
    "interpretation": "A present-day catalog filter applied to historical orbit elements; it does not establish historical operational status.",
}
(ROOT / "data/current_payload_orbit_history.manifest.json").write_text(
    json.dumps(record, indent=2) + "\n"
)
print(f"Exported current payload orbit history ({output.stat().st_size / 1e9:.2f} GB)")
