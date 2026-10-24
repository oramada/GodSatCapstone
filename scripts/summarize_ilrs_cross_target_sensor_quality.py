"""Aggregate measured ILRS return-rate versus CPF range-quality analyses."""
import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = {
    "lageos1": ("LAGEOS-1", "MEO"),
    "lageos2": ("LAGEOS-2", "MEO"),
    "lares": ("LARES", "LEO, high altitude"),
    "starlette": ("Starlette", "LEO"),
}


def build_summary():
    result = {
        "status": "completed",
        "estimand": "within-station-day difference in mean absolute CPF range residual: CRD return rate below 1 percent minus return rate at least 10 percent",
        "interpretation": "Observed sensor signal-quality association during acquired satellite laser-ranging passes. It is observational, conditions on recorded normal points, and is not a missed-acquisition probability or sensor dropout rate.",
        "targets": [],
    }
    for slug, (name, regime) in TARGETS.items():
        folder = ROOT / f"data/ground_sensor/ilrs_{slug}_npt"
        geometry = json.loads((folder / "station_geometry_summary.json").read_text())
        ranges = json.loads((folder / "range_validation_summary.json").read_text())
        quality = json.loads((folder / "return_quality_analysis.json").read_text())
        if any(item.get("status") != "completed" for item in (ranges, quality)):
            result["status"] = "partial"
        paired = quality["paired_station_day_low_vs_high_return"]
        robust = ranges["robust_dhf_bias_corrected_residual_m_within_abs_100m"]
        result["targets"].append({
            "target": name,
            "archive_slug": slug,
            "approximate_orbit_regime": regime,
            "normal_points": ranges["source_observations"],
            "cpf_range_validated_rows": ranges["range_residual_rows"],
            "unmatched_observation_counts": ranges["unmatched_observation_counts"],
            "station_geometry": {
                "station_occupations": geometry["observed_station_sod_count"],
                "dated_coordinates_matched": geometry["station_sods_with_dated_coordinate_solution"],
                "dated_eccentricities_matched": geometry["station_sods_with_dated_eccentricity"],
                "missing_coordinate_sods": geometry["missing_coordinate_sods"],
            },
            "range_residuals_within_100m_screen_m": {
                key: robust[key] for key in ["count", "excluded_abs_over_100m", "median_abs", "mae", "p95_abs", "p99_abs"]
            },
            "return_rate_quality_contrast": {
                "analyzed_normal_points": quality["validity"]["analyzed_rows"],
                "paired_station_days": paired["clusters"],
                "low_minus_high_mean_absolute_residual_m": paired["mean"],
                "ci95_m": paired["ci95"],
                "low_return_points": paired["low_return_points"],
                "high_return_points": paired["high_return_points"],
            },
            "input_sha256": quality["inputs"],
            "range_validation_output": ranges["output_csv"],
            "return_quality_output": str((folder / "return_quality_analysis.json").relative_to(ROOT)),
        })
    return result


def render_report(summary):
    lines = [
        "# ILRS cross-target measured sensor-quality analysis",
        "",
        summary["interpretation"],
        "",
        "All residuals use the exact CPF prediction named in each CRD record and the dated station geometry available locally. The operational CPF is a model-consistency reference, not independent orbit truth. Range summaries below the 100 m screen are descriptive; excluded larger residuals are retained in per-target summaries.",
        "",
        "| Target | Approx. regime | Matched range rows | Analyzed return-rate rows | Paired station-days | <1% minus >=10% mean absolute residual (95% CI) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for target in summary["targets"]:
        effect = target["return_rate_quality_contrast"]
        lo, hi = effect["ci95_m"]
        lines.append(
            f"| {target['target']} | {target['approximate_orbit_regime']} | {target['cpf_range_validated_rows']:,} | {effect['analyzed_normal_points']:,} | {effect['paired_station_days']:,} | {effect['low_minus_high_mean_absolute_residual_m']:.2f} m [{lo:.2f}, {hi:.2f}] |"
        )
    lines += [
        "",
        "A positive contrast means low-return bins have larger absolute range residuals than high-return bins within station-days containing both groups. The bootstrap gives equal weight to station-days and resamples those clusters; it does not control all pass-level confounding such as elevation, range, weather, or historical processing changes.",
        "",
        "CRD return rate is a signal-return percentage for recorded normal-point bins during acquired passes. No target's archive supplies planned passes, attempted acquisition intervals, or a no-acquisition status ledger. These results calibrate observed signal quality and cannot estimate missed-pass probability, natural hardware dropout, or GoDSAT custody effectiveness.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="outputs/ilrs-cross-target-sensor-quality/summary.json")
    parser.add_argument("--report", default="outputs/ilrs-cross-target-sensor-quality/report.md")
    args = parser.parse_args()
    summary = build_summary()
    json_path = (ROOT / args.json).resolve()
    report_path = (ROOT / args.report).resolve()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    report_path.write_text(render_report(summary))
    print(json.dumps({"status": summary["status"], "targets": len(summary["targets"]), "json": str(json_path.relative_to(ROOT)), "report": str(report_path.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
