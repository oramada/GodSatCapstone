"""Audit the four-hour all-catalog geometric opportunity census."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from godsat.dropout import monthly_dates
from godsat.orbits import EARTH_RADIUS
from godsat.scenario import cache_key

REGIMES = ("leo", "meo", "geo", "heo")
REGIME_BINS = REGIMES + ("other", "unknown")
SOURCE = ROOT / "outputs/catalog-trajectory-all-4hour-2022-2026"
HASH_CACHE: dict[Path, str] = {}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cached_digest(path: Path) -> str:
    if path not in HASH_CACHE:
        HASH_CACHE[path] = digest(path)
    return HASH_CACHE[path]


def los(origin: np.ndarray, targets: np.ndarray) -> np.ndarray:
    delta = targets - origin
    denom = np.sum(delta * delta, axis=1)
    fraction = np.clip(-np.sum(origin * delta, axis=1) / np.maximum(denom, 1e-12), 0, 1)
    closest = origin + fraction[:, None] * delta
    return np.linalg.norm(closest, axis=1) > EARTH_RADIUS + 20


def audit_part(source_part: dict, saved_path: Path, config: dict, recompute: bool) -> dict:
    saved = json.loads(saved_path.read_text())
    source = SOURCE / source_part["file"]
    if cached_digest(source) != source_part["sha256"]:
        raise ValueError(f"Physical source part checksum mismatch: {source_part['file']}")
    if saved.get("source_sha256") != source_part["sha256"]:
        raise ValueError(f"Saved source checksum mismatch: {source_part['file']}")
    if saved.get("source_rows") != source_part["rows"]:
        raise ValueError(f"Saved source row count mismatch: {source_part['file']}")
    if saved.get("sample_count") != source_part["samples_per_object"]:
        raise ValueError(f"Unexpected four-hour sample count: {source_part['file']}")
    expected_start = dt.datetime.fromisoformat(source_part["start_inclusive"])
    expected_stamps = [(expected_start + dt.timedelta(hours=4 * i)).isoformat()
                       for i in range(source_part["samples_per_object"])]
    if [row["time_utc"] for row in saved["samples"]] != expected_stamps:
        raise ValueError(f"Timestamp grid mismatch: {source_part['file']}")
    for sample in saved["samples"]:
        if sample["source_rows"] != source_part["objects"]:
            raise ValueError(f"Catalog row denominator mismatch at {sample['time_utc']}")
        if sample["fresh_valid_catalog_objects"] + sample["invalid_or_stale_rows"] != sample["source_rows"]:
            raise ValueError(f"Fresh/invalid partition mismatch at {sample['time_utc']}")
        if set(sample["host_regime_opportunities"]) != set(REGIMES):
            raise ValueError(f"Host regime set mismatch at {sample['time_utc']}")
        for regime in REGIMES:
            stamp_dt = dt.datetime.fromisoformat(sample["time_utc"])
            registered = [dt.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in monthly_dates()]
            anchor = min(registered, key=lambda candidate: abs((candidate - stamp_dt).total_seconds()))
            anchor_text = anchor.strftime("%Y-%m-%dT%H:%M:%SZ")
            expected_cache = ROOT / "data/scenarios" / f"{cache_key(anchor_text, config, regime)}.npz"
            expected_meta = expected_cache.with_suffix(".json")
            for suffix, path in ((regime, expected_cache), (f"{regime}_metadata", expected_meta)):
                if sample["host_scenario_hashes"].get(suffix) != cached_digest(path):
                    raise ValueError(f"Host scenario hash mismatch at {sample['time_utc']} {regime}")
            item = sample["host_regime_opportunities"][regime]
            counts = item["by_target_orbit_regime"]
            if set(counts) != set(REGIME_BINS):
                raise ValueError(f"Target regime bin mismatch at {sample['time_utc']} {regime}")
            if sum(counts.values()) != item["distinct_geometric_opportunities"]:
                raise ValueError(f"Orbit-bin sum mismatch at {sample['time_utc']} {regime}")
            if item["available_host_count"] + item["unavailable_selected_host_count"] != int(config["agents"]):
                raise ValueError(f"Host availability denominator mismatch at {sample['time_utc']} {regime}")
    if not recompute:
        return {"part": source_part["file"], "samples_structurally_checked": len(saved["samples"]),
                "source_rows": source_part["rows"], "source_sha256": source_part["sha256"],
                "output_sha256": digest(saved_path), "visibility_recomputed": 0}

    table = pq.read_table(source, columns=["norad_id", "time_utc", "orbit_regime", "sgp4_error",
        "element_age_hours", "x_teme_km", "y_teme_km", "z_teme_km"])
    col = table.to_pydict()
    times = np.asarray(col["time_utc"], dtype="U32")
    sample_index = len(saved["samples"]) // 2
    stamp = saved["samples"][sample_index]["time_utc"]
    mask = times == stamp
    ids = np.asarray(col["norad_id"], dtype=np.int64)[mask]
    positions = np.column_stack([np.asarray(col[key], dtype=np.float64)[mask]
        for key in ("x_teme_km", "y_teme_km", "z_teme_km")])
    orbit_regime = np.asarray(col["orbit_regime"], dtype="U8")[mask]
    age = np.asarray(col["element_age_hours"], dtype=np.float64)[mask]
    err = np.asarray(col["sgp4_error"], dtype=np.int16)[mask]
    altitude = np.linalg.norm(np.nan_to_num(positions), axis=1) - EARTH_RADIUS
    valid = ((err == 0) & np.isfinite(positions).all(axis=1) & np.isfinite(age)
             & (age <= float(config["max_element_age_hours"]))
             & (altitude > 150) & (altitude < 60_000))
    ids, positions, orbit_regime = ids[valid], positions[valid], orbit_regime[valid]
    if len(np.unique(ids)) != len(ids):
        raise ValueError(f"Duplicate catalog IDs at representative timestamp {stamp}")
    order = np.argsort(ids)
    ids, positions, orbit_regime = ids[order], positions[order], orbit_regime[order]
    sample_time = dt.datetime.fromisoformat(stamp)
    registered = [dt.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in monthly_dates()]
    anchor = min(registered, key=lambda candidate: abs((candidate - sample_time).total_seconds()))
    anchor_text = anchor.strftime("%Y-%m-%dT%H:%M:%SZ")
    for host_regime in REGIMES:
        path = ROOT / "data/scenarios" / f"{cache_key(anchor_text, config, host_regime)}.npz"
        meta = json.loads(path.with_suffix(".json").read_text())
        host_ids = np.asarray(meta["agents"], dtype=np.int64)
        indexes = np.searchsorted(ids, host_ids)
        in_range = indexes < len(ids)
        match = in_range.copy()
        match[in_range] = ids[indexes[in_range]] == host_ids[in_range]
        host_pos = positions[indexes[match]]
        visible_any = np.zeros(len(ids), dtype=bool)
        for sensor_pos in host_pos:
            delta = positions - sensor_pos
            ranges = np.linalg.norm(delta, axis=1)
            visible_any |= los(sensor_pos, positions) & (ranges > 1) & (ranges <= float(config["max_range_km"]))
        visible_any &= ~np.isin(ids, host_ids)
        computed_counts = {orbit: int(np.count_nonzero(visible_any & (orbit_regime == orbit)))
                           for orbit in REGIME_BINS}
        stored = saved["samples"][sample_index]["host_regime_opportunities"][host_regime]
        if computed_counts != stored["by_target_orbit_regime"]:
            raise ValueError(f"Independent visibility recomputation mismatch at {stamp} {host_regime}")
    return {"part": source_part["file"], "samples_structurally_checked": len(saved["samples"]),
            "source_rows": source_part["rows"], "source_sha256": source_part["sha256"],
            "output_sha256": digest(saved_path), "visibility_recomputed": 4,
            "recomputed_timestamp": stamp}


def audit(output: Path, representative_count: int = 12) -> dict:
    source_manifest = json.loads((SOURCE / "manifest.json").read_text())
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Census manifest.json is missing; run must complete first")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "completed":
        raise ValueError("Four-year census is not complete")
    if manifest.get("source_export_signature") != source_manifest.get("signature"):
        raise ValueError("Census source export signature mismatch")
    if manifest.get("part_count_complete") != len(source_manifest["parts"]):
        raise ValueError("Census daily part count is incomplete")
    if manifest.get("source_rows") != source_manifest["records_written"]:
        raise ValueError("Census source row total mismatch")
    campaign = ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json"
    config = json.loads(campaign.read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    step = max(1, len(source_manifest["parts"]) // max(1, representative_count))
    chosen = set(range(0, len(source_manifest["parts"]), step))
    if len(source_manifest["parts"]) - 1 not in chosen:
        chosen.add(len(source_manifest["parts"]) - 1)
    checks = []
    totals = {regime: {"opportunities": 0, "samples": 0, "hosts_available": 0,
                       "hosts_unavailable": 0,
                       "by_target_orbit_regime": {name: 0 for name in REGIME_BINS}}
              for regime in REGIMES}
    fresh_objects_sum = 0
    timestamp_count = 0
    timeseries_rows = []
    for index, source_part in enumerate(source_manifest["parts"]):
        name = f"{Path(source_part['file']).stem}-opportunities.json"
        path = output / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing daily census part {name}")
        checks.append(audit_part(source_part, path, config, index in chosen))
        daily = json.loads(path.read_text())
        for sample in daily["samples"]:
            timestamp_count += 1
            fresh_objects_sum += int(sample["fresh_valid_catalog_objects"])
            for regime in REGIMES:
                value = sample["host_regime_opportunities"][regime]
                timeseries_rows.append({
                    "time_utc": sample["time_utc"],
                    "fresh_valid_catalog_objects": sample["fresh_valid_catalog_objects"],
                    "host_regime": regime,
                    "distinct_geometric_opportunities": value["distinct_geometric_opportunities"],
                    "available_hosts": value["available_host_count"],
                    "unavailable_selected_hosts": value["unavailable_selected_host_count"],
                    **{f"targets_{name}": count for name, count in value["by_target_orbit_regime"].items()},
                })
                totals[regime]["samples"] += 1
                totals[regime]["opportunities"] += int(value["distinct_geometric_opportunities"])
                totals[regime]["hosts_available"] += int(value["available_host_count"])
                totals[regime]["hosts_unavailable"] += int(value["unavailable_selected_host_count"])
                for target_regime, count in value["by_target_orbit_regime"].items():
                    totals[regime]["by_target_orbit_regime"][target_regime] += int(count)
    regime_summary = {}
    for regime, value in totals.items():
        n = value["samples"]
        regime_summary[regime] = {
            "mean_geometrically_visible_targets_per_sample": value["opportunities"] / n,
            "mean_available_hosts_per_sample": value["hosts_available"] / n,
            "mean_unavailable_selected_hosts_per_sample": value["hosts_unavailable"] / n,
            "mean_visible_targets_by_target_orbit_per_sample": {
                name: count / n for name, count in value["by_target_orbit_regime"].items()},
        }
    report = {"status": "passed_structural_and_stratified_source_recomputation",
        "source_parts_checked": len(checks),
        "four_hour_samples_structurally_checked": sum(row["samples_structurally_checked"] for row in checks),
        "visibility_timeseries_rows": len(timeseries_rows),
        "source_row_denominators_checked": sum(row["source_rows"] for row in checks),
        "independent_visibility_recomputations": sum(row["visibility_recomputed"] for row in checks),
        "daily_artifact_checksums": checks,
        "catalog_sample_denominator_total": fresh_objects_sum,
        "mean_fresh_valid_catalog_objects_per_sample": fresh_objects_sum / timestamp_count,
        "host_regime_opportunity_summary": regime_summary,
        "representative_parts": [row for row in checks if row["visibility_recomputed"]],
        "source_export_signature": source_manifest["signature"],
        "limits": ["Daily checksums and source row totals are compared with the independently validated trajectory manifest.",
            "Visibility counts are independently recomputed at a stratified sample of dates; other daily metrics are structurally and arithmetically checked.",
            "A four-hour opportunity is geometric visibility, not a commanded attempt or a detected target."]}
    (output / "independent_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "census_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    csv_path = output / "four_hour_visibility_timeseries.csv"
    columns = ["time_utc", "fresh_valid_catalog_objects", "host_regime",
        "distinct_geometric_opportunities", "available_hosts", "unavailable_selected_hosts",
        *[f"targets_{name}" for name in REGIME_BINS]]
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(timeseries_rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/all-catalog-visibility-census-4hour-2022-2026")
    parser.add_argument("--representative-count", type=int, default=12)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = audit(output, args.representative_count)
    print(json.dumps({key: result[key] for key in ("status", "source_parts_checked",
        "four_hour_samples_structurally_checked", "independent_visibility_recomputations")}, indent=2))


if __name__ == "__main__":
    main()
