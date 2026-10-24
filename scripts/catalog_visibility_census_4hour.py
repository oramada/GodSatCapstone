"""Four-hour all-catalog geometric opportunity census from validated SGP4 parts.

This streams one daily Parquet part at a time. It measures whether each fresh,
valid catalog object is geometrically visible from the study's six hypothetical
hosts in each of four host-orbit regimes. It does not model task assignment,
attitude, weather, or detector success.
"""
from __future__ import annotations

import argparse
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

from godsat.scenario import cache_key, line_of_sight
from godsat.dropout import monthly_dates
from godsat.orbits import EARTH_RADIUS

REGIMES = ("leo", "meo", "geo", "heo")
REGIME_BINS = REGIMES + ("other", "unknown")
SOURCE = ROOT / "outputs/catalog-trajectory-all-4hour-2022-2026"
STUDY_CONFIG = ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json"
OUTAGE_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def available_host_positions(sorted_ids: np.ndarray, sorted_pos: np.ndarray,
                             selected_ids: list[int]) -> tuple[np.ndarray, int]:
    """Return only hosts with a fresh valid state; report unavailable count."""
    host_ids = np.asarray(selected_ids, dtype=np.int64)
    indexes = np.searchsorted(sorted_ids, host_ids)
    in_range = indexes < len(sorted_ids)
    matched = in_range.copy()
    matched[in_range] = sorted_ids[indexes[in_range]] == host_ids[in_range]
    return sorted_pos[indexes[matched]], int((~matched).sum())


def load_hosts(date: dt.datetime, config: dict) -> tuple[dict[str, list[int]], dict[str, str]]:
    # Assign each four-hour sample to the nearest registered monthly study
    # epoch. Positions themselves come from every four-hour sample.
    registered = [dt.datetime.fromisoformat(value.replace("Z", "+00:00")) for value in monthly_dates()]
    anchor_dt = min(registered, key=lambda candidate: abs((candidate - date).total_seconds()))
    anchor = anchor_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    hosts, hashes = {}, {}
    for regime in REGIMES:
        path = ROOT / "data/scenarios" / f"{cache_key(anchor, config, regime)}.npz"
        meta = path.with_suffix(".json")
        if not path.is_file() or not meta.is_file():
            raise FileNotFoundError(f"Missing registered monthly host scenario for {anchor} {regime}: {path}")
        data = json.loads(meta.read_text())
        ids = list(map(int, data.get("agents", [])))
        if len(ids) != int(config["agents"]) or len(set(ids)) != len(ids):
            raise ValueError(f"Invalid {regime} host list for {anchor}")
        hosts[regime] = ids
        hashes[regime] = sha256(path)
        hashes[f"{regime}_metadata"] = sha256(meta)
    return hosts, hashes


def day_result(part: Path, config: dict) -> dict:
    table = pq.read_table(part, columns=["norad_id", "time_utc", "orbit_regime", "sgp4_error",
        "element_age_hours", "x_teme_km", "y_teme_km", "z_teme_km"])
    columns = table.to_pydict()
    times = np.asarray(columns["time_utc"], dtype="U32")
    order = np.argsort(times, kind="stable")
    ids = np.asarray(columns["norad_id"], dtype=np.int64)[order]
    times = times[order]
    regimes = np.asarray(columns["orbit_regime"], dtype="U8")[order]
    errors = np.asarray(columns["sgp4_error"], dtype=np.int16)[order]
    age = np.asarray(columns["element_age_hours"], dtype=np.float64)[order]
    positions = np.column_stack([np.asarray(columns[key], dtype=np.float64)[order]
        for key in ("x_teme_km", "y_teme_km", "z_teme_km")])
    altitude = np.linalg.norm(np.nan_to_num(positions), axis=1) - EARTH_RADIUS
    valid = ((errors == 0) & np.isfinite(positions).all(axis=1) & np.isfinite(age)
             & (age <= float(config["max_element_age_hours"]))
             & (altitude > 150) & (altitude < 60_000))
    unique_times, starts = np.unique(times, return_index=True)
    groups = []
    source_coverage = {}
    for stamp, start in zip(unique_times, starts):
        end = int(np.searchsorted(times, stamp, side="right"))
        sl = slice(int(start), end)
        row_valid = valid[sl]
        day = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        hosts, host_hashes = load_hosts(day, config)
        sample_ids = ids[sl]
        sample_pos = positions[sl]
        sample_regime = regimes[sl]
        sample_valid_ids = sample_ids[row_valid]
        sample_valid_pos = sample_pos[row_valid]
        sample_valid_regime = sample_regime[row_valid]
        sorted_ids = sample_valid_ids
        id_order = np.argsort(sorted_ids)
        sorted_ids = sorted_ids[id_order]
        sorted_pos = sample_valid_pos[id_order]
        sorted_regime = sample_valid_regime[id_order]
        host_sets = {}
        missing_host_counts = {}
        for host_regime, host_ids in hosts.items():
            host_sets[host_regime], missing_host_counts[host_regime] = available_host_positions(
                sorted_ids, sorted_pos, host_ids)
        per_host_regime = {}
        for host_regime, host_pos in host_sets.items():
            visible_union = np.zeros(len(sorted_ids), dtype=bool)
            for one_host in host_pos:
                delta = sorted_pos - one_host
                ranges = np.linalg.norm(delta, axis=1)
                visible = line_of_sight(one_host, sorted_pos)
                visible &= (ranges > 1.0) & (ranges <= float(config["max_range_km"]))
                visible_union |= visible
            visible_union &= ~np.isin(sorted_ids, np.asarray(hosts[host_regime], dtype=np.int64))
            counts = {regime: int(np.count_nonzero(visible_union & (sorted_regime == regime)))
                      for regime in REGIME_BINS}
            per_host_regime[host_regime] = {
            "distinct_geometric_opportunities": int(visible_union.sum()),
                "available_host_count": int(len(host_pos)),
                "unavailable_selected_host_count": missing_host_counts[host_regime],
                "by_target_orbit_regime": counts,
            }
        groups.append({"time_utc": str(stamp), "fresh_valid_catalog_objects": int(len(sorted_ids)),
            "source_rows": int(end-start), "invalid_or_stale_rows": int((~row_valid).sum()),
            "host_regime_opportunities": per_host_regime,
            "host_scenario_hashes": host_hashes})
        source_coverage[str(stamp)] = {"rows": int(end-start), "fresh_valid": int(len(sorted_ids))}
    return {"date": part.name, "source_part": part.name, "source_sha256": sha256(part),
        "source_rows": table.num_rows, "sample_count": len(groups), "samples": groups}


