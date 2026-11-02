"""Aggregate four-year ILRS/CPF model-comparison manifests for selected targets."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGETS = {
    "lageos1": ("LAGEOS-1", 8820, "MEO"),
    "lageos2": ("LAGEOS-2", 22195, "MEO"),
    "lares": ("LARES", 38077, "LEO, high altitude"),
    "starlette": ("Starlette", 7646, "LEO"),
}


def build_summary():
    result = {
        "status": "completed",
        "period_utc": {"start": "2022-10-09", "end_inclusive": "2026-10-09"},
        "comparison": "archived GP-element SGP4 transformed to ITRF versus CRD-referenced ILRS operational CPF positions",
        "interpretation": "Model-to-model diagnostic only; CPF is not independent truth. Results are target-specific and cover only rows meeting the comparison filters.",
        "targets": [],
    }
    for slug, (name, norad, regime) in TARGETS.items():
        folder = ROOT / f"data/ground_sensor/ilrs_{slug}_npt"
        raw = json.loads((folder / "manifest.json").read_text())
        cpf_path = folder / "cpf_manifest.json"
        comparison_path = folder / "orbit_model_comparison_summary.json"
        cpf = json.loads(cpf_path.read_text()) if cpf_path.exists() else None
        comparison = json.loads(comparison_path.read_text()) if comparison_path.exists() else None
        normal_points_path = folder / "normal_points.csv"
        normal_point_count = None
        stations = set()
        if normal_points_path.exists():
            with normal_points_path.open(newline="") as stream:
                for row in csv.DictReader(stream):
                    normal_point_count = (normal_point_count or 0) + 1
                    if row.get("station_name"):
                        stations.add(row["station_name"])
        if not comparison or comparison.get("status") != "completed":
            result["status"] = "partial"
        result["targets"].append({
            "target": name, "archive_slug": slug, "norad_id": norad,
            "approximate_regime": regime,
            "daily_archive": {key: raw.get(key) for key in ["status", "expected_calendar_days", "files_found", "files_missing_from_listing", "files_with_errors", "total_bytes"]},
            "normal_point_count": normal_point_count,
            "station_count": len(stations) if normal_point_count is not None else None,
            "cpf": ({key: cpf.get(key) for key in ["status", "reference_resolution_status", "unique_crd_references", "unique_exact_cpf_files_requested", "cpf_files_downloaded_or_cached", "covered_observation_rows", "observation_rows_outside_cpf_interval"]} | {"unresolved_reference_count": len(cpf.get("not_found_or_ambiguous_references", [])), "download_error_count": len(cpf.get("download_errors", []))}) if cpf else None,
            "sgp4_vs_cpf": ({
                "compared_observations": comparison.get("compared_observations"),
                "excluded_observations": comparison.get("excluded_observations"),
                "historical_element_age_hours": comparison.get("historical_element_age_hours"),
                "separation_km": comparison.get("sgp4_minus_cpf_position_separation_km"),
                "output_csv": comparison.get("output_csv"),
            } if comparison else None),
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/ilrs-multi-target-validation/summary.json")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = build_summary()
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"status": summary["status"], "targets": len(summary["targets"]), "output": str(output.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
