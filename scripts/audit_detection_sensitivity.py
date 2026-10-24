#!/usr/bin/env python3
"""Independently reproduce paired dropout effects in a probability-sensitivity run."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


def close(actual: float, expected: float, label: str, tolerance: float = 1e-12) -> None:
    if not np.isclose(actual, expected, rtol=0.0, atol=tolerance):
        raise ValueError(f"{label}: stored {actual} does not match independently recomputed {expected}")


def audit(output: Path) -> dict:
    output = output.resolve()
    source = json.loads((output / "sensitivity_summary.json").read_text())
    if source.get("status") != "completed":
        raise ValueError("sensitivity_summary.json is not complete")
    probabilities = [float(value) for value in source["probability_levels"]]
    dates = list(source["dates"])
    if len({f"pbase-{value:.2f}" for value in probabilities}) != len(probabilities):
        raise ValueError("probability levels collide in their response-directory labels")

    effects_by_probability: dict[float, dict[tuple[str, str, str], float]] = {}
    checks = []
    for probability in probabilities:
        label = f"pbase-{probability:.2f}"
        folder = output / label
        study = json.loads((folder / "dropout_summary.json").read_text())
        if study.get("status") != "completed":
            raise ValueError(f"{label} dropout summary is incomplete")
        design = study["design"]
        study_dates = list(study["dates"])
        regimes = list(study["orbit_regimes"])
        modes = list(study["modes"])
        replicates = int(study["replicates_per_date_regime_mode_rate"])
        model_seeds = list(map(int, study["model_seeds"]))
        rates = set(map(float, study["rates"]))
        if study_dates != dates or rates != {0.0, 0.2}:
            raise ValueError(f"{label} date or outage-rate design differs from the sensitivity manifest")
        if not np.isclose(float(study["design"]["config"]["detection_probability"]), probability,
                          rtol=0.0, atol=1e-14):
            raise ValueError(f"{label} configuration does not contain its declared probability")

        paired: dict[tuple[str, str, str, int, int], dict[float, float]] = {}
        with (folder / "dropout_responses.csv").open(newline="") as stream:
            for row in csv.DictReader(stream):
                key = (row["date"], row["regime"], row["mode"],
                       int(row["replicate"]), int(row["model_seed"]))
                rate = float(row["dropout_probability"])
                value = float(row["custody_continuity"])
                if not np.isfinite(value) or rate in paired.setdefault(key, {}):
                    raise ValueError(f"duplicate pair or nonfinite custody in {label}: {key} {rate}")
                paired[key][rate] = value
        if len(paired) != len(dates) * len(regimes) * len(modes) * replicates * len(model_seeds):
            raise ValueError(f"{label} row count does not match its declared date/regime/mode/seed design")

        date_effects: dict[tuple[str, str, str], list[float]] = {}
        for (date, regime, mode, replicate, model_seed), values in paired.items():
            if set(values) != {0.0, 0.2}:
                raise ValueError(f"incomplete paired rates in {label}: {date} {regime} {mode} {replicate} {model_seed}")
            date_effects.setdefault((date, regime, mode), []).append(values[0.2] - values[0.0])

        effects_by_probability[probability] = {}
        for regime in regimes:
            for mode in modes:
                per_date = np.asarray([
                    np.mean(date_effects[(date, regime, mode)]) for date in dates
                ])
                all_pairs = np.asarray([
                    values[0.2] - values[0.0]
                    for (date, r, m, _replicate, _seed), values in paired.items()
                    if r == regime and m == mode
                ])
                key = f"{regime}:{mode}:custody_continuity"
                stored = study["paired_vs_zero_dropout"][key]["0.2"]
                close(float(stored["paired_mean_change"]), float(all_pairs.mean()), f"{label} {key} paired mean")
                pair_ci = float(student_t.ppf(.975, len(all_pairs)-1) * all_pairs.std(ddof=1) / np.sqrt(len(all_pairs)))
                close(float(stored["ci95_half_width"]), pair_ci, f"{label} {key} paired CI")
                close(float(stored["date_clustered_mean_change"]), float(per_date.mean()), f"{label} {key} date mean")
                date_ci = float(student_t.ppf(.975, len(per_date)-1) * per_date.std(ddof=1) / np.sqrt(len(per_date)))
                close(float(stored["date_clustered_ci95_half_width"]), date_ci, f"{label} {key} date CI")
                effects_by_probability[probability].update({
                    (date, regime, mode): float(value)
                    for date, value in zip(dates, per_date)
                })
                checks.append({"probability": probability, "regime": regime, "mode": mode,
                               "pairs": len(all_pairs), "date_clusters": len(per_date),
                               "paired_mean": float(all_pairs.mean()),
                               "date_clustered_mean": float(per_date.mean()),
                               "date_clustered_ci95_half_width": date_ci})

    interactions = {}
    for low, high in itertools.combinations(probabilities, 2):
        for regime in ("leo", "meo", "geo", "heo"):
            for mode in ("independent", "burst"):
                daily = np.asarray([
                    effects_by_probability[low][(date, regime, mode)]
                    - effects_by_probability[high][(date, regime, mode)]
                    for date in dates
                ])
                key = f"{regime}:{mode}:{low:.4f}_minus_{high:.4f}"
                stored = source["paired_detection_probability_interactions"][key]
                close(float(stored["difference_in_paired_dropout_effect"]), float(daily.mean()), f"{key} mean")
                ci = float(student_t.ppf(.975, len(daily)-1) * daily.std(ddof=1) / np.sqrt(len(daily)))
                close(float(stored["date_clustered_ci95_half_width"]), ci, f"{key} CI")
                interactions[key] = {"mean": float(daily.mean()), "ci95_half_width": ci,
                                     "n_dates": len(daily)}

    report = {
        "status": "completed_valid",
        "audited_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_summary": "sensitivity_summary.json",
        "probability_levels": probabilities,
        "date_clusters": len(dates),
        "independent_regime_mode_effect_checks": len(checks),
        "independent_interaction_checks": len(interactions),
        "checks": checks,
        "paired_detection_probability_interactions": interactions,
        "interpretation": source.get("interpretation_note"),
    }
    path = output / "independent_sensitivity_audit.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    temp.replace(path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "checks"}, indent=2))


if __name__ == "__main__":
    main()
