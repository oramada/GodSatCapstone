#!/usr/bin/env python3
"""Fetch public daily CASSIOPE/e-POP attitude quaternion files and audit them."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            # Missing products are evidence of archive coverage. Do not hide
            # them behind retries or confuse a temporary failure with absence.
            if error.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
        time.sleep(0.5 * 2 ** attempt)


def find_product(day: date, availability_directory: Path | None = None) -> str | None:
    url = day_url(day)
    probe = {"date_utc": day.isoformat(), "directory_url": url,
             "checked_utc": datetime.now(timezone.utc).isoformat()}

    def persist_probe(body=None):
        if availability_directory is None:
            return
        path = availability_directory / str(day.year) / f"{day.isoformat()}.json"
        if body is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            html_path = path.with_suffix('.html')
            temporary = html_path.with_suffix('.html.tmp')
            temporary.write_bytes(body); temporary.replace(html_path)
            probe["listing_sha256"] = hashlib.sha256(body).hexdigest()
        atomic_json(path, probe)

    try:
        body = read_url(url, timeout=30)
        html = body.decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            probe.update(http_status=404, products=[])
            persist_probe()
            return None
        raise
    matches = PRODUCT.findall(html)
    valid_listing = bool(re.search(r'<table\b', html, re.IGNORECASE))
    if not matches and not valid_listing:
        raise ValueError(f"Unrecognized publisher directory response for {day}; absence is unverified")
    probe.update(http_status=200, products=matches, recognized_directory_listing=valid_listing)
    persist_probe(body)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"Expected one CAS_AttQuat file for {day}, found {len(matches)}")
    href = matches[0]
    return href if href.startswith("http") else BASE + href


def read_known_product(day: date) -> tuple[str, bytes]:
    """Retrieve publisher-versioned products when the directory index fails.

    Exhausting these versions is an acquisition error, not evidence that the
    publisher has no product for this date. The CDF parser validates the bytes.
    """
    for version in ("2.0.2", "2.0.1", "2.0.0"):
        url = day_url(day) + f"CAS_AttQuat_{day:%Y%m%d}T000000_{day:%Y%m%d}T235959_{version}.cdf.zip"
        try:
            return url, read_url(url)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    raise FileNotFoundError(f"No CAS_AttQuat {day} product at known versions 2.0.2/2.0.1/2.0.0; directory availability is unverified")


def process_day(day: date, output: Path, keep_raw: bool = False,
                direct_products: bool = False) -> dict:
    ymd = day.isoformat()
    year = str(day.year)
    audit_path = output / "audits" / year / f"{ymd}.json"
    parquet_path = output / "processed" / year / f"{ymd}.parquet"
    if audit_path.exists() and parquet_path.exists():
        saved = json.loads(audit_path.read_text())
        if saved.get("status") == "validated" and saved.get("date_utc") == ymd:
            return {"date_utc": ymd, "status": "already_validated", "audit": saved}

    if direct_products:
        acquisition_method = "direct_known_product_versions"
        try:
            product_url, payload = read_known_product(day)
        except FileNotFoundError:
            product_url = find_product(day, output / "availability")
            if product_url is None:
                return {"date_utc": ymd, "status": "not_published"}
            payload = read_url(product_url)
            acquisition_method = "publisher_directory_after_known_version_miss"
    else:
        acquisition_method = "daily_directory_listing"
        product_url = find_product(day, output / "availability")
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
        "acquisition_method": acquisition_method,
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


def run(start: date, end: date, output: Path, workers: int, keep_raw: bool = False,
        direct_products: bool = False, retry_errors: bool = False) -> dict:
    if end <= start:
        raise ValueError("--end is exclusive and must be after --start")
    dates = [start + timedelta(days=i) for i in range((end - start).days)]
    output = output if output.is_absolute() else ROOT / output
    manifest_path = output / "manifest.json"
    statuses = {}
    failures = []
    if retry_errors:
        previous = json.loads(manifest_path.read_text())
        if (previous.get("requested_start_utc") != start.isoformat()
                or previous.get("requested_end_exclusive_utc") != end.isoformat()
                or previous.get("requested_days") != len(dates)):
            raise ValueError("Error-only retry requires the same requested date interval")
        statuses = {day: state for day, state in previous.get("per_day_status", {}).items()
                    if state in {"validated", "already_validated", "not_published"}}

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
            "acquisition_method": "direct_known_product_versions" if direct_products else "daily_directory_listing",
            "retry_errors_only": retry_errors,
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
        futures = {pool.submit(process_day, day, output, keep_raw, direct_products): day
                   for day in dates if day.isoformat() not in statuses}
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
    parser.add_argument("--direct-products", action="store_true", help="try publisher versions 2.0.2, 2.0.1, then 2.0.0 directly when directory indexes cannot be retrieved; failures remain errors, not unpublished dates")
    parser.add_argument("--retry-errors", action="store_true", help="retry unresolved dates from the same saved interval, retaining prior product and publisher-absence records")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    result = run(args.start, args.end, args.output, args.workers, args.keep_raw, args.direct_products, args.retry_errors)
    print(json.dumps({k: result[k] for k in ["status", "requested_days", "products_validated", "days_not_published"]}, indent=2))


if __name__ == "__main__":
    main()
