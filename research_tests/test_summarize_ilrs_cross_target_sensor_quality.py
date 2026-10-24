import json

from scripts import summarize_ilrs_cross_target_sensor_quality as summary_module


def test_cross_target_sensor_quality_summary_preserves_paired_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(summary_module, "ROOT", tmp_path)
    for slug, _ in summary_module.TARGETS.items():
        folder = tmp_path / f"data/ground_sensor/ilrs_{slug}_npt"
        folder.mkdir(parents=True)
        (folder / "station_geometry_summary.json").write_text(json.dumps({
            "status": "completed", "observed_station_sod_count": 4,
            "station_sods_with_dated_coordinate_solution": 3,
            "station_sods_with_dated_eccentricity": 3,
            "missing_coordinate_sods": ["missing"],
        }))
        (folder / "range_validation_summary.json").write_text(json.dumps({
            "status": "completed", "source_observations": 100,
            "range_residual_rows": 80, "unmatched_observation_counts": {"missing": 20},
            "robust_dhf_bias_corrected_residual_m_within_abs_100m": {
                "count": 79, "excluded_abs_over_100m": 1, "median_abs": 3.0,
                "mae": 4.0, "p95_abs": 8.0, "p99_abs": 12.0,
            },
            "output_csv": f"{slug}/range_validation.csv",
        }))
        (folder / "return_quality_analysis.json").write_text(json.dumps({
            "status": "completed", "validity": {"analyzed_rows": 70},
            "paired_station_day_low_vs_high_return": {
                "clusters": 10, "mean": 0.8, "ci95": [0.5, 1.1],
                "low_return_points": 20, "high_return_points": 20,
            },
            "inputs": {"normals.csv": {"sha256": "abc"}},
        }))

    summary = summary_module.build_summary()
    report = summary_module.render_report(summary)

    assert summary["status"] == "completed"
    assert len(summary["targets"]) == 4
    assert all(row["return_rate_quality_contrast"]["ci95_m"] == [0.5, 1.1]
               for row in summary["targets"])
    assert "not a missed-acquisition probability" in summary["interpretation"]
    assert "0.80 m [0.50, 1.10]" in report
