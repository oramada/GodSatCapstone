import json
import shutil

from scripts.analysis.analyze_epop_dropout import analyze


def test_empirical_profile_uses_real_daily_series_and_one_minute_steps(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    data = tmp_path / "epop"
    source = root / "data/attitude/cassiope_epop/processed/2022/2022-10-09.parquet"
    target = data / "processed/2022/2022-10-09.parquet"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    (data / "manifest.json").write_text(json.dumps({
        "per_day_status": {"2022-10-09": "validated"}}))
    (data / "independent_audit.json").write_text(json.dumps({
        "status": "passed_structural_and_statistical", "downloaded_days": 1}))

    result = analyze(data, bootstrap_replicates=20)
    assert result["published_days_analyzed"] == 1
    assert result["one_minute_samples"] == 1440
    assert 0 <= result["one_minute_attitude_solution_dropout_rate"] <= 1
    assert sum(result["transition_counts_00_01_10_11"]) == 1439
    assert result["dropout_run_length_minutes"]["max"] > 0
    assert result["dropout_run_lengths_are_truncated_at_daily_file_boundaries"]
