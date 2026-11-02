"""Fetch the pinned four-year TLE archive and a dated CelesTrak SATCAT snapshot."""

from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data/raw/source-manifest.json"
SATCAT_URL = "https://celestrak.org/pub/satcat.csv"
USER_AGENT = "GodSatFactorial-data-fetch/1.0 (student research; pinned public archive)"


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, destination: pathlib.Path, *, expected_size: int | None = None,
          expected_sha256: str | None = None, force: bool = False) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        actual_size = destination.stat().st_size
        actual_hash = sha256_file(destination)
        if ((expected_size is None or actual_size == expected_size)
                and (expected_sha256 is None or actual_hash == expected_sha256)):
            return {"path": str(destination.relative_to(ROOT)), "bytes": actual_size,
                    "sha256": actual_hash, "cached": True}

    partial = destination.with_suffix(destination.suffix + ".part")
    if force:
        partial.unlink(missing_ok=True)
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=90)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not download {url}: {exc}") from exc

    with response:
        append = offset > 0 and response.status == 206
        if offset and not append:
            offset = 0
        mode = "ab" if append else "wb"
        received = offset
        with partial.open(mode) as output:
            while True:
                chunk = response.read(8 * 1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if received and received % (256 * 1024 * 1024) < len(chunk):
                    print(f"  {destination.name}: {received / 1e9:.2f} GB received", flush=True)

    actual_size = partial.stat().st_size
    actual_hash = sha256_file(partial)
    if expected_size is not None and actual_size != expected_size:
        raise RuntimeError(f"Size mismatch for {destination.name}: expected {expected_size}, got {actual_size}; "
                           f"partial file retained at {partial}")
    if expected_sha256 and actual_hash != expected_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {destination.name}: expected {expected_sha256}, got {actual_hash}; "
                           f"partial file retained at {partial}")
    os.replace(partial, destination)
    return {"path": str(destination.relative_to(ROOT)), "bytes": actual_size,
            "sha256": actual_hash, "cached": False}


def fetch_archive(manifest: dict, workers: int, force: bool) -> list[dict]:
    repository = manifest["repository"]
    revision = manifest["revision"]

    def one(source: dict) -> dict:
        source_path = source["path"]
        year = pathlib.PurePosixPath(source_path).stem.removeprefix("tle_")
        target = ROOT / "data/raw" / f"tle_{year}.parquet"
        url = (f"https://huggingface.co/datasets/{repository}/resolve/"
               f"{revision}/{urllib.parse.quote(source_path, safe='/')}?download=true")
        record = fetch(url, target, expected_size=source["lfs"]["size"],
                       expected_sha256=source["lfs"]["oid"], force=force)
        record["source_url"] = url
        print(f"{'Verified' if record['cached'] else 'Downloaded'} {target.name} "
              f"({record['bytes'] / 1e9:.3f} GB)", flush=True)
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, manifest["files"]))


def fetch_catalog(refresh: bool) -> dict:
    target = ROOT / "data/raw/satcat.csv"
    if target.exists() and not refresh:
        actual_hash = sha256_file(target)
        prior_path = ROOT / "data/raw/satcat-manifest.json"
        if prior_path.exists():
            prior = json.loads(prior_path.read_text())
            if prior.get("sha256") == actual_hash:
                record = prior
            else:
                record = {"path": str(target.relative_to(ROOT)), "bytes": target.stat().st_size,
                          "sha256": actual_hash, "source_url": SATCAT_URL,
                          "retrieved_utc": None,
                          "note": "Local SATCAT differs from its saved manifest; original retrieval time is unknown."}
        else:
            record = {"path": str(target.relative_to(ROOT)), "bytes": target.stat().st_size,
                      "sha256": actual_hash, "source_url": SATCAT_URL,
                      "retrieved_utc": None,
                      "note": "Existing local SATCAT has no retrieval manifest; original retrieval time is unknown."}
        print("Using existing SATCAT snapshot; pass --refresh-catalog to fetch a new one.", flush=True)
    else:
        record = fetch(SATCAT_URL, target, force=refresh)
        record.update({"source_url": SATCAT_URL,
                       "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        print(f"{'Verified' if record['cached'] else 'Downloaded'} SATCAT snapshot "
              f"({record['bytes'] / 1e6:.2f} MB)", flush=True)
    manifest_path = ROOT / "data/raw/satcat-manifest.json"
    manifest_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2,
                        help="parallel archive downloads (default: 2)")
    parser.add_argument("--force", action="store_true",
                        help="re-download even correctly verified archived files")
    parser.add_argument("--refresh-catalog", action="store_true",
                        help="replace the local SATCAT snapshot with the latest copy")
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    manifest = json.loads(MANIFEST_PATH.read_text())
    total = sum(item["lfs"]["size"] for item in manifest["files"])
    print(f"Pinned archive: {manifest['repository']}@{manifest['revision']} "
          f"({total / 1e9:.3f} GB across {len(manifest['files'])} files)", flush=True)
    # Publish a receipt only after every input has passed verification. The
    # pinned source manifest is an expectation, not proof of a local download.
    receipt_path = ROOT / "data/raw/manifest.json"
    receipt_path.unlink(missing_ok=True)
    files = fetch_archive(manifest, args.workers, args.force)
    catalog = fetch_catalog(args.refresh_catalog)
    receipt = {
        "status": "verified",
        "verified_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": manifest["repository"],
        "revision": manifest["revision"],
        "source_manifest_sha256": sha256_file(MANIFEST_PATH),
        "files": files,
        "catalog": catalog,
    }
    temporary = receipt_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.replace(receipt_path)
    print("Data fetch and checksum verification complete.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
