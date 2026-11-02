"""Resume the public DUST benchmark download using verified HTTP byte ranges."""
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
import pathlib
import threading
import urllib.request

URL = "https://zenodo.org/api/records/20255672/files/DUST.zip/content"
SIZE = 861_350_187
MD5 = "a31b62290eface15e519ed954124d59c"


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def download(path, workers=8, chunk_size=16 * 1024 * 1024):
    path = pathlib.Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = path.with_suffix(path.suffix + ".ranges.json")
    if progress_path.exists():
        progress = json.loads(progress_path.read_text())
        if progress.get("url") != URL or progress.get("size_bytes") != SIZE:
            raise ValueError("Progress file belongs to a different DUST archive")
    else:
        existing = path.stat().st_size if path.exists() else 0
        if existing > SIZE:
            raise ValueError(f"Existing file is larger than expected ({existing} > {SIZE})")
        progress = {"url": URL, "size_bytes": SIZE,
                    "prefix_bytes": existing, "completed_ranges": []}
        atomic_json(progress_path, progress)
    prefix = int(progress["prefix_bytes"])
    if prefix < 0 or prefix > SIZE:
        raise ValueError("Invalid saved prefix size")
    if not path.exists():
        path.touch()
    with path.open("r+b") as stream:
        stream.truncate(SIZE)
    completed = {tuple(map(int, item)) for item in progress.get("completed_ranges", [])}
    ranges = []
    start = prefix
    while start < SIZE:
        end = min(SIZE - 1, start + chunk_size - 1)
        if (start, end) not in completed:
            ranges.append((start, end))
        start = end + 1

    lock = threading.Lock()
    def fetch(block):
        start, end = block
        last_error = None
        for attempt in range(5):
            try:
                request = urllib.request.Request(URL, headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "GoDSAT-research-data-downloader/1.0"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 206:
                        raise IOError(f"Server returned HTTP {response.status}, expected 206")
                    expected_range = f"bytes {start}-{end}/{SIZE}"
                    if response.headers.get("Content-Range") != expected_range:
                        raise IOError(f"Unexpected Content-Range: {response.headers.get('Content-Range')}")
                    body = response.read(end - start + 2)
                if len(body) != end - start + 1:
                    raise IOError(f"Short range response: {len(body)} bytes for {start}-{end}")
                with path.open("r+b", buffering=0) as stream:
                    offset = 0
                    while offset < len(body):
                        written = os.pwrite(stream.fileno(), body[offset:], start + offset)
                        if written <= 0:
                            raise IOError("Could not write downloaded range")
                        offset += written
                with lock:
                    completed.add(block)
                    progress["completed_ranges"] = [list(item) for item in sorted(completed)]
                    atomic_json(progress_path, progress)
                return len(body)
            except Exception as error:
                last_error = error
        raise RuntimeError(f"Failed range {start}-{end} after retries: {last_error}")

    total = prefix
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, block): block for block in ranges}
        for future in concurrent.futures.as_completed(futures):
            total += future.result()
            print(f"downloaded or resumed {total:,}/{SIZE:,} bytes", flush=True)

    if path.stat().st_size != SIZE:
        raise IOError(f"Downloaded file size mismatch: {path.stat().st_size} != {SIZE}")
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != MD5:
        raise IOError(f"Zenodo MD5 mismatch: expected {MD5}, received {actual}")
    path.with_suffix(path.suffix + ".md5").write_text(actual + "\n")
    progress["verified_md5"] = actual
    progress["status"] = "completed"
    atomic_json(progress_path, progress)
    return {"status": "completed", "path": str(path), "size_bytes": SIZE, "md5": actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/ground_sensor/dust_star_tracker/DUST.zip")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-size-mib", type=int, default=16)
    args = parser.parse_args()
    if args.workers < 1 or args.chunk_size_mib < 1:
        parser.error("workers and chunk-size-mib must be positive")
    result = download(args.output, args.workers, args.chunk_size_mib * 1024 * 1024)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
