import csv
import json

from scripts import summarize_ilrs_multi_target


def test_multi_target_summary_combines_archives_observations_and_comparisons(tmp_path, monkeypatch):
    monkeypatch.setattr(summarize_ilrs_multi_target, "ROOT", tmp_path)
    for slug, (_, norad, _) in summarize_ilrs_multi_target.TARGETS.items():
        folder = tmp_path / f"data/ground_sensor/ilrs_{slug}_npt"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps({
            "status": "completed", "expected_calendar_days": 1462,
            "files_found": 1462, "files_missing_from_listing": 0,
            "files_with_errors": 0, "total_bytes": 100,
        }))
        (folder / "cpf_manifest.json").write_text(json.dumps({
            "status": "completed", "reference_resolution_status": "partial",
            "unique_crd_references": 5, "unique_exact_cpf_files_requested": 3,
            "cpf_files_downloaded_or_cached": 3, "covered_observation_rows": 4,
            "observation_rows_outside_cpf_interval": 1,
            "not_found_or_ambiguous_references": [{"reason": "unmatched"}],
            "download_errors": [],
        }))
        with (folder / "normal_points.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["station_name"])
            writer.writeheader()
            writer.writerows([{"station_name": "A"}, {"station_name": "B"}, {"station_name": "A"}])
        (folder / "orbit_model_comparison_summary.json").write_text(json.dumps({
            "status": "completed", "target_norad_id": norad,
            "compared_observations": 2, "excluded_observations": {},
            "historical_element_age_hours": {"median": 1},
            "sgp4_minus_cpf_position_separation_km": {"median": 0.2, "p95": 0.4},
            "output_csv": f"{slug}.csv",
        }))

    summary = summarize_ilrs_multi_target.build_summary()

    assert summary["status"] == "completed"
    assert len(summary["targets"]) == 4
    assert all(target["normal_point_count"] == 3 for target in summary["targets"])
    assert all(target["station_count"] == 2 for target in summary["targets"])
    assert all(target["cpf"]["unresolved_reference_count"] == 1 for target in summary["targets"])
    assert all(target["sgp4_vs_cpf"]["compared_observations"] == 2 for target in summary["targets"])