def run(output: Path, selected_parts: list[int] | None = None) -> dict:
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    if manifest.get("status") != "completed" or manifest.get("step_seconds") != 14400:
        raise ValueError("Expected the completed validated four-hour catalog trajectory export")
    config = json.loads(STUDY_CONFIG.read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    output.mkdir(parents=True, exist_ok=True)
    parts = manifest["parts"]
    if selected_parts is not None:
        parts = [parts[index] for index in selected_parts]
    completed, reused = [], 0
    for part in parts:
        src = SOURCE / part["file"]
        dst = output / f"{Path(part['file']).stem}-opportunities.json"
        signature = {"source_sha256": part["sha256"], "study_config_sha256": sha256(STUDY_CONFIG),
                     "algorithm_version": OUTAGE_VERSION,
                     "host_cohort": "six DOE-selected current-active hosts per regime, nearest registered monthly study epoch",
                     "measurement": "four-hour sampled geometric visibility, TEME, 6000 km, Earth occultation"}
        if dst.is_file():
            cached = json.loads(dst.read_text())
            if cached.get("signature") == signature:
                completed.append(dst.name); reused += 1
                continue
        result = day_result(src, config)
        result["signature"] = signature
        temp = dst.with_suffix(".json.tmp")
        temp.write_text(json.dumps(result, separators=(",", ":")) + "\n")
        temp.replace(dst)
        completed.append(dst.name)
        print(f"{dst.name}: {result['sample_count']} samples; {result['source_rows']:,} rows", flush=True)
    report = {"status": "completed" if len(completed) == len(manifest["parts"]) else "partial",
        "study": "Four-year all-catalog geometric opportunity census sampled every four hours",
        "source_manifest_sha256": sha256(SOURCE / "manifest.json"),
        "source_export_signature": manifest["signature"],
        "object_count": manifest["object_count"], "source_rows": manifest["records_written"],
        "cadence_seconds": manifest["step_seconds"], "part_count_expected": len(manifest["parts"]),
        "part_count_included_this_run": len(parts), "part_count_complete": len(completed),
        "parts_reused": reused, "config_sha256": sha256(STUDY_CONFIG),
        "parts": completed,
        "limits": ["Four-hour samples can miss shorter visibility windows.",
            "Geometric opportunity is not a task assignment or successful observation.",
            "Study-selected current-active host IDs are backcast; historical operation is unverified.",
            "No weather, daylight, attitude, instrument schedule, or calibrated detection model is applied."]}
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/all-catalog-visibility-census-4hour-2022-2026")
    parser.add_argument("--parts", help="comma-separated source part indices; omit to process all parts")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    indexes = [int(item) for item in args.parts.split(",")] if args.parts else None
    result = run(output, indexes)
    print(json.dumps({key: result[key] for key in ("status", "part_count_included_this_run", "part_count_complete", "parts_reused")}, indent=2))


if __name__ == "__main__":
    main()
