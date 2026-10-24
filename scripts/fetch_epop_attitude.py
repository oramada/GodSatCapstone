#!/usr/bin/env python3
"""Fetch public daily CASSIOPE/e-POP attitude quaternion files and audit them."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from godsat.epop_attitude import write_attquat_product

BASE = "https://epop-data.phys.ucalgary.ca"
PRODUCT = re.compile(r'href=["\']([^"\']*/CAS_AttQuat_[^"\']+\.cdf\.zip)["\']')
SOURCE = "University of Calgary CASSIOPE/e-POP CAS_AttQuat daily definitive attitude product"
LOCK = threading.Lock()


def day_url(day: date) -> str:
    return f"{BASE}/{day:%Y/%m/%d}/"


def read_url(url: str, timeout: int = 90) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "GoDSAT research data acquisition"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def find_product(day: date) -> str | None:
    try:
        html = read_url(day_url(day), timeout=30).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    matches = PRODUCT.findall(html)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"Expected one CAS_AttQuat file for {day}, found {len(matches)}")
    href = matches[0]
    return href if href.startswith("http") else BASE + href


def process_day(day: date, output: Path, keep_raw: bool = False) -> dict:
    ymd = day.isoformat()
    year = str(day.year)
    audit_path = output / "audits" / year / f"{ymd}.json"
    parquet_path = output / "processed" / year / f"{ymd}.parquet"
    if audit_path.exists() and parquet_path.exists():
        saved = json.loads(audit_path.read_text())
        if saved.get("status") == "validated" and saved.get("date_utc") == ymd:
            return {"date_utc": ymd, "status": "already_validated", "audit": saved}

    product_url = find_product(day)
    if product_url is None:
        return {"date_utc": ymd, "status": "not_published"}

    payload = read_url(product_url)
    filename = product_url.rsplit("/", 1)[-1]
    raw_path = None
    if keep_raw:
        temp_dir = output / "raw" / year
        temp_dir.mkdir(parents=True, exist_ok=True)
        raw_path = temp_dir / filename
        tmp_raw = raw_path.with_suffix(raw_path.suffix + ".tmp")
        tmp_raw.write_bytes(payload)
        tmp_raw.replace(raw_path)
    parsed = write_attquat_product(payload, parquet_path, audit_path)
    parsed.update({
        "status": "validated",
        "date_utc": ymd,
        "source": SOURCE,
        "source_url": product_url,
        "source_zip_path": str(raw_path.relative_to(ROOT)) if raw_path else None,
        "source_zip_sha256": hashlib.sha256(payload).hexdigest(),
        "source_zip_bytes": len(payload),
        "parquet_path": str(parquet_path.relative_to(ROOT)),
    })
    audit_path.write_text(json.dumps(parsed, indent=2) + "\n")
    return {"date_utc": ymd, "status": "validated", "audit": parsed}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(start: date, end: date, output: Path, workers: int, keep_raw: bool = False) -> dict:
    if end <= start:
        raise ValueError("--end is exclusive and must be after --start")
    dates = [start + timedelta(days=i) for i in range((end - start).days)]
    output = output if output.is_absolute() else ROOT / output
    manifest_path = output / "manifest.json"
    statuses = {}
    failures = []

    def commit(item: dict) -> None:
        statuses[item["date_utc"]] = item["status"]
        if item["status"] == "error":
            failures.append(item)
        validated = [v for v in statuses.values() if v in {"validated", "already_validated"}]
        not_published = sorted(k for k, v in statuses.items() if v == "not_published")
        manifest = {
            "status": "running" if len(statuses) < len(dates) else ("completed_with_errors" if failures else "completed"),
            "source": SOURCE,
            "source_catalog_url": "https://epop-data.phys.ucalgary.ca/",
            "requested_start_utc": start.isoformat(),
            "requested_end_exclusive_utc": end.isoformat(),
            "requested_days": len(dates),
            "days_processed": len(statuses),
            "products_validated": len(validated),
            "days_not_published": len(not_published),
            "not_published_dates": not_published,
            "failures": failures,
            "per_day_status": statuses,
        }
        with LOCK:
            atomic_json(manifest_path, manifest)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_day, day, output, keep_raw): day for day in dates}
        for future in concurrent.futures.as_completed(futures):
            day = futures[future]
            try:
                item = future.result()
            except Exception as error:  # Keep the resume manifest even on a transient source failure.
                item = {"date_utc": day.isoformat(), "status": "error", "error": f"{type(error).__name__}: {error}"}
            commit(item)
            if len(statuses) % 25 == 0 or len(statuses) == len(dates):
                print(f"{len(statuses)}/{len(dates)} days processed; validated={sum(v in {'validated','already_validated'} for v in statuses.values())}; missing={sum(v == 'not_published' for v in statuses.values())}; errors={len(failures)}", flush=True)
    return json.loads(manifest_path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 10, 9))
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(timezone.utc).date(), help="Exclusive UTC date (default: today)")
    parser.add_argument("--output", type=Path, default=Path("data/attitude/cassiope_epop"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--keep-raw", action="store_true", help="retain original ZIP files as well as hashes and the public source URLs")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    result = run(args.start, args.end, args.output, args.workers, args.keep_raw)
    print(json.dumps({k: result[k] for k in ["status", "requested_days", "products_validated", "days_not_published"]}, indent=2))


if __name__ == "__main__":
    main()
