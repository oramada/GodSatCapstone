#!/usr/bin/env python3
"""Stress-test dropout conclusions against assumed baseline detectability."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from godsat.dropout import quarterly_dates, run_dropout_study
from godsat.orbits import ROOT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/all-orbits-paper-exact-active-hosts-dropout5.json")
    parser.add_argument("--baseline-output", type=Path, default=ROOT / "outputs/all-orbits-paper-exact-active-hosts")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/four-year-quarterly-detection-sensitivity-v3-active-hosts")
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--probabilities", type=float, nargs="+", default=[0.50, 0.80, 0.98])
    parser.add_argument(
        "--interpretation-note",
        default=("The base detection probability is a synthetic stress-test input. "
                 "No catalog-wide empirical calibration is implied."),
        help="Provenance and scope note recorded in the generated JSON and report.",
    )
    args = parser.parse_args()
    if args.replicates < 1:
        parser.error("--replicates must be positive")
    if any(not 0 < p <= 1 for p in args.probabilities) or len(set(args.probabilities)) != len(args.probabilities):
        parser.error("--probabilities must be unique values in (0, 1]")

    base_config = json.loads(args.config.read_text())
    dates = quarterly_dates()
    model_seeds = [101, 211, 307, 401, 503]
    summaries = {}
    for probability in args.probabilities:
        config = {
            **base_config,
            "detection_probability": probability,
            "dropout_rates": [0.0, 0.2],
            "dropout_modes": ["independent", "burst"],
            "dropout_regimes": ["leo", "meo", "geo", "heo"],
            "dropout_dates": dates,
            "dropout_model_seeds": model_seeds,
        }
        label = f"pbase-{probability:.2f}"
        result = run_dropout_study(
            config,
            args.baseline_output,
            args.output / label,
            rates=[0.0, 0.2],
            replicates=args.replicates,
        )
        summaries[label] = {
            "detection_probability_base_assumption": probability,
            "design_signature": result["design_signature"],
            "status": result["status"],
            "dates": len(result["dates"]),
            "regimes": result["orbit_regimes"],
            "replicates_per_cell": result["replicates_per_date_regime_mode_rate"],
            "model_seeds": result["model_seeds"],
            "effects": {
                key: values.get("0.2")
                for key, values in result["paired_vs_zero_dropout"].items()
                if key.endswith(":custody_continuity")
            },
            "no_added_dropout_custody_by_regime": {
                regime: {
                    metric: result["metrics"][f"{regime}:independent:0"][metric]
                    for metric in ("custody_continuity", "observable_custody")
                }
                for regime in result["orbit_regimes"]
            },
            "note": args.interpretation_note,
        }
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "sensitivity_summary.json").write_text(
            json.dumps(
                {
                    "status": "in_progress",
                    "baseline_output": str(args.baseline_output),
                    "probability_levels": args.probabilities,
                    "dropout_rates": [0.0, 0.2],
                    "dropout_modes": ["independent", "burst"],
                    "dates": dates,
                    "replicates_per_date_regime_mode_rate": args.replicates,
                    "model_seeds": model_seeds,
                    "interpretation_note": args.interpretation_note,
                    "results": summaries,
                },
                indent=2,
            )
            + "\n"
        )
    effects_by_probability = {}
    for probability in args.probabilities:
        rows_path = args.output / f"pbase-{probability:.2f}" / "dropout_responses.csv"
        paired = {}
        with rows_path.open(newline="") as source:
            for row in csv.DictReader(source):
                key = (
                    row["date"], row["regime"], row["mode"], int(row["replicate"]),
                    int(row["model_seed"]),
                )
                rate = float(row["dropout_probability"])
                paired.setdefault(key, {})[rate] = float(row["custody_continuity"])
        daily = {}
        for (date, regime, mode, replicate, model_seed), values in paired.items():
            if 0.0 not in values or 0.2 not in values:
                raise ValueError(f"unpaired detection sensitivity row: {date} {regime} {mode} {replicate} {model_seed}")
            daily.setdefault((date, regime, mode), []).append(values[0.2] - values[0.0])
        effects_by_probability[probability] = {
            key: float(np.mean(values)) for key, values in daily.items()
        }

    interaction_contrasts = {}
    for lower_index, lower in enumerate(args.probabilities):
        for higher in args.probabilities[lower_index + 1 :]:
            for regime in ("leo", "meo", "geo", "heo"):
                for mode in ("independent", "burst"):
                    daily_differences = np.asarray([
                        effects_by_probability[lower][(date, regime, mode)]
                        - effects_by_probability[higher][(date, regime, mode)]
                        for date in dates
                    ])
                    n_dates = len(daily_differences)
                    half_width = (
                        float(student_t.ppf(0.975, n_dates - 1)
                              * daily_differences.std(ddof=1) / np.sqrt(n_dates))
                        if n_dates > 1 else None
                    )
                    interaction_contrasts[f"{regime}:{mode}:{lower:.4f}_minus_{higher:.4f}"] = {
                        "difference_in_paired_dropout_effect": float(daily_differences.mean()),
                        "date_clustered_ci95_half_width": half_width,
                        "n_dates": n_dates,
                    }
    (args.output / "sensitivity_summary.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "baseline_output": str(args.baseline_output),
                "probability_levels": args.probabilities,
                "dropout_rates": [0.0, 0.2],
                "dropout_modes": ["independent", "burst"],
                "dates": dates,
                "replicates_per_date_regime_mode_rate": args.replicates,
                "model_seeds": model_seeds,
                "interpretation_note": args.interpretation_note,
                "results": summaries,
                "paired_detection_probability_interactions": interaction_contrasts,
            },
            indent=2,
        )
        + "\n"
    )
    lines = [
        "# Dropout sensitivity to assumed sensor detectability",
        "",
        "This is a stress test of the existing simulated sensor model, not a calibration from observations. It holds the five DOE policy checkpoints, four historical orbit regimes, 17 quarterly dates, range/staleness penalties, and paired random streams fixed. It varies the base detection probability, then compares 0% with 20% independent or burst dropout. Each probability level contains 6,800 treatment rows (5 simulation replicates × 5 checkpoints per date/regime/mode/rate cell). Date-clustered 95% intervals use the 17 sampled dates as clusters.",
        "",
        args.interpretation_note,
        "The current configured default is 0.98. Broad values such as 0.50 and 0.80 are stress-test inputs. BUAA-MSOD provides cropped detection benchmark labels; Durham contains detections without complete nondetection opportunities; ILRS reports acquired returns; and DUST annotation gaps have unknown causes. None identifies catalog-wide acquisition probability.",
        "",
        "## No-added-dropout baseline and 20% burst effect",
        "",
        "Custody values are fractions; dropout effects are percentage points (pp), paired against the no-added-dropout condition at the same assumed detectability.",
        "",
        "| Base detection assumption | Regime | No-added-dropout custody (date mean ± 95% CI) | 20% burst dropout change (pp ± 95% CI) |",
        "|---:|:---|---:|---:|",
    ]
    for probability in args.probabilities:
        result = summaries[f"pbase-{probability:.2f}"]
        for regime in ("leo", "meo", "geo", "heo"):
            baseline = result["no_added_dropout_custody_by_regime"][regime]["custody_continuity"]
            burst = result["effects"][f"{regime}:burst:custody_continuity"]
            lines.append(
                f"| {probability:.4f} | {regime.upper()} | {baseline['date_clustered_mean']:.4f} ± {baseline['date_clustered_ci95_half_width']:.4f} | {100*burst['date_clustered_mean_change']:+.2f} ± {100*burst['date_clustered_ci95_half_width']:.2f} |"
            )
    probability_pairs = list(itertools.combinations(args.probabilities, 2))
    lines.extend([
        "",
        "## Paired change in the burst-dropout effect between base-probability assumptions",
        "",
        "Each contrast is the 20%-minus-0% dropout custody effect at the lower base probability minus the same effect at the higher probability. Intervals cluster by date.",
        "",
        "| Regime | " + " | ".join(f"{low:.4f} minus {high:.4f} (pp ± 95% CI)" for low, high in probability_pairs) + " |",
        "|:---|" + "---:|" * len(probability_pairs),
    ])
    for regime in ("leo", "meo", "geo", "heo"):
        cells = []
        for low, high in probability_pairs:
            value = interaction_contrasts[f"{regime}:burst:{low:.4f}_minus_{high:.4f}"]
            cells.append(
                f"{100*value['difference_in_paired_dropout_effect']:+.2f} ± {100*value['date_clustered_ci95_half_width']:.2f}"
            )
        lines.append(f"| {regime.upper()} | " + " | ".join(cells) + " |")
    lines.extend([
        "",
        "The modeled 20% burst intervention and the effect of changing detectability are outcomes of the synthetic environment and frozen policy; they do not estimate real sensor outage effectiveness.",
        "",
        f"Reproduce the run with `PYTHONPATH=. .venv/bin/python scripts/detection_assumption_sensitivity.py --config {args.config} --baseline-output {args.baseline_output} --output {args.output} --replicates {args.replicates} --probabilities {' '.join(map(str, args.probabilities))} --interpretation-note {json.dumps(args.interpretation_note)}`. Audit each probability-level directory with `PYTHONPATH=. .venv/bin/python scripts/audit_dropout_results.py --output {args.output / ('pbase-%.2f' % args.probabilities[0])}` (repeat for `{' '.join('pbase-%.2f' % p for p in args.probabilities)}; run `PYTHONPATH=. .venv/bin/python scripts/audit_detection_sensitivity.py --output {args.output}` to independently reproduce the paired effects and date-clustered intervals.",
    ])
    (args.output / "detection_assumption_sensitivity_report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": "completed", "output": str(args.output), "levels": list(summaries)}, indent=2))


if __name__ == "__main__":
    main()
