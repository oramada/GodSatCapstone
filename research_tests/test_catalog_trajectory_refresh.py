from scripts.audit_catalog_trajectory_refresh import audit


def test_latest_source_refresh_reconciles_to_four_year_catalog():
    result = audit()
    assert result["status"] == "passed_source_and_baseline_reconciliation"
    assert result["trajectory_rows_checked"] == 482_472
    assert result["independent_state_replays"] == 500
    assert result["comparison_to_pinned_archive"]["stale_to_fresh"] == 1_647
    assert result["comparison_to_pinned_archive"]["fresh_to_stale"] == 0
    assert result["maximum_position_difference_km"] == 0
    assert result["maximum_velocity_difference_km_s"] == 0
