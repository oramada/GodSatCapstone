"""Reconcile the GoDSAT study's major datasets and independently audited outputs.

This is an evidence index, not a rerun of the multi-day experiments. It verifies
that the persisted component audits agree and reports the boundaries that keep
the replacement system from being a literal GoDSAT reproduction.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        raise FileNotFoundError(f"Required evidence file is missing: {relative}")
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(recompute_dust_source: bool = True) -> dict[str, Any]:
    trajectory = load_json("outputs/catalog-trajectory-all-4hour-2022-2026/manifest.json")
    trajectory_audit = load_json("outputs/catalog-trajectory-all-4hour-2022-2026/validation.json")
    from scripts.audit_catalog_trajectory_refresh import audit as audit_trajectory_refresh
    trajectory_refresh = audit_trajectory_refresh()
    element_selection = load_json(
        "outputs/catalog-trajectory-all-4hour-2022-2026/source-element-selection-audit.json")
    source_epoch_manifest = load_json("data/historical_state_vectors_all/manifest.json")
    source_epoch_validation = load_json("data/historical_state_vectors_all/validation.json")
    source_epoch_repair = load_json("data/historical_state_vectors_all/repair_audit.json")
    current_snapshot = load_json("data/current_active_catalog_snapshot_2026-10-10/manifest.json")
    current_snapshot_audit = load_json("data/current_active_catalog_snapshot_2026-10-10/independent_audit.json")
    current_active = load_json("data/current_active_payload_orbit_history.parquet.manifest.json")
    campaign = load_json("outputs/all-orbits-paper-exact-active-hosts/campaign_integrity_audit.json")
    center_replication = load_json(
        "outputs/all-orbits-active-hosts-center-replication/replication_integrity_audit.json")
    center_replication_validation = load_json(
        "outputs/all-orbits-active-hosts-center-replication/independent_validation.json")
    center_replication_surfaces = load_json(
        "outputs/all-orbits-active-hosts-center-replication/response_surfaces_augmented.json")
    awp = load_json("outputs/awp-policy-monthly-validation-2022-2026/independent_audit.json")
    awp_proxy_summary = load_json(
        "outputs/awp-policy-monthly-dust-persistence-time-scaled-2022-2026/summary.json")
    awp_proxy = load_json(
        "outputs/awp-policy-monthly-dust-persistence-time-scaled-2022-2026/independent_audit.json")
    from godsat.environment import rescale_markov_persistence
    # Use the cadence-scaled reruns as the authoritative Durham sensitivity.
    # Earlier results applied an ~8.8 s catalogue-frame persistence directly
    # to a 60 s simulation tick and therefore overstated burst duration.
    durham_awp_summary = load_json(
        "outputs/awp-policy-monthly-durham-gap-time-scaled-2022-2026/summary.json")
    durham_awp_audit = load_json(
        "outputs/awp-policy-monthly-durham-gap-time-scaled-2022-2026/independent_audit.json")
    durham_awp_rate_ci = {}
    for label in ("low", "high"):
        root = f"outputs/awp-policy-monthly-durham-gap-time-scaled-ci-{label}-2022-2026"
        durham_awp_rate_ci[label] = (
            load_json(f"{root}/summary.json"),
            load_json(f"{root}/independent_audit.json"))
    dropout = load_json("outputs/four-year-monthly-dropout-v1-multiseed/dropout_integrity_audit.json")
    visibility = load_json("outputs/all-catalog-visibility-census-2022-2026/summary.json")
    visibility_audit = load_json("outputs/all-catalog-visibility-census-2022-2026/independent_audit.json")
    full_catalog_tasking = load_json("outputs/full-catalog-tasking-monthly-2022-2026/summary.json")
    full_catalog_tasking_audit = load_json("outputs/full-catalog-tasking-monthly-2022-2026/independent_audit.json")
    full_catalog_weekly_tasking = load_json(
        "outputs/full-catalog-tasking-weekly-2022-2026/summary.json")
    full_catalog_weekly_tasking_audit = load_json(
        "outputs/full-catalog-tasking-weekly-2022-2026/independent_audit.json")
    active_payload_tasking = load_json("outputs/current-active-payload-tasking-monthly-2022-2026/summary.json")
    active_payload_tasking_audit = load_json("outputs/current-active-payload-tasking-monthly-2022-2026/independent_audit.json")
    full_catalog_seed_sensitivity = load_json(
        "outputs/full-catalog-tasking-seed-sensitivity-2022-2026/seed_sensitivity.json")
    full_catalog_seed_audit = load_json(
        "outputs/full-catalog-tasking-seed-sensitivity-2022-2026/independent_audit.json")
    capacity = load_json("outputs/full-catalog-capacity-sensitivity-quarterly-2022-2026/summary.json")
    capacity_audit = load_json("outputs/full-catalog-capacity-sensitivity-quarterly-2022-2026/independent_audit.json")
    capacity_monthly = load_json("outputs/full-catalog-capacity-sensitivity-monthly-2022-2026/summary.json")
    capacity_monthly_audit = load_json("outputs/full-catalog-capacity-sensitivity-monthly-2022-2026/independent_audit.json")
    dust = load_json("data/onboard_sensor/dust_star_tracker/dropout_study/frame_dropout_integrity_audit.json")
    dust_image = load_json("data/onboard_sensor/dust_star_tracker/dropout_study/internal_gap_image_signal_audit.json")
    dust_gap_interpolation = load_json(
        "data/onboard_sensor/dust_star_tracker/dropout_study/gap_interpolation_cross_validation.json")
    dust_cadence = load_json("data/onboard_sensor/dust_star_tracker/dropout_study/capture_cadence_audit.json")
    dust_cadence_custody = load_json(
        "data/onboard_sensor/dust_star_tracker/dropout_study/capture_cadence_custody.json")
    dust_cadence_custody_audit = load_json(
        "data/onboard_sensor/dust_star_tracker/dropout_study/capture_cadence_custody_audit.json")
    sentinel_access = load_json("data/attitude/sentinel_quaternions/access_audit.json")
    epop_attitude_manifest = load_json("data/attitude/cassiope_epop/manifest.json")
    epop_attitude_audit = load_json("data/attitude/cassiope_epop/independent_audit.json")
    epop_dropout_profile = load_json("data/attitude/cassiope_epop/dropout_profile_1minute.json")
    epop_solution_quality = load_json("data/attitude/cassiope_epop/solution_quality_1minute.json")
    epop_dropout_masks = load_json("data/attitude/cassiope_epop/dropout_masks_1minute.json")
    epop_dropout_masks_audit = load_json("data/attitude/cassiope_epop/dropout_masks_independent_audit.json")
    require(epop_attitude_audit.get("status") == "passed_structural_and_statistical"
            and epop_attitude_audit.get("failures") == []
            and epop_attitude_audit.get("downloaded_days", 0) > 0
            and epop_attitude_audit.get("totals", {}).get("samples")
                == epop_attitude_audit.get("downloaded_days", 0) * 86400
            and epop_attitude_manifest.get("days_processed", 0)
                >= epop_attitude_audit.get("manifest_days_processed_at_audit", 0),
            "CASSIOPE attitude telemetry is missing or its independent audit failed")
    epop_profile_dates = {row.get("date") for row in epop_dropout_profile.get("per_day", [])}
    require(epop_dropout_profile.get("status") == "completed"
            and epop_dropout_profile.get("source_audit_status") == epop_attitude_audit.get("status")
            and len(epop_profile_dates) == epop_dropout_profile.get("published_days_analyzed")
            and epop_profile_dates.issubset(set(epop_attitude_audit.get("validated_dates", [])))
            and epop_dropout_profile.get("one_minute_samples") == len(epop_profile_dates) * 1440
            and 0 <= epop_dropout_profile.get("one_minute_attitude_solution_dropout_rate", -1) < 1
            and 0 <= epop_dropout_profile.get("simulator_markov_persistence_parameter", -1) < 1,
            "CASSIOPE empirical one-minute dropout profile is incomplete or stale against audited data")
    quality_counts = epop_solution_quality.get("quality_class_counts", {})
    require(epop_solution_quality.get("status") == "completed"
            and epop_solution_quality.get("source_audit_status") == epop_attitude_audit.get("status")
            and epop_solution_quality.get("sampled_days") == epop_attitude_audit.get("downloaded_days")
            and epop_solution_quality.get("sampled_minutes") == epop_dropout_profile.get("one_minute_samples")
            and sum(quality_counts.values()) == epop_solution_quality.get("sampled_minutes")
            and epop_solution_quality.get("source_profile_sha256")
                == sha256_file(ROOT / "data/attitude/cassiope_epop/dropout_profile_1minute.json"),
            "CASSIOPE minute-level attitude source-quality analysis is incomplete or stale")
    mask_archive = ROOT / epop_dropout_masks.get("mask_archive_path", "")
    require(epop_dropout_masks.get("status") == "completed"
            and epop_dropout_masks_audit.get("status") == "passed_independent_source_replay"
            and epop_dropout_masks.get("source_profile_sha256")
                == sha256_file(ROOT / "data/attitude/cassiope_epop/dropout_profile_1minute.json")
            and epop_dropout_masks.get("mask_archive_sha256") == sha256_file(mask_archive)
            and epop_dropout_masks_audit.get("mask_archive_sha256") == epop_dropout_masks.get("mask_archive_sha256")
            and epop_dropout_masks_audit.get("source_profile_sha256") == epop_dropout_masks.get("source_profile_sha256")
            and epop_dropout_masks_audit.get("sample_count_checked") == epop_dropout_profile.get("one_minute_samples")
            and epop_dropout_masks_audit.get("mismatched_samples") == 0,
            "CASSIOPE compact empirical dropout masks or independent source audit are incomplete")
    epop_profile_tasking_path = Path(
        "outputs/full-catalog-tasking-epop-profile-weekly-2022-2026")
    epop_profile_tasking = None
    epop_profile_tasking_audit = None
    if ((epop_profile_tasking_path / "summary.json").exists()
            and (epop_profile_tasking_path / "independent_audit.json").exists()):
        epop_profile_tasking = load_json(str(epop_profile_tasking_path / "summary.json"))
        epop_profile_tasking_audit = load_json(
            str(epop_profile_tasking_path / "independent_audit.json"))
        require(epop_profile_tasking.get("status") == "completed"
                and epop_profile_tasking.get("completed_date_regime_groups") == 832
                and len(epop_profile_tasking.get("rows", [])) == 1664
                and epop_profile_tasking_audit.get("status") == "passed_structural_and_statistical"
                and epop_profile_tasking_audit.get("dates_checked") == 208
                and epop_profile_tasking_audit.get("paired_date_regime_cells_checked") == 832
                and epop_profile_tasking_audit.get("response_rows_checked") == 1664
                and epop_profile_tasking_audit.get("date_cluster_effects_independently_recomputed") is True
                and epop_profile_tasking.get("dropout_profile", {}).get("source_profile_sha256")
                    == sha256_file(ROOT / "data/attitude/cassiope_epop/dropout_profile_1minute.json")
                and epop_profile_tasking_audit.get("dropout_profile_design_sha256")
                    == epop_profile_tasking.get("dropout_profile", {}).get("design_sha256"),
                "CASSIOPE-profile full-catalog tasking result is incomplete or failed independent audit")
    epop_empirical_tasking_path = Path(
        "outputs/full-catalog-tasking-epop-empirical-block-weekly-2022-2026")
    epop_empirical_tasking = None
    epop_empirical_tasking_audit = None
    if ((epop_empirical_tasking_path / "summary.json").exists()
            and (epop_empirical_tasking_path / "independent_audit.json").exists()):
        epop_empirical_tasking = load_json(str(epop_empirical_tasking_path / "summary.json"))
        epop_empirical_tasking_audit = load_json(
            str(epop_empirical_tasking_path / "independent_audit.json"))
        require(epop_empirical_tasking.get("status") == "completed"
                and epop_empirical_tasking.get("completed_date_regime_groups") == 832
                and len(epop_empirical_tasking.get("rows", [])) == 1664
                and epop_empirical_tasking_audit.get("status") == "passed_structural_and_statistical"
                and epop_empirical_tasking_audit.get("dates_checked") == 208
                and epop_empirical_tasking_audit.get("paired_date_regime_cells_checked") == 832
                and epop_empirical_tasking_audit.get("response_rows_checked") == 1664
                and epop_empirical_tasking.get("dropout_profile", {}).get("mode") == "empirical_block"
                and epop_empirical_tasking.get("dropout_profile", {}).get("source_profile_sha256")
                    == sha256_file(ROOT / "data/attitude/cassiope_epop/dropout_profile_1minute.json")
                and epop_empirical_tasking.get("dropout_profile", {}).get("mask_archive_sha256")
                    == epop_dropout_masks_audit.get("mask_archive_sha256")
                and epop_empirical_tasking_audit.get("checks", {}).get(
                    "empirical_mask_archive_hash_and_source_audit") is True,
                "CASSIOPE empirical-block full-catalog tasking result is incomplete or failed independent audit")
    awp_cpf = load_json("outputs/awp-ilrs-cpf-validation-2022-2026/summary.json")
    awp_cpf_audit = load_json("outputs/awp-ilrs-cpf-validation-2022-2026/independent_audit.json")
    awp_cpf_drag = load_json("outputs/awp-ilrs-cpf-drag-validation-2022-2026/summary.json")
    awp_cpf_drag_audit = load_json("outputs/awp-ilrs-cpf-drag-validation-2022-2026/independent_audit.json")
    awp_cpf_drag_rerun = load_json(
        "outputs/awp-ilrs-cpf-drag-validation-independent-rerun-2026-10-10/summary.json")
    awp_cpf_iers = load_json("outputs/awp-ilrs-cpf-iers-earth-constants-2022-2026/summary.json")
    awp_cpf_iers_audit = load_json("outputs/awp-ilrs-cpf-iers-earth-constants-2022-2026/independent_audit.json")
    dense_sgp4_cpf = load_json(
        "outputs/dense-sgp4-cpf-validation-2022-2026/independent_audit.json")
    dust_detection = load_json("outputs/four-year-quarterly-dust-anchored-detection-sensitivity/sensitivity_summary.json")
    dust_detection_audit = load_json("outputs/four-year-quarterly-dust-anchored-detection-sensitivity/independent_sensitivity_audit.json")
    dust_persistence = load_json("outputs/dust-burst-persistence-empirical/summary.json")
    dust_persistence_audit = load_json("outputs/dust-burst-persistence-empirical/independent_audit.json")
    durham = load_json("data/ground_sensor/durham_widefield_ssa/dataset_audit.json")
    ilrs = load_json("outputs/ilrs-cross-target-sensor-quality/summary.json")
    ztf = load_json("outputs/ztf-palomer-opportunity-poc/audit.json")
    buaa_benchmark = load_json("outputs/buaa-msod-msamnet-test/benchmark.json")
    buaa_benchmark_audit = load_json("outputs/buaa-msod-msamnet-test/independent_audit.json")
    buaa_recall_sensitivity = load_json(
        "outputs/four-year-quarterly-buaa-recall-sensitivity-2026-10-11/sensitivity_summary.json")
    buaa_recall_sensitivity_audit = load_json(
        "outputs/four-year-quarterly-buaa-recall-sensitivity-2026-10-11/independent_sensitivity_audit.json")
    most_attempt_audit = load_json("data/ground_sensor/most_2004_2005/attempt_audit.json")
    visibility_4hour = load_json(
        "outputs/all-catalog-visibility-census-4hour-2022-2026/manifest.json")
    visibility_4hour_audit = load_json(
        "outputs/all-catalog-visibility-census-4hour-2022-2026/independent_audit.json")
    original = load_json("data/godsat_original_artifact_availability.json")
    cohort_dropout = load_json(
        "outputs/catalog-dropout-cohort-comparison-2022-2026/summary.json")

    # Keep the matched cohort analysis tied to the exact component audits and
    # response files used to calculate it. This aggregate audit verifies
    # provenance and design completeness; it does not relabel injected loss as
    # an empirically observed sensor failure rate.
    expected_cohort_sources = {
        "all_catalog": "outputs/full-catalog-tasking-monthly-2022-2026",
        "current_active_payload": "outputs/current-active-payload-tasking-monthly-2022-2026",
    }
    cohort_source_hashes_valid = True
    for cohort_name, source_folder in expected_cohort_sources.items():
        recorded = cohort_dropout.get("source_sha256", {}).get(cohort_name, {})
        for filename in ("summary.json", "independent_audit.json", "responses.csv"):
            source_path = ROOT / source_folder / filename
            cohort_source_hashes_valid &= (
                source_path.is_file()
                and recorded.get(str(source_path)) == sha256_file(source_path))
    require(cohort_dropout.get("status") == "completed"
            and cohort_dropout.get("shared_sensor_hosts_verified_date_regime_cells") == 192
            and cohort_dropout.get("source_audits") == {
                "all_catalog": "passed_structural_and_statistical",
                "current_active_payload": "passed_structural_and_statistical",
            }
            and len(cohort_dropout.get("results", [])) == 8
            and cohort_source_hashes_valid,
            "Matched catalog-cohort dropout analysis is incomplete or its source hashes changed")

    require(trajectory.get("status") == "completed", "Full-catalog trajectory export is not completed")
    require(trajectory_audit.get("status") == "validated_complete", "Full-catalog trajectory audit is not complete")
    require(trajectory.get("signature") == trajectory_audit.get("signature"), "Trajectory export and audit signatures differ")
    require(trajectory.get("source_revision") == trajectory_audit.get("source_revision"), "Trajectory source revisions differ")
    require(trajectory.get("projected_rows") == trajectory_audit.get("rows"), "Trajectory row totals do not reconcile")
    require(trajectory.get("object_count") == trajectory_audit.get("objects"), "Trajectory object totals do not reconcile")
    require(trajectory.get("parts_written") == trajectory_audit.get("parts_validated"), "Trajectory part totals do not reconcile")
    require(element_selection.get("status") == "validated_complete_source_epoch_selection"
            and element_selection.get("trajectory_signature") == trajectory.get("signature")
            and element_selection.get("validation_signature") == trajectory_audit.get("signature")
            and element_selection.get("rows_checked") == trajectory_audit.get("rows")
            and element_selection.get("fresh_source_rows") == trajectory_audit.get("successful") + trajectory_audit.get("sgp4_errors")
            and element_selection.get("stale_or_missing_source_rows") == trajectory_audit.get("stale_or_missing")
            and element_selection.get("status_mismatches") == 0
            and element_selection.get("selected_epoch_mismatches") == 0
            and element_selection.get("element_age_mismatches") == 0,
            "Complete raw-source epoch selection audit is incomplete or has mismatches")
    source_years = source_epoch_validation.get("years", {})
    require(source_epoch_manifest.get("status") == "completed"
            and source_epoch_validation.get("status") == "validated_complete"
            and source_epoch_repair.get("status") == "completed"
            and source_epoch_validation.get("export_signature") == source_epoch_manifest.get("signature")
            and source_epoch_validation.get("source_revision") == source_epoch_manifest.get("source_revision")
            and source_epoch_validation.get("export_records_written_at_validation_start")
                    == source_epoch_validation.get("export_records_written_at_validation_completion")
                    == source_epoch_manifest.get("records_written")
            and source_epoch_validation.get("records_validated") == source_epoch_manifest.get("records_written")
            and set(source_years) == {"2022", "2023", "2024", "2025", "2026"}
            and all(row.get("export_complete_for_year") is True
                    and row.get("count_match") is True
                    and row.get("successful_state_rows_all_finite") is True
                    and row.get("failed_state_rows_all_nonfinite") is True
                    and row.get("manifest_error_counts_match") is True
                    and row.get("independent_sample_records") == 100
                    and row.get("sample_max_abs_position_difference_km") == 0
                    and row.get("sample_max_abs_velocity_difference_km_s") == 0
                    for row in source_years.values())
            and sum(row["output_records"] for row in source_years.values())
                    == source_epoch_manifest.get("records_written")
            and source_epoch_manifest.get("records_written") == 79_357_514,
            "Raw source-epoch state archive is incomplete or its source validation does not reconcile")
    require(current_snapshot.get("status") == "completed"
            and current_snapshot_audit.get("status") == "passed_structural_and_sampled_state_reproduction"
            and current_snapshot.get("current_payload_states_written") == 16676
            and current_snapshot_audit.get("output_rows_checked") == 16676
            and current_snapshot.get("query_epoch_utc") > trajectory.get("end_exclusive")
            and current_snapshot["state_status_counts"].get("success") == 16596
            and current_snapshot["state_status_counts"].get("stale_element") == 78
            and current_snapshot["state_status_counts"].get("future_element") == 2
            and current_snapshot_audit.get("successful_current_states_without_historical_elements") == 738,
            "Common-epoch current active payload supplement is incomplete or unaudited")

    require(current_active.get("status") == "completed", "Current active-payload history export is not completed")
    require(current_active.get("historical_record_count", 0) > 0, "Current active-payload history is empty")
    require(campaign.get("status") == "completed", "Exact active-host DOE campaign audit did not complete")
    require(all(campaign.get("checks", {}).values()), "One or more DOE campaign integrity checks failed")
    center_replication_surfaces_path = ROOT / "outputs/all-orbits-active-hosts-center-replication/response_surfaces_augmented.json"
    center_replication_report_path = ROOT / "outputs/all-orbits-active-hosts-center-replication/center_replication_report.md"
    require(center_replication.get("status") == "completed"
            and center_replication.get("planned_additional_replicates") == 12
            and center_replication.get("observed_additional_replicates") == 12
            and center_replication.get("unique_seed_count") == 13
            and center_replication.get("total_center_observations") == 13
            and center_replication.get("pure_error_df", {}).get("objective") == 12
            and center_replication.get("pure_error_df", {}).get("custody_continuity") == 12
            and center_replication.get("lack_of_fit_df", {}).get("objective") == 5
            and center_replication.get("lack_of_fit_df", {}).get("custody_continuity") == 5
            and center_replication.get("response_surfaces_sha256") == sha256_file(center_replication_surfaces_path)
            and center_replication.get("report_sha256") == sha256_file(center_replication_report_path),
            "Four-regime replicated-center DOE analysis is incomplete or its report/surface hashes differ")
    require(center_replication_validation.get("status") == "completed"
            and center_replication_validation.get("additional_replicates_validated") == 12
            and center_replication_validation.get("center_observations") == 13
            and center_replication_validation.get("unique_center_seeds") == 13
            and center_replication_validation.get("response_surfaces_reproduced") is True
            and center_replication_validation.get("failures") == [],
            "Independent replicated-center DOE validation failed")
    require(awp.get("status") == "completed_valid", "Monthly AWP comparison audit is not valid")
    require(awp_proxy_summary.get("status") == "completed"
            and awp_proxy_summary.get("completed_scenarios") == 192
            and awp_proxy_summary.get("scenario_failures") == []
            and awp_proxy_summary.get("policy_evaluation_design_rows") == 1920
            and awp_proxy_summary.get("dropout_evaluation_design_rows") == 19200
            and abs(awp_proxy_summary.get("config", {}).get("dropout_burst_persistence", -1)
                    - dust_persistence["failure_state_persistence_proxy"]) < 1e-14
            and awp_proxy_summary.get("config", {}).get("dropout_burst_reference_step_seconds") == 1.0
            and awp_proxy_summary.get("config", {}).get("step_seconds") == 60,
            "DUST-persistence AWP sensitivity design is incomplete or misconfigured")
    require(awp_proxy.get("status") == "completed_valid"
            and awp_proxy.get("policy_rows") == 1920
            and awp_proxy.get("dropout_rows") == 19200
            and awp_proxy.get("scenario_cache_hashes_checked") == 384
            and awp_proxy.get("checkpoint_hashes_checked") == 5
            and awp_proxy.get("failures") == [],
            "DUST-persistence AWP sensitivity independent audit failed")
    dust_persistence_effective_interval = [
        rescale_markov_persistence(value, 0.2, 1.0, 60.0)
        for value in dust_persistence["session_cluster_bootstrap_ci95"]
    ]
    require(all(abs(value - 0.2) < 1e-12 for value in dust_persistence_effective_interval),
            "DUST persistence interval should collapse to the memoryless 60-second process")
    durham_reference_cadence = statistics.median(
        night["observed_frame_time_delta_seconds"]["median"]
        for night in durham["sensitivity_by_night"])
    durham_markov_persistence = durham["conditional_missing_state_persistence_proxy"][
        "markov_missing_to_missing_transition_fraction"]
    from godsat.environment import rescale_markov_persistence
    durham_effective_persistence = rescale_markov_persistence(
        durham_markov_persistence,
        durham["conditional_in_field_detection_gap_proxy"]["conditional_unrecorded_fraction"],
        durham_reference_cadence, durham_awp_summary["config"]["step_seconds"])
    require(len(durham["sensitivity_by_night"]) == durham["coverage"]["night_count"] == 10,
            "Durham cadence scaling does not cover every audited observing night")
    require(durham_awp_summary.get("status") == "completed"
            and durham_awp_summary.get("completed_scenarios") == 192
            and durham_awp_summary.get("scenario_failures") == []
            and durham_awp_summary.get("policy_evaluation_design_rows") == 1920
            and durham_awp_summary.get("dropout_evaluation_design_rows") == 19200
            and abs(durham_awp_summary.get("dropout_outage_rate", -1)
                    - durham["conditional_in_field_detection_gap_proxy"]["conditional_unrecorded_fraction"]) < 1e-14
            and abs(durham_awp_summary.get("config", {}).get("dropout_burst_persistence", -1)
                    - durham_markov_persistence) < 1e-12
            and abs(durham_awp_summary.get("config", {}).get("dropout_burst_reference_step_seconds", -1)
                    - durham_reference_cadence) < 1e-9
            and durham_awp_summary.get("config", {}).get("step_seconds") == 60,
            "Durham-parameterized AWP sensitivity design is incomplete or misconfigured")
    require(durham_awp_audit.get("status") == "completed_valid"
            and durham_awp_audit.get("policy_rows") == 1920
            and durham_awp_audit.get("dropout_rows") == 19200
            and durham_awp_audit.get("scenario_cache_hashes_checked") == 384
            and durham_awp_audit.get("checkpoint_hashes_checked") == 5
            and durham_awp_audit.get("failures") == [],
            "Durham-parameterized AWP sensitivity independent audit failed")
    for label, (summary, result) in durham_awp_rate_ci.items():
        require(summary.get("status") == "completed"
                and summary.get("completed_scenarios") == 192
                and summary.get("scenario_failures") == []
                and summary.get("policy_evaluation_design_rows") == 1920
                and summary.get("dropout_evaluation_design_rows") == 19200
                and result.get("status") == "completed_valid"
                and result.get("policy_rows") == 1920
                and result.get("dropout_rows") == 19200
                and result.get("scenario_cache_hashes_checked") == 384
                and result.get("checkpoint_hashes_checked") == 5
                and result.get("failures") == [],
                f"Durham {label}-rate uncertainty sensitivity is incomplete or unaudited")
        expected_rate = durham["conditional_in_field_detection_gap_proxy"]["night_cluster_bootstrap_ci95"][
            0 if label == "low" else 1]
        require(abs(summary.get("dropout_outage_rate", -1) - expected_rate) < 1e-14,
                f"Durham {label}-rate sensitivity does not match the source interval")
        require(abs(summary.get("config", {}).get("dropout_burst_persistence", -1)
                    - durham_markov_persistence) < 1e-12
                and abs(summary.get("config", {}).get("dropout_burst_reference_step_seconds", -1)
                        - durham_reference_cadence) < 1e-9,
                f"Durham {label}-rate sensitivity does not use source-cadence-scaled persistence")
    require(dropout.get("status") == "completed_valid", "Four-year synthetic dropout audit is not valid")
    require(dropout.get("date_count") == 48 and dropout.get("unique_valid_rows") == dropout.get("expected_treatment_rows"),
            "Four-year dropout design is incomplete")
    require(visibility.get("status") == "completed" and visibility.get("date_count") == 48,
            "Catalog visibility census is incomplete")
    require(visibility.get("host_group_count") == 192,
            "Catalog visibility census lacks its 48-date by four-regime design")
    require(len(visibility.get("scenario_cache_sha256", {})) == 192,
            "Catalog visibility census is missing scenario cache hashes")
    require(visibility_audit.get("status") == "passed"
            and visibility_audit.get("dates_checked") == 48
            and visibility_audit.get("scenario_cache_hashes_verified") == 192,
            "Independent catalog visibility census audit did not pass")
    require(full_catalog_tasking.get("status") == "completed"
            and full_catalog_tasking.get("completed_date_regime_groups") == 192
            and len(full_catalog_tasking.get("rows", [])) == 384,
            "Full-catalog tasking benchmark is incomplete")
    require(full_catalog_tasking_audit.get("status") == "passed_structural_and_statistical"
            and full_catalog_tasking_audit.get("response_rows_checked") == 384
            and full_catalog_tasking_audit.get("sensor_host_scenario_hashes_verified") == 192
            and full_catalog_tasking_audit.get("historical_host_state_availability", {}).get("cells_recomputed") == 192
            and full_catalog_tasking_audit.get("historical_host_state_availability", {}).get("missing_agent_steps_by_host_regime") == {"leo": 0, "meo": 0, "geo": 0, "heo": 39},
            "Independent full-catalog tasking audit did not pass")
    require(full_catalog_weekly_tasking.get("status") == "completed"
            and len(full_catalog_weekly_tasking.get("dates", [])) == 208
            and full_catalog_weekly_tasking["dates"][0] == "2022-10-15T00:00:00Z"
            and full_catalog_weekly_tasking["dates"][-1] == "2026-10-03T00:00:00Z"
            and full_catalog_weekly_tasking.get("completed_date_regime_groups") == 832
            and len(full_catalog_weekly_tasking.get("rows", [])) == 1664,
            "Weekly full-catalog tasking benchmark is incomplete")
    require(full_catalog_weekly_tasking_audit.get("status") == "passed_structural_and_statistical"
            and full_catalog_weekly_tasking_audit.get("dates_checked") == 208
            and full_catalog_weekly_tasking_audit.get("paired_date_regime_cells_checked") == 832
            and full_catalog_weekly_tasking_audit.get("response_rows_checked") == 1664
            and full_catalog_weekly_tasking_audit.get("sensor_host_scenario_hashes_verified") == 832
            and full_catalog_weekly_tasking_audit.get("historical_host_state_availability", {}).get("cells_recomputed") == 832
            and full_catalog_weekly_tasking_audit.get("scenario_metadata_checksum_mismatches") == [],
            "Independent weekly full-catalog tasking audit did not pass")
    require(active_payload_tasking.get("status") == "completed"
            and active_payload_tasking.get("target_cohort") == "current_active_payload"
            and active_payload_tasking.get("target_cohort_id_count") == 15927
            and active_payload_tasking.get("completed_date_regime_groups") == 192
            and len(active_payload_tasking.get("rows", [])) == 384,
            "Current-active-payload monthly tasking benchmark is incomplete")
    require(active_payload_tasking_audit.get("status") == "passed_structural_and_statistical"
            and active_payload_tasking_audit.get("target_cohort") == "current_active_payload"
            and active_payload_tasking_audit.get("response_rows_checked") == 384
            and active_payload_tasking_audit.get("sensor_host_scenario_hashes_verified") == 192
            and active_payload_tasking_audit.get("historical_host_state_availability", {}).get("cells_recomputed") == 192
            and active_payload_tasking_audit.get("historical_host_state_availability", {}).get("missing_agent_steps_by_host_regime") == {"leo": 0, "meo": 0, "geo": 0, "heo": 39},
            "Independent current-active-payload tasking audit did not pass")
    require(full_catalog_seed_sensitivity.get("status") == "completed"
            and len(full_catalog_seed_sensitivity.get("dates", [])) == 48
            and len(full_catalog_seed_sensitivity.get("response_rows", [])) == 384,
            "Full-catalog independent-seed sensitivity is incomplete")
    require(full_catalog_seed_audit.get("status") == "passed_source_design_and_statistical_reproduction"
            and full_catalog_seed_audit.get("response_rows_checked") == 384
            and full_catalog_seed_audit.get("scenario_cache_hashes_verified") == 192
            and full_catalog_seed_audit.get("checks", {}).get(
                "paired_seed_by_outage_interactions_recomputed") is True,
            "Independent full-catalog seed-sensitivity audit did not pass")
    require(capacity.get("status") == "completed"
            and capacity.get("completed_date_regime_capacity_groups") == 204
            and len(capacity.get("rows", [])) == 408,
            "Full-catalog capacity sensitivity is incomplete")
    require(capacity_audit.get("status") == "passed_structural_and_statistical"
            and capacity_audit.get("capacity_cells_checked") == 204
            and capacity_audit.get("response_rows_checked") == 408
            and capacity_audit.get("target_denominator_fixed_across_capacities") is True,
            "Independent full-catalog capacity audit did not pass")
    require(capacity_monthly.get("status") == "completed"
            and capacity_monthly.get("date_grid") == "monthly"
            and len(capacity_monthly.get("dates", [])) == 48
            and capacity_monthly.get("completed_date_regime_capacity_groups") == 576
            and len(capacity_monthly.get("rows", [])) == 1152,
            "Full-catalog monthly capacity sensitivity is incomplete")
    require(capacity_monthly_audit.get("status") == "passed_structural_and_statistical"
            and capacity_monthly_audit.get("date_grid") == "monthly"
            and capacity_monthly_audit.get("capacity_cells_checked") == 576
            and capacity_monthly_audit.get("response_rows_checked") == 1152
            and capacity_monthly_audit.get("scenario_cache_hashes_verified") == 192
            and capacity_monthly_audit.get("target_denominator_fixed_across_capacities") is True,
            "Independent monthly full-catalog capacity audit did not pass")
    require(len(visibility.get("dates", [])) == 48 and len(visibility.get("host_regime_groups", [])) == 192,
            "Catalog visibility census row counts do not reconcile")
    for row in visibility["dates"]:
        require(row["archived_catalog_ids"] == trajectory_audit["objects"],
                "Catalog visibility census denominator disagrees with the full trajectory catalog")
        require(row["distinct_targets_observable_from_any_selected_host_set"] <= row["propagatable_objects"],
                "Observable target count exceeds the propagatable catalog")
    require(dust.get("status") == "completed" and dust.get("missing_rows") == 0,
            "DUST frame-dropout replay is incomplete")
    require(dust_image.get("status") == "completed"
            and dust_image.get("same_frame_background_test", {}).get("tested_gaps") == 47
            and dust_image.get("heldout_threshold_detection", {}).get("status")
                == "completed_leave_one_session_out_threshold_replay"
            and dust_image.get("heldout_threshold_detection", {}).get("session_folds") == 22
            and dust_image.get("heldout_threshold_detection", {}).get(
                "positive_labeled_positions", {}).get("total") == 4237
            and dust_image.get("heldout_threshold_detection", {}).get(
                "background_controls", {}).get("total") == 8821
            and dust_image.get("heldout_threshold_detection", {}).get(
                "interpolated_annotation_gaps", {}).get("signal_like") == 26
            and dust_image.get("heldout_threshold_detection", {}).get(
                "interpolated_annotation_gaps", {}).get("total") == 47
            and "not confirmed identity" in dust_image.get("heldout_threshold_detection", {}).get(
                "interpretation_limit", ""),
            "DUST matched-frame gap-signal analysis is incomplete")
    dust_image_csv = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study/internal_gap_image_signal.csv"
    require(dust_image_csv.is_file()
            and sha256_file(dust_image_csv) == dust_image.get("csv_sha256"),
            "DUST session-held-out image-signal ledger hash does not match its audit")
    if recompute_dust_source:
        from audit_dust_gap_image_visibility import audit as audit_dust_gap_image_visibility
        with tempfile.TemporaryDirectory(prefix="godsat-dust-image-signal-audit-") as temporary_dir:
            recomputed_dust_image = audit_dust_gap_image_visibility(
                ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip", Path(temporary_dir))
        require(recomputed_dust_image == dust_image,
                "DUST held-out image-signal analysis does not reproduce from source images/annotations")
    dust_interpolation_csv = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study/gap_interpolation_cross_validation.csv"
    require(dust_gap_interpolation.get("status") == "completed_labeled_track_interpolation_cross_validation"
            and dust_gap_interpolation.get("archive_md5") == dust_cadence.get("archive_md5")
            and dust_gap_interpolation.get("validation_design", {}).get("heldout_frames") == 48410
            and dust_interpolation_csv.is_file()
            and sha256_file(dust_interpolation_csv) == dust_gap_interpolation.get("validation_design", {}).get("csv_sha256"),
            "DUST gap-interpolation cross-validation provenance or coverage is invalid")
    if recompute_dust_source:
        from audit_dust_gap_interpolation import audit as audit_dust_gap_interpolation
        with tempfile.TemporaryDirectory(prefix="godsat-dust-interpolation-audit-") as temporary_dir:
            recomputed_interpolation = audit_dust_gap_interpolation(
                ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip", Path(temporary_dir))
        require(recomputed_interpolation == dust_gap_interpolation,
                "DUST gap-interpolation cross-validation does not reproduce from source annotations")
    require(dust_cadence.get("status") == "completed"
            and dust_cadence.get("metadata_image_rows_checked") == 1378
            and dust_cadence.get("session_count") == 22
            and dust_cadence.get("session_cadence", {}).get("missing_nominal_capture_slots") == 66
            and dust_cadence.get("annotated_transit_windows", {}).get("missing_nominal_capture_slots_inside_transit_windows") == 94
            and "cannot be attributed to hardware dropout" in dust_cadence.get("interpretation", ""),
            "DUST empirical image-cadence gap audit is incomplete or overstates causal evidence")
    require(dust_cadence_custody.get("status") == "completed_conditional_cadence_custody_sensitivity"
            and dust_cadence_custody.get("annotated_transits") == 160
            and dust_cadence_custody.get("transit_weighted_expected_1hz_slots") == 4378
            and dust_cadence_custody.get("missing_capture_slots_inside_annotated_transits") == 94
            and dust_cadence_custody_audit.get("status") == "passed_independent_source_and_statistical_reproduction"
            and dust_cadence_custody_audit.get("zero_mismatches") is True
            and dust_cadence_custody_audit.get("bootstrap_replicates_recomputed") == 10000
            and dust_cadence_custody_audit.get("empirical_capture_gap_proxy", {}).get("missing_capture_slots") == 94
            and dust_cadence_custody_audit.get("empirical_capture_gap_proxy", {}).get("expected_transit_slots") == 4378
            and dust_cadence_custody_audit.get("empirical_capture_gap_proxy", {}).get("bootstrap_replicates") == 10000,
            "DUST timestamp-grid custody sensitivity or independent audit is incomplete")
    require("not a missed-acquisition probability" in ilrs.get("interpretation", ""),
            "ILRS result interpretation must explicitly distinguish acquired-pass quality from dropout")
    require(sentinel_access.get("inventory_products") == 7896
            and sentinel_access.get("probes", {}).get("public_catalogue_product_metadata", {}).get("status_code") == 200
            and sentinel_access.get("probes", {}).get("odata_product_download_without_token", {}).get("status_code") == 401
            and sentinel_access.get("probes", {}).get("s3_object_without_keys", {}).get("status_code") == 403,
            "Sentinel attitude access boundary audit is missing or inconclusive")
    require(dense_sgp4_cpf.get("status") == "passed_dense_source_epoch_and_position_reproduction"
            and dense_sgp4_cpf.get("target_count") == 4
            and dense_sgp4_cpf.get("response_rows_checked") == 483718,
            "Dense full-available-coverage SGP4/CPF orbit validation is incomplete")
    dense_rows = 0
    for target in dense_sgp4_cpf["targets"]:
        folder = ROOT / f"data/ground_sensor/ilrs_{target['target']}_npt"
        expected = target["source_sha256"]
        actual = {
            "normal_points.csv": sha256_file(folder / "normal_points.csv"),
            "cpf_manifest.json": sha256_file(folder / "cpf_manifest.json"),
            "orbit_model_comparison.csv": sha256_file(folder / "orbit_model_comparison.csv"),
            "orbit_model_comparison_summary.json": sha256_file(folder / "orbit_model_comparison_summary.json"),
        }
        require(actual == expected, f"Dense SGP4/CPF source or result hash mismatch for {target['target']}")
        dense_rows += target["rows_checked"]
    require(dense_rows == dense_sgp4_cpf["response_rows_checked"],
            "Dense SGP4/CPF per-target row totals do not reconcile")
    require(awp_cpf.get("status") == "completed" and len(awp_cpf.get("targets", [])) == 4
            and awp_cpf_audit.get("status") == "passed_structural_and_statistical"
            and awp_cpf_audit.get("response_rows_checked") == 1536,
            "AWP versus ILRS CPF validation is incomplete or unaudited")
    require(awp_cpf_drag.get("status") == "completed" and awp_cpf_drag.get("model_id") == "awp_j2_drag"
            and len(awp_cpf_drag.get("targets", [])) == 4
            and awp_cpf_drag_audit.get("status") == "passed_structural_and_statistical"
            and awp_cpf_drag_audit.get("model_id") == "awp_j2_drag"
            and awp_cpf_drag_audit.get("response_rows_checked") == 1536,
            "AWP drag versus ILRS CPF validation is incomplete or unaudited")
    require(awp_cpf_drag_rerun.get("status") == "completed"
            and awp_cpf_drag_rerun.get("model_id") == awp_cpf_drag.get("model_id")
            and len(awp_cpf_drag_rerun.get("targets", [])) == len(awp_cpf_drag["targets"]) == 4,
            "Fresh independent AWP drag recomputation is incomplete")
    for original_target, rerun_target in zip(awp_cpf_drag["targets"], awp_cpf_drag_rerun["targets"]):
        require(original_target["design"]["target"] == rerun_target["design"]["target"]
                and original_target["output_csv_sha256"] == rerun_target["output_csv_sha256"]
                and original_target["metrics"] == rerun_target["metrics"],
                f"Fresh AWP drag recomputation differs for {original_target['design']['target']}")
    require(awp_cpf_iers.get("status") == "completed"
            and awp_cpf_iers.get("earth_constants", {}).get("model") == "IERS Conventions 2010"
            and len(awp_cpf_iers.get("targets", [])) == 4
            and awp_cpf_iers_audit.get("status") == "passed_structural_and_statistical"
            and awp_cpf_iers_audit.get("response_rows_checked") == 1536,
            "IERS-constant AWP versus ILRS CPF comparison is incomplete or unaudited")
    require(dust_detection.get("status") == "completed"
            and dust_detection.get("probability_levels") == [0.9762, 0.989, 0.9972]
            and len(dust_detection.get("dates", [])) == 17
            and dust_detection_audit.get("status") == "completed_valid"
            and dust_detection_audit.get("date_clusters") == 17
            and dust_detection_audit.get("independent_regime_mode_effect_checks") == 24
            and dust_detection_audit.get("independent_interaction_checks") == 24,
            "DUST-anchored four-year detection sensitivity or its independent analysis audit is incomplete")
    for probability in dust_detection["probability_levels"]:
        label = f"pbase-{probability:.2f}"
        treatment_audit = load_json(
            f"outputs/four-year-quarterly-dust-anchored-detection-sensitivity/{label}/dropout_integrity_audit.json")
        require(dust_detection["results"].get(label, {}).get("status") == "completed"
                and treatment_audit.get("status") == "completed_valid"
                and treatment_audit.get("expected_treatment_rows") == 6800
                and treatment_audit.get("unique_valid_rows") == 6800,
                f"DUST-anchored detection treatment audit failed for {label}")
    require(dust_persistence.get("status") == "completed"
            and dust_persistence.get("sessions") == 22
            and dust_persistence.get("conditional_internal_span_frames") == 4284
            and dust_persistence.get("unlabeled_internal_frames") == 47
            and dust_persistence.get("internal_gap_runs") == 27
            and dust_persistence_audit.get("status") == "passed_independent_source_reproduction"
            and dust_persistence_audit.get("checks", {}).get("bootstrap_interval_reproduces") is True,
            "DUST annotation-gap burst-persistence analysis is incomplete or unaudited")
    from audit_durham_widefield_ssa import audit as audit_durham_widefield_ssa
    durham_source = ROOT / "data/ground_sensor/durham_widefield_ssa/all_data.zip"
    recomputed_durham = audit_durham_widefield_ssa(durham_source)
    require(recomputed_durham == durham,
            "Durham nightly optical detection audit does not reproduce from its checksum-verified source")
    require(durham.get("status") == "completed_conditional_on_sky_detection_gap_audit"
            and durham.get("coverage", {}).get("night_count") == 10
            and durham.get("coverage", {}).get("reported_detection_rows") == 202627
            and durham.get("source", {}).get("tle_files_found_in_released_nightly_archives") == 0
            and durham.get("conditional_in_field_detection_gap_proxy", {}).get("target_frame_opportunities") == 161805
            and durham.get("conditional_in_field_detection_gap_proxy", {}).get("unrecorded_target_frames") == 23547,
            "Durham conditional optical gap evidence is missing, incomplete, or inconsistent")
    most_rows = most_attempt_audit.get("published_summary_table_rows", [])
    most_denominator = most_attempt_audit.get("denominator_audit", {})
    require(most_attempt_audit.get("status") == "published_outcomes_found_attempt_denominator_ambiguous"
            and len(most_rows) == most_denominator.get("table_rows") == 7
            and sum(row.get("reported_result") == "FAILED" for row in most_rows)
                == most_denominator.get("listed_failed_table_rows") == 4
            and sum(row.get("reported_result") == "SUCCESS" for row in most_rows)
                == most_denominator.get("success_rows") == 2
            and sum(row.get("reported_result") == "N/A" for row in most_rows)
                == most_denominator.get("preempted_not_attempted_rows") == 1
            and most_denominator.get("listed_failed_target_names") == 5
            and most_denominator.get("attempt_rate_calculated") is False
            and most_attempt_audit.get("scope", {}).get("relation_to_four_year_study_window")
                == "outside the 2022-10-09 through 2026-10-10 window",
            "MOST historical outcome evidence is inconsistent or improperly used as a four-year dropout rate")

    local = original.get("local_workspace", {})
    original_available = bool(local.get("matlab_source_files")) and bool(local.get("pretrained_q_table_artifacts_found"))
    natural_dropout_measured = False  # Optical track gaps are conditional; no population-level attempt/health ledger exists.
    ztf_metadata_path = ROOT / ztf["metadata_file"]
    require(ztf_metadata_path.is_file(), "ZTF metadata snapshot is missing")
    require(sha256_file(ztf_metadata_path) == ztf["metadata_sha256"], "ZTF metadata checksum mismatch")
    with ztf_metadata_path.open(newline="") as stream:
        ztf_metadata_rows = sum(1 for _ in csv.DictReader(stream))
    require(ztf_metadata_rows == 11096, "ZTF metadata row count differs from the validated snapshot")
    ztf_fullnight_path = ROOT / "data/ground_sensor/ztf_palomer_poc/ztf_metadata_2024-07-10_fullnight.csv"
    require(ztf_fullnight_path.is_file(), "Full-night ZTF metadata snapshot is missing")
    ztf_fullnight_sha256 = sha256_file(ztf_fullnight_path)
    with ztf_fullnight_path.open(newline="") as stream:
        ztf_fullnight_rows = list(csv.DictReader(stream))
    ztf_fullnight_exposures = len({row["expid"] for row in ztf_fullnight_rows})
    require(ztf_fullnight_sha256 == "0f481170358b4260c3d74eccbcd9a79d41480793c95c7d2e552790cc3c39e070",
            "Full-night ZTF metadata checksum differs from the audited snapshot")
    require(len(ztf_fullnight_rows) == 24437 and ztf_fullnight_exposures == 424,
            "Full-night ZTF metadata row or exposure count differs from the audited snapshot")
    ztf_fullnight_crossings_path = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10/midpoint_crossing_audit.json"
    require(ztf_fullnight_crossings_path.is_file(), "Full-night ZTF midpoint crossing audit is missing")
    ztf_fullnight_crossings = json.loads(ztf_fullnight_crossings_path.read_text())
    require(ztf_fullnight_crossings.get("metadata_sha256") == ztf_fullnight_sha256
            and ztf_fullnight_crossings.get("metadata_rows") == len(ztf_fullnight_rows)
            and ztf_fullnight_crossings.get("exposures") == ztf_fullnight_exposures
            and ztf_fullnight_crossings.get("catalog_ids_considered") == 40206,
            "Full-night ZTF crossing audit does not match its metadata/catalog inputs")
    ztf_exposure_path_path = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10/exposure_path_audit.json"
    require(ztf_exposure_path_path.is_file(), "Full-night ZTF exposure-path audit is missing")
    ztf_exposure_paths = json.loads(ztf_exposure_path_path.read_text())
    crossing_keys = {(row["expid"], int(row["ccdid"]), int(row["qid"]), int(row["norad_id"]))
                     for row in ztf_fullnight_crossings["candidates"]}
    path_keys = {(row["expid"], int(row["ccdid"]), int(row["qid"]), int(row["norad_id"]))
                 for row in ztf_exposure_paths.get("candidates", [])}
    path_totals = ztf_exposure_paths.get("totals", {})
    require(ztf_exposure_paths.get("status") == "completed_full_exposure_paths_for_midpoint_candidates"
            and ztf_exposure_paths.get("metadata_sha256") == ztf_fullnight_sha256
            and ztf_exposure_paths.get("midpoint_audit_sha256") == sha256_file(ztf_fullnight_crossings_path)
            and path_keys == crossing_keys
            and len(path_keys) == path_totals.get("midpoint_candidates_replayed")
            and path_totals.get("candidates_with_path_inside") == len(path_keys)
            and path_totals.get("candidates_with_observable_path_inside") == len(path_keys)
            and path_totals.get("candidates_with_sunlit_observable_path_inside")
                == sum(bool(row["any_path_sunlit_observable_inside"]) for row in ztf_exposure_paths["candidates"])
            and path_totals.get("exposures_with_any_sunlit_observable_path_inside")
                == len({row["expid"] for row in ztf_exposure_paths["candidates"]
                        if row["any_path_sunlit_observable_inside"]})
            and path_totals.get("maximum_midpoint_direction_error_arcsec", float("inf")) < 0.1,
            "Full-night ZTF exposure-path ledger does not reconcile with midpoint candidates/source")
    ztf_edge_path = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10/edge_crossing_audit.json"
    require(ztf_edge_path.is_file(), "Full-night ZTF midpoint-outside edge-crossing audit is missing")
    ztf_edges = json.loads(ztf_edge_path.read_text())
    ztf_edge_keys = {(row["expid"], int(row["ccdid"]), int(row["qid"]), int(row["norad_id"]))
                     for row in ztf_edges.get("candidates", [])}
    ztf_midpoint_keys = crossing_keys
    edge_totals = ztf_edges.get("totals", {})
    edge_hits = [row for row in ztf_edges.get("candidates", []) if row.get("crosses_quadrant_during_exposure")]
    edge_sunlit = [row for row in ztf_edges.get("candidates", []) if row.get("sunlit_observable_crossing")]
    require(ztf_edges.get("status") == "completed_screened_edge_crossing_replay"
            and ztf_edges.get("scope_complete") is True
            and ztf_edges.get("metadata_sha256") == ztf_fullnight_sha256
            and ztf_edges.get("midpoint_audit_sha256") == sha256_file(ztf_fullnight_crossings_path)
            and ztf_edges.get("exposures_screened") == ztf_fullnight_exposures
            and len(ztf_edge_keys) == edge_totals.get("screened_candidates")
            and not (ztf_edge_keys & ztf_midpoint_keys)
            and len(edge_hits) == edge_totals.get("exact_path_edge_crossings")
            and len(edge_sunlit) == edge_totals.get("sunlit_observable_edge_crossings")
            and len({row["expid"] for row in edge_hits}) == edge_totals.get("exposures_with_edge_crossing"),
            "Full-night ZTF midpoint-outside edge-crossing ledger does not reconcile")
    ztf_image_sample_path = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10/image_sample_audit.json"
    require(ztf_image_sample_path.is_file(), "Full-night ZTF image profile audit is missing")
    ztf_image_sample = json.loads(ztf_image_sample_path.read_text())
    require(ztf_image_sample.get("status") == "completed_profile_audit"
            and ztf_image_sample.get("images_completed") == 12
            and len(ztf_image_sample.get("image_results", [])) == 12
            and ztf_image_sample.get("opportunity_count") == 41
            and ztf_image_sample.get("metadata_sha256") == ztf_fullnight_sha256
            and ztf_image_sample.get("midpoint_audit_sha256") == sha256_file(ztf_fullnight_crossings_path)
            and ztf_image_sample.get("exposure_path_audit_sha256") == sha256_file(ztf_exposure_path_path)
            and ztf_image_sample.get("edge_crossing_audit_sha256") == sha256_file(ztf_edge_path),
            "Full-night ZTF image profile audit is incomplete or source hashes differ")
    eligible_ztf_opportunities = {
        (row["expid"], int(row["ccdid"]), int(row["qid"]), int(row["norad_id"]))
        for row in ztf_exposure_paths["candidates"] if row.get("any_path_sunlit_observable_inside")}
    eligible_ztf_opportunities.update(
        (row["expid"], int(row["ccdid"]), int(row["qid"]), int(row["norad_id"]))
        for row in ztf_edges["candidates"] if row.get("sunlit_observable_crossing"))
    sample_opportunity_keys = set()
    ztf_sample_image_hashes_checked = 0
    for image in ztf_image_sample["image_results"]:
        image_path = ROOT / image["image_path"]
        require(image_path.is_file() and image_path.stat().st_size == image["image_bytes"]
                and sha256_file(image_path) == image["image_sha256"],
                f"ZTF sample science image checksum mismatch: {image['image_path']}")
        ztf_sample_image_hashes_checked += 1
        require(len(image["candidate_results"]) == image["candidate_count"],
                "ZTF sample image candidate count does not reconcile")
        for row in image["candidate_results"]:
            key = (row["expid"], int(row["ccdid"]), int(row["qid"]), int(row["norad_id"]))
            require(key in eligible_ztf_opportunities and key not in sample_opportunity_keys,
                    "ZTF sample candidate is not an eligible unique source-ledger opportunity")
            sample_opportunity_keys.add(key)
    require(len(sample_opportunity_keys) == ztf_image_sample["opportunity_count"],
            "ZTF image sample candidate opportunities do not reconcile")
    ztf_injection_path = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10/injected_streak_detection_benchmark.json"
    require(ztf_injection_path.is_file(), "ZTF held-out injected-streak benchmark is missing")
    ztf_injection = json.loads(ztf_injection_path.read_text())
    ztf_sample_exposure_ids = {str(row["expid"]) for row in ztf_image_sample["image_results"]}
    injection_exposure_ids = {str(row["expid"]) for row in ztf_injection.get("heldout_image_results", [])}
    require(ztf_injection.get("status") == "completed_image_level_injection_benchmark"
            and ztf_injection.get("image_sample_sha256") == sha256_file(ztf_image_sample_path)
            and injection_exposure_ids == ztf_sample_exposure_ids
            and len(ztf_injection.get("heldout_image_results", [])) == len(ztf_image_sample["image_results"]),
            "ZTF injected-streak benchmark does not reconcile to every sampled image")
    injection_trial_count = 0
    trial_rows_by_magnitude = {}
    baseline_control_flags = {str(q): [] for q in (0.90, 0.95, 0.99)}
    for image in ztf_injection["heldout_image_results"]:
        training_ids = {str(value) for value in image["training_exposure_ids"]}
        require(str(image["expid"]) not in training_ids
                and training_ids | {str(image["expid"])} == ztf_sample_exposure_ids,
                "ZTF injection benchmark has heldout exposure leakage")
        sample_image = next(row for row in ztf_image_sample["image_results"]
                            if str(row["expid"]) == str(image["expid"]))
        require(image["image_sha256"] == sample_image["image_sha256"],
                "ZTF injection heldout image hash differs from image sample")
        for candidate in image["candidate_results"]:
            baseline = candidate.get("no_injection_score_over_global_sigma")
            if baseline is not None:
                for quantile, threshold in candidate["training_null_thresholds"].items():
                    baseline_control_flags[quantile].append(baseline >= threshold)
            for trial in candidate.get("injection_trials", []):
                injection_trial_count += 1
                trial_rows_by_magnitude.setdefault(float(trial["maglimit_offset"]), []).append(trial)
    require(injection_trial_count > 0
            and all(len(rows) == len(trial_rows_by_magnitude.get(offset, []))
                    for offset, rows in trial_rows_by_magnitude.items()),
            "ZTF injected-streak positive-control trials are incomplete")
    for row in ztf_injection.get("summary_by_magnitude", []):
        trials = trial_rows_by_magnitude.get(float(row["maglimit_offset"]), [])
        require(len(trials) == row["trials"], "ZTF injection magnitude trial count differs")
        for quantile, rate in row["detection_fraction_at_training_null_quantile"].items():
            expected_rate = (sum(bool(trial["above_training_thresholds"][quantile]) for trial in trials)/len(trials)
                             if trials else None)
            require(rate == expected_rate, "ZTF injection recovery fraction does not reproduce")
    require(ztf_injection["heldout_no_injection_control_false_alarm_fraction"] == {
                quantile: (sum(flags)/len(flags) if flags else None)
                for quantile, flags in baseline_control_flags.items()},
            "ZTF injection heldout background-control rates do not reproduce")
    ztf_association_path = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10/real_image_path_association_audit.json"
    require(ztf_association_path.is_file(), "ZTF real-image path association audit is missing")
    ztf_association = json.loads(ztf_association_path.read_text())
    require(ztf_association.get("status") == "completed_descriptive_real_image_path_association_audit"
            and ztf_association.get("image_sample_sha256") == sha256_file(ztf_image_sample_path)
            and ztf_association.get("selection_and_measurement", {}).get("images") == 12
            and ztf_association.get("selection_and_measurement", {}).get("predicted_opportunities") == 41
            and ztf_association.get("selection_and_measurement", {}).get("profiled_opportunities") == 34
            and len(ztf_association.get("opportunity_results", [])) == 41,
            "ZTF real-image association audit does not reconcile to the source-linked sample")
    from audit_ztf_real_image_path_associations import audit as recompute_ztf_association
    recomputed_ztf_association = recompute_ztf_association(
        ztf_image_sample, sha256_file(ztf_image_sample_path))
    require(ztf_association == recomputed_ztf_association,
            "ZTF real-image path association results do not reproduce")
    require(len(ztf["candidates"]) == 5, "ZTF candidate track set is incomplete")
    ztf_image_hashes_checked = 0
    for candidate in ztf["candidates"]:
        image_path = ROOT / candidate["image_path"]
        require(image_path.is_file(), f"ZTF science image is missing: {candidate['image_path']}")
        require(sha256_file(image_path) == candidate["image_sha256"],
                f"ZTF science image checksum mismatch: {candidate['image_path']}")
        ztf_image_hashes_checked += 1
    require(buaa_benchmark.get("status") == "completed"
            and buaa_benchmark.get("dataset") == "BUAA-MSOD"
            and buaa_benchmark.get("frame_count") == 3840
            and buaa_benchmark.get("sequence_groups") == 64
            and buaa_benchmark.get("ground_truth_boxes") == 355
            and buaa_benchmark.get("checkpoint_sha256") == "933c3c94bbe56e5e5052b334d280f23f8d53d922615a83238d774f2b1ab313fe"
            and buaa_benchmark_audit.get("status") == "passed_source_and_metric_reproduction"
            and buaa_benchmark_audit.get("frames_checked") == 3840
            and buaa_benchmark_audit.get("ground_truth_centers_reconciled_to_archive") == 355
            and buaa_benchmark_audit.get("aggregate_metrics_recomputed") is True,
            "BUAA-MSOD held-out detector benchmark or independent audit is incomplete")
    require(buaa_recall_sensitivity.get("status") == "completed"
            and buaa_recall_sensitivity.get("probability_levels") == [0.84, 0.95, 1.0]
            and len(buaa_recall_sensitivity.get("dates", [])) == 17
            and buaa_recall_sensitivity_audit.get("status") == "completed_valid"
            and buaa_recall_sensitivity_audit.get("date_clusters") == 17
            and buaa_recall_sensitivity_audit.get("independent_regime_mode_effect_checks") == 24
            and buaa_recall_sensitivity_audit.get("independent_interaction_checks") == 24,
            "BUAA-recall-anchored dropout sensitivity or its independent audit is incomplete")
    for probability in buaa_recall_sensitivity["probability_levels"]:
        label = f"pbase-{probability:.2f}"
        treatment_audit = load_json(
            f"outputs/four-year-quarterly-buaa-recall-sensitivity-2026-10-11/{label}/dropout_integrity_audit.json")
        require(buaa_recall_sensitivity["results"].get(label, {}).get("status") == "completed"
                and treatment_audit.get("status") == "completed_valid"
                and treatment_audit.get("expected_treatment_rows") == 6800
                and treatment_audit.get("unique_valid_rows") == 6800,
                f"BUAA-recall sensitivity treatment audit failed for {label}")
    require(visibility_4hour.get("status") == "completed"
            and visibility_4hour.get("part_count_complete") == 1462
            and visibility_4hour.get("source_rows") == 352687032
            and visibility_4hour.get("cadence_seconds") == 14400
            and visibility_4hour_audit.get("status") == "passed_structural_and_stratified_source_recomputation"
            and visibility_4hour_audit.get("source_parts_checked") == 1462
            and visibility_4hour_audit.get("four_hour_samples_structurally_checked") == 8772
            and visibility_4hour_audit.get("visibility_timeseries_rows") == 35088
            and visibility_4hour_audit.get("independent_visibility_recomputations", 0) >= 48,
            "Four-year four-hour all-catalog visibility census or its independent audit is incomplete")
    return {
        "status": "validated_artifacts_with_external_evidence_gaps",
        "scope": "Reconciles persisted component audits, including source-rerun dense SGP4-to-CPF comparison rows for four ILRS targets, checksum-linked full-night ZTF metadata, midpoint/exposure/edge trajectory ledgers, selected science-image profiles, held-out synthetic trail sensitivity, descriptive real-image path association against parallel lanes, the complete raw-source epoch/freshness comparison for the catalog grid, fresh AWP drag-to-CPF reproduction, and corrected-IERS-constant AWP-to-CPF comparison. It does not rerun the multi-day DOE or full-catalog episodes.",
        "execution_qualifiers": {
            "dust_interpolation_archive_recomputed_in_this_invocation": recompute_dust_source,
            "saved_independent_dust_source_audit_status": dust_gap_interpolation["status"],
            "note": (
                "DUST interpolation was freshly recomputed from the source archive in this invocation."
                if recompute_dust_source else
                "The cloud-offloaded DUST archive was not reopened; this invocation reused its persisted checksum-linked independent source audit."
            ),
        },
        "evidence": {
            "four_year_all_catalog_trajectory": {
                "status": trajectory_audit["status"],
                "objects": trajectory_audit["objects"],
                "rows": trajectory_audit["rows"],
                "parts": trajectory_audit["parts_validated"],
                "successful": trajectory_audit["successful"],
                "sgp4_errors": trajectory_audit["sgp4_errors"],
                "stale_or_missing": trajectory_audit["stale_or_missing"],
                "cadence_hours": trajectory["step_seconds"] / 3600,
            },
            "four_year_trajectory_latest_source_refresh": {
                "status": trajectory_refresh["status"],
                "source_revision": trajectory_refresh["source_revision"],
                "source_latest_epoch_utc": trajectory_refresh["source_latest_epoch_utc"],
                "objects": trajectory_refresh["objects_checked"],
                "start_inclusive": trajectory_refresh["start_inclusive"],
                "end_exclusive": trajectory_refresh["end_exclusive"],
                "rows": trajectory_refresh["trajectory_rows_checked"],
                "independent_state_replays": trajectory_refresh["independent_state_replays"],
                "maximum_sample_position_difference_km": trajectory_refresh["maximum_position_difference_km"],
                "maximum_sample_velocity_difference_km_s": trajectory_refresh["maximum_velocity_difference_km_s"],
                "comparison_to_pinned_archive": trajectory_refresh["comparison_to_pinned_archive"],
                "scope_limit": trajectory_refresh["scope_limit"],
            },
            "four_year_all_catalog_source_epoch_vectors": {
                "status": source_epoch_validation["status"],
                "source_epoch_records": source_epoch_manifest["records_written"],
                "source_revision": source_epoch_manifest["source_revision"],
                "yearly_record_counts": {
                    year: row["output_records"] for year, row in source_years.items()},
                "distinct_catalog_ids_by_year": {
                    year: row["distinct_catalog_ids"] for year, row in source_years.items()},
                "all_year_source_counts_reconciled": True,
                "independent_source_state_samples": sum(
                    row["independent_sample_records"] for row in source_years.values()),
                "max_sample_position_difference_km": max(
                    row["sample_max_abs_position_difference_km"] for row in source_years.values()),
                "max_sample_velocity_difference_km_s": max(
                    row["sample_max_abs_velocity_difference_km_s"] for row in source_years.values()),
                "sgp4_errors": sum(sum(int(count) for code, count in row["sgp4_error_counts"].items()
                                       if int(code) != 0)
                                   for row in source_years.values()),
                "repair_audit_status": source_epoch_repair["status"],
                "cadence_and_scope_limit": "One reconstructed SGP4 state per archived orbital-element epoch; epochs are irregular. This is the complete local source history, not a continuous fixed-cadence ephemeris or proof of operating status.",
            },
            "all_catalog_source_element_selection": {
                "status": element_selection["status"],
                "rows_checked": element_selection["rows_checked"],
                "fresh_source_rows": element_selection["fresh_source_rows"],
                "stale_or_missing_source_rows": element_selection["stale_or_missing_source_rows"],
                "selected_epoch_mismatches": element_selection["selected_epoch_mismatches"],
                "element_age_mismatches": element_selection["element_age_mismatches"],
                "max_element_age_delta_hours": element_selection["max_element_age_delta_hours"],
                "scope_limit": "Checks source epoch selection and freshness for every row; SGP4 vectors remain fully structural-audited and source-reproduced on stratified samples, not recomputed for all rows.",
            },
            "current_active_payload_common_epoch_snapshot": {
                "status": current_snapshot["status"],
                "independent_audit_status": current_snapshot_audit["status"],
                "query_epoch_utc": current_snapshot["query_epoch_utc"],
                "payload_candidates": current_snapshot["current_payload_candidates"],
                "common_epoch_states": current_snapshot["current_payload_states_written"],
                "state_status_counts": current_snapshot["state_status_counts"],
                "payload_ids_with_archived_history": current_snapshot["current_payload_ids_with_archived_history"],
                "payload_ids_without_archived_history": current_snapshot["current_payload_ids_without_archived_history"],
                "fresh_states_without_archived_history": current_snapshot_audit["successful_current_states_without_historical_elements"],
                "interpretation": current_snapshot["interpretation"],
            },
            "active_payload_history": {
                "objects": current_active["historical_object_count"],
                "records": current_active["historical_record_count"],
                "historical_snapshot_backcast": True,
            },
            "paper_design_campaign": {
                "status": campaign["status"],
                "screening_runs": campaign["screening_treatments"],
                "ccd_runs": campaign["ccd_treatments"],
                "bayesian_runs": campaign["bayesian_treatments"],
                "checkpoint_count": campaign["checkpoint_count"],
            },
            "replicated_center_lack_of_fit": {
                "status": center_replication_validation["status"],
                "additional_independent_center_retrains": center_replication["observed_additional_replicates"],
                "total_center_observations": center_replication["total_center_observations"],
                "pure_error_degrees_of_freedom": center_replication["pure_error_df"],
                "lack_of_fit_degrees_of_freedom": center_replication["lack_of_fit_df"],
                "response_surface_hash_verified": True,
                "report_hash_verified": True,
                "lack_of_fit": {
                    metric: center_replication_surfaces[metric]["lack_of_fit"]
                    for metric in ("objective", "custody_continuity", "slew_energy_proxy", "false_track_proxy", "wall_seconds")
                },
                "interpretation": "Independent center replication rejects the quadratic model for objective and custody; the fitted optimum is not validated.",
            },
            "awp_four_year_monthly_policy_comparison": {
                "status": awp["status"],
                "policy_rows": awp["policy_rows"],
                "dropout_rows": awp["dropout_rows"],
                "scenario_cache_hashes_checked": awp["scenario_cache_hashes_checked"],
            },
            "awp_dust_persistence_monthly_sensitivity": {
                "status": awp_proxy["status"],
                "persistence_proxy": awp_proxy_summary["config"]["dropout_burst_persistence"],
                "source_persistence_ci95": dust_persistence["session_cluster_bootstrap_ci95"],
                "source_frame_cadence_seconds": awp_proxy_summary["config"]["dropout_burst_reference_step_seconds"],
                "simulator_step_seconds": awp_proxy_summary["config"]["step_seconds"],
                "effective_simulator_step_persistence": dust_persistence_effective_interval,
                "scenario_count": awp_proxy_summary["completed_scenarios"],
                "policy_rows": awp_proxy["policy_rows"],
                "dropout_rows": awp_proxy["dropout_rows"],
                "scenario_cache_hashes_checked": awp_proxy["scenario_cache_hashes_checked"],
                "dropout_effects_recomputed": awp_proxy["dropout_effects_recomputed"],
                "interpretation": "Burst-duration sensitivity using a DUST annotation-gap proxy; it is not a natural hardware failure estimate.",
            },
            "awp_durham_gap_parameterized_sensitivity": {
                "status": durham_awp_audit["status"],
                "authoritative_cadence_scaled_run": True,
                "scenario_count": durham_awp_summary["completed_scenarios"],
                "requested_conditional_outage_rate": durham_awp_summary["dropout_outage_rate"],
                "requested_catalogue_gap_transition_persistence": durham_awp_summary["config"]["dropout_burst_persistence"],
                "source_frame_cadence_seconds_median_of_nightly_medians": durham_reference_cadence,
                "simulator_step_seconds": durham_awp_summary["config"]["step_seconds"],
                "effective_simulator_step_persistence": durham_effective_persistence,
                "nightly_cadence_summaries_checked": len(durham["sensitivity_by_night"]),
                "policy_rows": durham_awp_audit["policy_rows"],
                "dropout_rows": durham_awp_audit["dropout_rows"],
                "scenario_cache_hashes_checked": durham_awp_audit["scenario_cache_hashes_checked"],
                "effects_recomputed": durham_awp_audit["dropout_effects_recomputed"],
                "supersedes": "outputs/awp-policy-monthly-durham-gap-sensitivity-2022-2026 and unscaled ci-low/ci-high folders",
                "interpretation": "Synthetic burst-loss sensitivity parameterized by conditional optical catalogue gaps; persistence is cadence-scaled to 60 s while preserving the stationary rate. Not a population-wide hardware dropout measurement.",
            },
            "awp_durham_gap_rate_uncertainty_endpoints": {
                label: {
                    "status": audit_result["status"],
                    "requested_rate": summary["dropout_outage_rate"],
                    "source_frame_cadence_seconds": summary["config"]["dropout_burst_reference_step_seconds"],
                    "effective_simulator_step_persistence": rescale_markov_persistence(
                        durham_markov_persistence, summary["dropout_outage_rate"],
                        durham_reference_cadence, summary["config"]["step_seconds"]),
                    "policy_rows": audit_result["policy_rows"],
                    "dropout_rows": audit_result["dropout_rows"],
                    "scenario_cache_hashes_checked": audit_result["scenario_cache_hashes_checked"],
                    "effects_recomputed": audit_result["dropout_effects_recomputed"],
                }
                for label, (summary, audit_result) in durham_awp_rate_ci.items()
            },
            "simulated_four_year_dropout_design": {
                "status": dropout["status"],
                "dates": dropout["date_count"],
                "treatment_rows": dropout["unique_valid_rows"],
            },
            "all_catalog_monthly_visibility_census": {
                "status": visibility["status"],
                "dates": visibility["date_count"],
                "host_regime_groups": visibility["host_group_count"],
                "independent_audit_status": visibility_audit["status"],
                "archived_catalog_ids_per_date": visibility["dates"][0]["archived_catalog_ids"],
                "mean_fresh_propagatable_objects": round(statistics.mean(
                    row["propagatable_objects"] for row in visibility["dates"]), 1),
                "mean_objects_geometrically_visible": round(statistics.mean(
                    row["distinct_targets_observable_from_any_selected_host_set"]
                    for row in visibility["dates"]), 1),
            },
            "all_catalog_four_hour_visibility_opportunity_census": {
                "status": visibility_4hour["status"],
                "independent_audit_status": visibility_4hour_audit["status"],
                "source_objects": visibility_4hour["object_count"],
                "source_rows": visibility_4hour["source_rows"],
                "source_daily_parts": visibility_4hour_audit["source_parts_checked"],
                "four_hour_samples": visibility_4hour_audit["four_hour_samples_structurally_checked"],
                "visibility_timeseries_rows": visibility_4hour_audit["visibility_timeseries_rows"],
                "independent_visibility_recomputations": visibility_4hour_audit["independent_visibility_recomputations"],
                "cadence_hours": visibility_4hour["cadence_seconds"] / 3600,
                "interpretation_limit": "All-catalog geometric line-of-sight opportunities at four-hour samples from hypothetical current-active hosts assigned to the nearest monthly DOE host cohort; not observations, tasked opportunities, detection probability, or continuous visibility.",
            },
            "all_catalog_monthly_tasking_reference": {
                "status": full_catalog_tasking["status"],
                "independent_audit_status": full_catalog_tasking_audit["status"],
                "dates": len(full_catalog_tasking["dates"]),
                "sensor_regime_groups": full_catalog_tasking["completed_date_regime_groups"],
                "paired_responses": len(full_catalog_tasking["rows"]),
                "mean_candidate_catalog_ids_per_episode": round(statistics.mean(
                    row["catalog_objects_in_episode"] for row in full_catalog_tasking["rows"]
                    if row["requested_outage_rate"] == 0), 1),
                "mean_zero_loss_custody": round(statistics.mean(
                    row["custody_continuity"] for row in full_catalog_tasking["rows"]
                    if row["requested_outage_rate"] == 0), 6),
                "mean_20pct_burst_loss_custody": round(statistics.mean(
                    row["custody_continuity"] for row in full_catalog_tasking["rows"]
                    if row["requested_outage_rate"] == 0.2), 6),
                "mean_sensor_actions_per_hour": round(statistics.mean(
                    row["sensor_actions"] for row in full_catalog_tasking["rows"]
                    if row["requested_outage_rate"] == 0), 1),
                "historical_host_state_cells_recomputed": full_catalog_tasking_audit["historical_host_state_availability"]["cells_recomputed"],
                "historical_unavailable_host_steps_by_regime": full_catalog_tasking_audit["historical_host_state_availability"]["missing_agent_steps_by_host_regime"],
                "scenario_metadata_hash_drifts_reported": len(full_catalog_tasking_audit["scenario_metadata_checksum_mismatches"]),
                "method": full_catalog_tasking["method"],
            },
            "all_catalog_weekly_tasking_reference": {
                "status": full_catalog_weekly_tasking["status"],
                "independent_audit_status": full_catalog_weekly_tasking_audit["status"],
                "dates": len(full_catalog_weekly_tasking["dates"]),
                "date_range": [full_catalog_weekly_tasking["dates"][0],
                               full_catalog_weekly_tasking["dates"][-1]],
                "sensor_regime_groups": full_catalog_weekly_tasking["completed_date_regime_groups"],
                "paired_responses": len(full_catalog_weekly_tasking["rows"]),
                "scenario_hashes_verified": full_catalog_weekly_tasking_audit["sensor_host_scenario_hashes_verified"],
                "historical_host_state_cells_recomputed": full_catalog_weekly_tasking_audit["historical_host_state_availability"]["cells_recomputed"],
                "historical_unavailable_host_steps_by_regime": full_catalog_weekly_tasking_audit["historical_host_state_availability"]["missing_agent_steps_by_host_regime"],
                "mean_candidate_catalog_ids_per_episode": round(statistics.mean(
                    row["catalog_objects_in_episode"] for row in full_catalog_weekly_tasking["rows"]
                    if row["requested_outage_rate"] == 0), 1),
                "mean_zero_loss_custody": round(statistics.mean(
                    row["custody_continuity"] for row in full_catalog_weekly_tasking["rows"]
                    if row["requested_outage_rate"] == 0), 6),
                "mean_20pct_burst_loss_custody": round(statistics.mean(
                    row["custody_continuity"] for row in full_catalog_weekly_tasking["rows"]
                    if row["requested_outage_rate"] == 0.2), 6),
                "effects_by_regime": full_catalog_weekly_tasking["paired_effects"],
                "method": full_catalog_weekly_tasking["method"],
                "interpretation_limit": "Weekly one-hour samples of an all-catalog greedy tasking reference with synthetic injected burst loss; not continuous operations, the trained policy, or natural sensor reliability.",
            },
            "current_active_payload_monthly_tasking_backcast": {
                "status": active_payload_tasking["status"],
                "independent_audit_status": active_payload_tasking_audit["status"],
                "current_snapshot_history_ids": active_payload_tasking["target_cohort_id_count"],
                "target_cohort_id_sha256": active_payload_tasking["target_cohort_id_sha256"],
                "dates": len(active_payload_tasking["dates"]),
                "sensor_regime_groups": active_payload_tasking["completed_date_regime_groups"],
                "paired_responses": len(active_payload_tasking["rows"]),
                "historical_host_state_cells_recomputed": active_payload_tasking_audit["historical_host_state_availability"]["cells_recomputed"],
                "historical_unavailable_host_steps_by_regime": active_payload_tasking_audit["historical_host_state_availability"]["missing_agent_steps_by_host_regime"],
                "scenario_metadata_hash_drifts_reported": len(active_payload_tasking_audit["scenario_metadata_checksum_mismatches"]),
                "episode_target_ids_min_max": [
                    min(row["catalog_objects_in_episode"] for row in active_payload_tasking["rows"]),
                    max(row["catalog_objects_in_episode"] for row in active_payload_tasking["rows"])],
                "effects_by_regime": [
                    {"sensor_host_regime": row["sensor_host_regime"],
                     "custody_change_20pct_minus_0": row["custody_change_20pct_minus_0"],
                     "observable_custody_change_20pct_minus_0": row["observable_custody_change_20pct_minus_0"],
                     "slew_proxy_change_20pct_minus_0": row["slew_proxy_change_20pct_minus_0"]}
                    for row in active_payload_tasking["paired_effects"]],
                "interpretation_limit": "Uses today’s active-GP/SATCAT classification backcast to archived historical elements; it does not establish historical operational status. The outage is injected and synthetic, and samples one hour per month.",
            },
            "all_catalog_monthly_tasking_seed_sensitivity": {
                "status": full_catalog_seed_sensitivity["status"],
                "independent_audit_status": full_catalog_seed_audit["status"],
                "additional_seed": full_catalog_seed_sensitivity["seed"],
                "dates": full_catalog_seed_audit["dates_checked"],
                "paired_responses": full_catalog_seed_audit["response_rows_checked"],
                "scenario_hashes_verified": full_catalog_seed_audit["scenario_cache_hashes_verified"],
                "effects_by_regime": full_catalog_seed_audit["date_clustered_effects"],
                "seed_by_outage_interaction": full_catalog_seed_audit["seed_by_outage_interaction"],
                "interpretation": "Added seed robustness for injected-loss effects across all catalog targets; does not provide natural hardware dropout rates or continuous historical operations.",
            },
            "all_catalog_quarterly_host_capacity_sensitivity": {
                "status": capacity["status"],
                "independent_audit_status": capacity_audit["status"],
                "dates": len(capacity["dates"]),
                "capacity_cells": capacity["completed_date_regime_capacity_groups"],
                "paired_responses": len(capacity["rows"]),
                "mean_candidate_catalog_ids_per_episode": round(statistics.mean(
                    row["catalog_objects_in_episode"] for row in capacity["rows"]
                    if row["requested_outage_rate"] == 0), 1),
                "maximum_supported_hosts_by_regime_and_date": capacity.get("maximum_team_size_by_date_regime", {}),
                "uniform_capacity_effects": capacity["capacity_effects"],
                "method": capacity["method"],
            },
            "all_catalog_monthly_host_capacity_sensitivity": {
                "status": capacity_monthly["status"],
                "independent_audit_status": capacity_monthly_audit["status"],
                "dates": capacity_monthly_audit["dates_checked"],
                "capacity_cells": capacity_monthly_audit["capacity_cells_checked"],
                "paired_responses": capacity_monthly_audit["response_rows_checked"],
                "scenario_hashes_verified": capacity_monthly_audit["scenario_cache_hashes_verified"],
                "mean_candidate_catalog_ids_per_episode": round(statistics.mean(
                    row["catalog_objects_in_episode"] for row in capacity_monthly["rows"]
                    if row["requested_outage_rate"] == 0), 1),
                "maximum_supported_hosts_by_regime_and_date": capacity_monthly.get("maximum_team_size_by_date_regime", {}),
                "uniform_capacity_effects": capacity_monthly["capacity_effects"],
                "method": capacity_monthly["method"],
                "interpretation_limit": "Forty-eight monthly one-hour snapshots under hypothetical active sensor hosts and a greedy scheduler; outage is injected, not empirically observed.",
            },
            "matched_catalog_cohort_dropout_sensitivity": {
                "status": cohort_dropout["status"],
                "shared_sensor_hosts_verified_date_regime_cells": cohort_dropout[
                    "shared_sensor_hosts_verified_date_regime_cells"],
                "regime_metric_comparisons": len(cohort_dropout["results"]),
                "source_hashes_revalidated": True,
                "tasking_capacity": cohort_dropout["tasking_capacity"],
                "interpretation_limit": "Paired synthetic 20% burst-loss sensitivity across different target populations; not measured physical sensor reliability or natural dropout effectiveness.",
            },
            "measured_sensor_sources": {
                "MOST_historical_tasking_outcomes": {
                    "status": most_attempt_audit["status"],
                    "listed_failed_date_events": most_denominator["listed_failed_table_rows"],
                    "listed_failed_target_names": most_denominator["listed_failed_target_names"],
                    "successful_events": most_denominator["success_rows"],
                    "preempted_opportunities": most_denominator["preempted_not_attempted_rows"],
                    "distinct_attempt_denominator_resolved": False,
                    "failure_fraction_calculated": False,
                    "interpretation_limit": most_attempt_audit["interpretation"],
                },
                "BUAA_MSOD_checkpoint_test": {
                    "status": buaa_benchmark["status"],
                    "independent_audit_status": buaa_benchmark_audit["status"],
                    "checkpoint_repository_commit": buaa_benchmark["upstream_model_commit"],
                    "checkpoint_sha256": buaa_benchmark["checkpoint_sha256"],
                    "test_frames": buaa_benchmark_audit["frames_checked"],
                    "sequence_groups": buaa_benchmark_audit["sequence_groups_checked"],
                    "publisher_target_boxes": buaa_benchmark_audit["ground_truth_centers_reconciled_to_archive"],
                    "precision_against_released_labels": buaa_benchmark["precision_against_released_labels"],
                    "recall_against_released_labels": buaa_benchmark["recall_against_released_labels"],
                    "f1_against_released_labels": buaa_benchmark["f1_against_released_labels"],
                    "interpretation_limit": buaa_benchmark["interpretation_limit"],
                },
                "DUST_frame_replay_status": dust["status"],
                "DUST_internal_gaps_with_BH_adjusted_local_signal": dust_image["same_frame_background_test"]["gaps_bh_q_below_0_05"],
                "DUST_gap_interpolation_cross_validation": {
                    "status": dust_gap_interpolation["status"],
                    "heldout_labeled_frames": dust_gap_interpolation["validation_design"]["heldout_frames"],
                    "by_gap_length": dust_gap_interpolation["by_gap_length"],
                    "interpretation": dust_gap_interpolation["interpretation_limit"],
                },
                "DUST_image_cadence": {
                    "sessions": dust_cadence["session_count"],
                    "frames": dust_cadence["image_frames_checked"],
                    "missing_nominal_1hz_slots_between_session_images": dust_cadence["session_cadence"]["missing_nominal_capture_slots"],
                    "session_capture_fraction_within_observed_bounds": dust_cadence["session_cadence"]["observed_capture_fraction"],
                    "target_weighted_missing_nominal_slots_inside_annotated_transits": dust_cadence["annotated_transit_windows"]["missing_nominal_capture_slots_inside_transit_windows"],
                    "target_weighted_capture_fraction_inside_annotated_transits": dust_cadence["annotated_transit_windows"]["capture_fraction_inside_transit_windows"],
                    "source_recomputed_target_window_capture_gap_proxy": dust_cadence_custody_audit["empirical_capture_gap_proxy"],
                    "interpretation": dust_cadence["interpretation"],
                },
                "DUST_timestamp_grid_custody_sensitivity": {
                    "status": dust_cadence_custody["status"],
                    "independent_audit_status": dust_cadence_custody_audit["status"],
                    "annotated_transits": dust_cadence_custody["annotated_transits"],
                    "transit_weighted_expected_1hz_slots": dust_cadence_custody["transit_weighted_expected_1hz_slots"],
                    "missing_capture_slots": dust_cadence_custody["missing_capture_slots_inside_annotated_transits"],
                    "custody_by_grace_seconds": [
                        {"grace_seconds": row["grace_seconds"],
                         "observed_manual_labels_custody": row["equal_weight_session_mean_custody"]["observed_manual_labels"],
                         "capture_gap_filled_custody": row["equal_weight_session_mean_custody"]["fill_missing_capture_slots_with_perfect_detections"],
                         "capture_gap_fill_effect_pp": row["paired_custody_effect_percentage_points"]["capture_gap_fill_minus_observed"]["mean"],
                         "capture_gap_fill_effect_ci95_pp": row["paired_custody_effect_percentage_points"]["capture_gap_fill_minus_observed"]["ci95_session_cluster_bootstrap"]}
                        for row in dust_cadence_custody["results"]],
                    "interpretation": dust_cadence_custody["interpretation"],
                },
                "DUST_heldout_image_detection_sensitivity": dust_image["heldout_threshold_detection"],
                "ILRS_interpretation": ilrs["interpretation"],
                "ZTF_Palomar_image_opportunities": {
                    "status": "completed_image_level_catalog_track_review",
                    "metadata_rows": ztf_metadata_rows,
                    "sampled_exposure_ids": len({r["expid"] for r in ztf["candidates"]}),
                    "candidate_tracks": len(ztf["candidates"]),
                    "sunlit_candidate_tracks": sum(r["predicted_track_sunlit_fraction"] > 0.5 for r in ztf["candidates"]),
                    "likely_catalog_associated_streaks": sum("clear elongated image streak" in r["manual_image_review"] for r in ztf["candidates"]),
                    "weak_or_ambiguous_profile_tracks": sum("ambiguous" in r["manual_image_review"] for r in ztf["candidates"]),
                    "image_files_checksum_verified": ztf_image_hashes_checked,
                    "metadata_checksum_verified": True,
                    "interpretation": "A small public-image sample contains likely catalog-associated streaks and one no-corresponding-trace case. It does not provide a calibrated detection probability or complete attempted-opportunity denominator.",
                },
                "ZTF_Palomar_fullnight_metadata": {
                    "status": "metadata_and_exposure_path_ledger_validated",
                    "metadata_rows": len(ztf_fullnight_rows),
                    "exposure_ids": ztf_fullnight_exposures,
                    "metadata_checksum_verified": True,
                    "midpoint_crossing_audit_status": "validated" if ztf_fullnight_crossings is not None else "not_yet_available",
                    "midpoint_footprint_tracks": (ztf_fullnight_crossings or {}).get("totals", {}).get("candidate_footprint_tracks"),
                    "exposure_path_audit_status": "validated" if ztf_exposure_paths is not None else "not_yet_available",
                    "full_exposure_candidates_inside": (ztf_exposure_paths or {}).get("totals", {}).get("candidates_with_path_inside"),
                    "full_exposure_sunlit_observable_candidates": (ztf_exposure_paths or {}).get("totals", {}).get("candidates_with_sunlit_observable_path_inside"),
                    "full_exposure_sunlit_observable_exposures": (ztf_exposure_paths or {}).get("totals", {}).get("exposures_with_any_sunlit_observable_path_inside"),
                    "full_exposure_max_midpoint_direction_error_arcsec": (ztf_exposure_paths or {}).get("totals", {}).get("maximum_midpoint_direction_error_arcsec"),
                    "midpoint_outside_edge_crossings": edge_totals.get("exact_path_edge_crossings"),
                    "midpoint_outside_sunlit_observable_crossings": edge_totals.get("sunlit_observable_edge_crossings"),
                    "midpoint_outside_edge_exposures": edge_totals.get("exposures_with_edge_crossing"),
                    "edge_search_scope_complete": ztf_edges.get("scope_complete"),
                    "full_night_image_profile_sample": {
                        "status": ztf_image_sample["status"],
                        "science_images_checksum_verified": ztf_sample_image_hashes_checked,
                        "candidate_opportunities_profiled": len(sample_opportunity_keys),
                        "midpoint_outside_edge_candidates_profiled": sum(
                            row["path_source"] == "midpoint_outside_edge_candidate"
                            for image in ztf_image_sample["image_results"] for row in image["candidate_results"]),
                        "interpretation": ztf_image_sample["interpretation_limit"],
                    },
                    "heldout_injected_streak_sensitivity": {
                        "status": ztf_injection["status"],
                        "leave_one_exposure_out_images": len(ztf_injection["heldout_image_results"]),
                        "injected_positive_control_trials": injection_trial_count,
                        "background_control_false_alarm_fraction": ztf_injection["heldout_no_injection_control_false_alarm_fraction"],
                        "recovery_by_magnitude_offset": ztf_injection["summary_by_magnitude"],
                        "interpretation": ztf_injection["interpretation_limit"],
                    },
                    "real_image_path_association": {
                        "status": ztf_association["status"],
                        **ztf_association["summary"],
                        "interpretation": ztf_association["interpretation_limit"],
                    },
                    "interpretation": "Every midpoint-selected candidate and candidates outside the midpoint set were propagated over the exposure. A 12-image profile sample adds pixel-level signal measurements, but the crossings remain candidate opportunities without blind identity truth or a planned-attempt/nondetection denominator.",
                },
            },
            "durham_widefield_optical_observation_gap_proxy": {
                "status": durham["status"],
                "license": durham["source"]["license"],
                "doi": durham["source"]["doi"],
                "nights": durham["coverage"]["night_count"],
                "processed_detection_rows": durham["coverage"]["reported_detection_rows"],
                "identified_catalogues": durham["coverage"]["identified_norad_catalogue_files"],
                "unidentified_track_catalogues": durham["coverage"]["unidentified_track_catalogue_files"],
                "detected_science_frame_timestamps": durham["coverage"]["frame_timestamps_with_any_rso_detection"],
                "tle_files_in_released_archives": durham["source"]["tle_files_found_in_released_nightly_archives"],
                "recomputed_from_source_archive": True,
                "conditional_target_frame_opportunities": durham["conditional_in_field_detection_gap_proxy"]["target_frame_opportunities"],
                "unrecorded_target_frames": durham["conditional_in_field_detection_gap_proxy"]["unrecorded_target_frames"],
                "conditional_unrecorded_fraction": durham["conditional_in_field_detection_gap_proxy"]["conditional_unrecorded_fraction"],
                "night_cluster_bootstrap_ci95": durham["conditional_in_field_detection_gap_proxy"]["night_cluster_bootstrap_ci95"],
                "pooled_sensitivity": durham["pooled_sensitivity"],
                "interpretation": durham["conditional_in_field_detection_gap_proxy"]["interpretation"],
            },
            "sentinel_attitude_access": {
                "inventory_products": sentinel_access["inventory_products"],
                "catalogue_metadata_status": sentinel_access["probes"]["public_catalogue_product_metadata"]["status_code"],
                "download_without_token_status": sentinel_access["probes"]["odata_product_download_without_token"]["status_code"],
                "s3_without_keys_status": sentinel_access["probes"]["s3_object_without_keys"]["status_code"],
                "legacy_endpoint_reachable": "error" not in sentinel_access["probes"].get("legacy_pod_catalogue", {}),
                "product_bytes_downloaded_by_audit": 0,
                "inventory_bytes": sentinel_access["inventory_content_bytes"],
            },
            "cassiope_attitude_solution_dropout_telemetry": {
                "source": epop_attitude_audit["source"],
                "independent_audit_status": epop_attitude_audit["status"],
                "coverage_status": epop_attitude_audit["coverage_status"],
                "fetch_status_at_audit": epop_attitude_audit["manifest_status_at_audit"],
                "fetch_days_processed_at_audit": epop_attitude_audit["manifest_days_processed_at_audit"],
                "fetch_products_validated_at_audit": epop_attitude_audit["manifest_products_validated_at_audit"],
                "fetch_not_published_at_audit": len(epop_attitude_audit["not_published_days"]),
                "fetch_failures_at_audit": epop_attitude_audit["manifest_failures_at_audit"],
                "validated_daily_products": epop_attitude_audit["downloaded_days"],
                "sample_count": epop_attitude_audit["totals"]["samples"],
                "first_day": epop_attitude_audit["first_day"],
                "last_day": epop_attitude_audit["last_day"],
                "invalid_quaternion_seconds": epop_attitude_audit["totals"]["invalid_quaternion_seconds"],
                "dropout_intervals": epop_attitude_audit["totals"]["dropout_events"],
                "longest_dropout_seconds": epop_attitude_audit["longest_solution_dropout_seconds"],
                "limitations": epop_attitude_audit["limitations"],
            },
            "cassiope_empirical_one_minute_dropout_profile": {
                "status": epop_dropout_profile["status"],
                "published_days": epop_dropout_profile["published_days_analyzed"],
                "date_range": epop_dropout_profile["source_date_range"],
                "observed_dropout_rate": epop_dropout_profile["one_minute_attitude_solution_dropout_rate"],
                "date_cluster_bootstrap_ci95": epop_dropout_profile["one_minute_dropout_rate_date_cluster_bootstrap_ci95"],
                "persistence_per_minute": epop_dropout_profile["simulator_markov_persistence_parameter"],
                "dropout_run_length_minutes": epop_dropout_profile["dropout_run_length_minutes"],
                "interpretation": epop_dropout_profile["interpretation"],
            },
            "cassiope_attitude_solution_quality": {
                "status": epop_solution_quality["status"],
                "source_profile_sha256": epop_solution_quality["source_profile_sha256"],
                "sampled_days": epop_solution_quality["sampled_days"],
                "cadence_seconds": epop_solution_quality["cadence_seconds"],
                "quality_class_counts": quality_counts,
                "quality_class_fraction_of_all_samples": epop_solution_quality["quality_class_fraction_of_all_samples"],
                "source_code_counts": epop_solution_quality["source_code_counts"],
                "handbook_nominal_source_uncertainty_degrees": epop_solution_quality["handbook_nominal_source_uncertainty_degrees"],
                "nearest_definitive_solution_spacing_seconds_on_valid_quaternion_samples": epop_solution_quality["nearest_definitive_solution_spacing_seconds_on_valid_quaternion_samples"],
                "limitations": epop_solution_quality["limitations"],
            },
            "cassiope_empirical_dropout_mask_archive": {
                "status": epop_dropout_masks["status"],
                "independent_audit_status": epop_dropout_masks_audit["status"],
                "days": epop_dropout_masks_audit["dates_checked"],
                "samples": epop_dropout_masks_audit["sample_count_checked"],
                "dropout_samples": epop_dropout_masks_audit["dropout_count_recomputed"],
                "cadence_seconds": epop_dropout_masks_audit["cadence_seconds"],
                "source_profile_sha256": epop_dropout_masks_audit["source_profile_sha256"],
                "mask_archive_sha256": epop_dropout_masks_audit["mask_archive_sha256"],
                "checks": epop_dropout_masks_audit["checks"],
            },
            "cassiope_profile_weekly_full_catalog_tasking": ({
                "status": epop_profile_tasking["status"],
                "independent_audit_status": epop_profile_tasking_audit["status"],
                "dates": epop_profile_tasking_audit["dates_checked"],
                "paired_date_regime_cells": epop_profile_tasking_audit["paired_date_regime_cells_checked"],
                "response_rows": epop_profile_tasking_audit["response_rows_checked"],
                "profile_rate": epop_profile_tasking["dropout_profile"]["rate"],
                "profile_persistence_per_minute": epop_profile_tasking["dropout_profile"]["persistence_per_minute"],
                "profile_sha256": epop_profile_tasking["dropout_profile"]["source_profile_sha256"],
                "date_clustered_effects": [{
                    "sensor_host_regime": row["sensor_host_regime"],
                    "custody_change": row["custody_change_dropout_profile_minus_0"],
                    "observable_custody_change": row["observable_custody_change_dropout_profile_minus_0"],
                    "slew_proxy_change": row["slew_proxy_change_dropout_profile_minus_0"],
                } for row in epop_profile_tasking["paired_effects"]],
                "limits": epop_profile_tasking["limits"],
            } if epop_profile_tasking is not None else {
                "status": "not_yet_available",
                "note": "Requires completion and independent audit of all 208 weekly dates.",
            }),
            "cassiope_empirical_block_weekly_full_catalog_tasking": ({
                "status": epop_empirical_tasking["status"],
                "independent_audit_status": epop_empirical_tasking_audit["status"],
                "dates": epop_empirical_tasking_audit["dates_checked"],
                "paired_date_regime_cells": epop_empirical_tasking_audit["paired_date_regime_cells_checked"],
                "response_rows": epop_empirical_tasking_audit["response_rows_checked"],
                "profile_rate": epop_empirical_tasking["dropout_profile"]["rate"],
                "profile_sha256": epop_empirical_tasking["dropout_profile"]["source_profile_sha256"],
                "mask_archive_sha256": epop_empirical_tasking["dropout_profile"]["mask_archive_sha256"],
                "date_clustered_effects": [{
                    "sensor_host_regime": row["sensor_host_regime"],
                    "custody_change": row["custody_change_dropout_profile_minus_0"],
                    "observable_custody_change": row["observable_custody_change_dropout_profile_minus_0"],
                    "slew_proxy_change": row["slew_proxy_change_dropout_profile_minus_0"],
                } for row in epop_empirical_tasking["paired_effects"]],
                "limits": epop_empirical_tasking["limits"],
            } if epop_empirical_tasking is not None else {
                "status": "not_yet_available",
                "note": "Requires completion and independent audit of all 208 weekly dates.",
            }),
            "awp_j2_against_ilrs_cpf": {
                "status": awp_cpf["status"],
                "independent_audit_status": awp_cpf_audit["status"],
                "targets": len(awp_cpf["targets"]),
                "sampled_rows": awp_cpf_audit["response_rows_checked"],
                "cadence_hours": awp_cpf["cadence_hours"],
                "per_target_metrics": [
                    {"target": item["design"]["target"],
                     "sampled_rows": item["metrics"]["sample_count"],
                     "awp_j2_median_separation_km": item["metrics"]["awp_j2_vs_cpf"]["median_km"],
                     "sgp4_median_separation_km": item["metrics"]["sgp4_vs_cpf"]["median_km"],
                     "awp_minus_sgp4_date_clustered_ci95_km": item["metrics"]["awp_minus_sgp4_separation_ci95_date_clustered_km"]}
                    for item in awp_cpf["targets"]],
                "interpretation": awp_cpf["interpretation"],
            },
            "awp_j2_drag_against_ilrs_cpf": {
                "status": awp_cpf_drag["status"],
                "independent_audit_status": awp_cpf_drag_audit["status"],
                "targets": len(awp_cpf_drag["targets"]),
                "sampled_rows": awp_cpf_drag_audit["response_rows_checked"],
                "area_mass_m2_kg": awp_cpf_drag["drag_assumptions"]["area_mass_m2_kg"],
                "paired_drag_vs_j2_results": awp_cpf_drag_audit["target_results"],
                "interpretation": awp_cpf_drag["interpretation"],
            },
            "fresh_recomputed_awp_j2_drag_against_ilrs_cpf": {
                "status": "completed_bit_for_bit_reproduction",
                "targets": len(awp_cpf_drag_rerun["targets"]),
                "sampled_rows": sum(item["design"]["sampled_rows"]
                                     for item in awp_cpf_drag_rerun["targets"]),
                "target_output_hashes_match_saved_campaign": True,
                "target_metrics_match_saved_campaign": True,
                "interpretation": "Fresh AWP numerical integrations exactly reproduced the archived position rows and summary metrics for four ILRS CPF targets; this confirms reproducibility, not physical-model accuracy.",
            },
            "awp_iers_earth_constants_against_ilrs_cpf": {
                "status": awp_cpf_iers["status"],
                "independent_audit_status": awp_cpf_iers_audit["status"],
                "earth_constants": awp_cpf_iers["earth_constants"],
                "targets": len(awp_cpf_iers["targets"]),
                "sampled_rows": awp_cpf_iers_audit["response_rows_checked"],
                "per_target_metrics": [
                    {"target": item["design"]["target"],
                     "awp_median_separation_km": item["metrics"]["awp_j2_vs_cpf"]["median_km"],
                     "sgp4_median_separation_km": item["metrics"]["sgp4_vs_cpf"]["median_km"],
                     "awp_minus_sgp4_date_clustered_ci95_km": item["metrics"]["awp_minus_sgp4_separation_ci95_date_clustered_km"]}
                    for item in awp_cpf_iers["targets"]],
                "interpretation": "Using IERS Earth constants corrects most of the AWP error for three high-altitude ILRS targets; SGP4 remains closer for all four sampled targets, and Starlette remains poorly matched.",
            },
            "dense_historical_sgp4_against_ilrs_cpf": {
                "status": dense_sgp4_cpf["status"],
                "targets": dense_sgp4_cpf["target_count"],
                "observation_rows": dense_sgp4_cpf["response_rows_checked"],
                "per_target_metrics": [
                    {"target": item["target"], "norad_id": item["norad_id"],
                     "rows": item["rows_checked"], "date_clusters": item["date_clusters"],
                     "metrics": item["metrics"]}
                    for item in dense_sgp4_cpf["targets"]],
                "interpretation": dense_sgp4_cpf["interpretation"],
            },
            "dust_anchored_detection_dropout_sensitivity": {
                "status": dust_detection["status"],
                "independent_audit_status": dust_detection_audit["status"],
                "conditional_frame_continuity_anchor": 0.9890,
                "session_cluster_ci95": [0.9762, 0.9972],
                "quarterly_dates": len(dust_detection["dates"]),
                "audited_treatment_rows_per_probability": 6800,
                "treatment_probabilities": [
                    {"probability": probability,
                     "burst_dropout_custody_change_pp_by_regime": {
                         regime: {
                             "mean": 100 * dust_detection["results"][f"pbase-{probability:.2f}"]["effects"][f"{regime}:burst:custody_continuity"]["date_clustered_mean_change"],
                             "ci95_half_width": 100 * dust_detection["results"][f"pbase-{probability:.2f}"]["effects"][f"{regime}:burst:custody_continuity"]["date_clustered_ci95_half_width"],
                         } for regime in ("leo", "meo", "geo", "heo")
                     }} for probability in dust_detection["probability_levels"]
                ],
                "interpretation": dust_detection["interpretation_note"],
            },
            "buaa_recall_anchored_detection_dropout_sensitivity": {
                "status": buaa_recall_sensitivity["status"],
                "independent_audit_status": buaa_recall_sensitivity_audit["status"],
                "probabilities": buaa_recall_sensitivity["probability_levels"],
                "audited_treatment_rows_per_probability": 6800,
                "date_clusters": buaa_recall_sensitivity_audit["date_clusters"],
                "burst_dropout_custody_change_pp_by_regime": {
                    f"{probability:.2f}": {
                        regime: {
                            "mean": 100 * buaa_recall_sensitivity["results"][f"pbase-{probability:.2f}"]["effects"][f"{regime}:burst:custody_continuity"]["date_clustered_mean_change"],
                            "ci95_half_width": 100 * buaa_recall_sensitivity["results"][f"pbase-{probability:.2f}"]["effects"][f"{regime}:burst:custody_continuity"]["date_clustered_ci95_half_width"],
                        } for regime in ("leo", "meo", "geo", "heo")
                    } for probability in buaa_recall_sensitivity["probability_levels"]
                },
                "interpretation": buaa_recall_sensitivity["interpretation_note"],
            },
            "dust_annotation_gap_burst_persistence": {
                "status": dust_persistence["status"],
                "independent_audit_status": dust_persistence_audit["status"],
                "conditional_internal_span_frames": dust_persistence["conditional_internal_span_frames"],
                "unlabeled_internal_frames": dust_persistence["unlabeled_internal_frames"],
                "internal_gap_runs": dust_persistence["internal_gap_runs"],
                "persistence_proxy": dust_persistence["failure_state_persistence_proxy"],
                "session_cluster_bootstrap_ci95": dust_persistence["session_cluster_bootstrap_ci95"],
                "interpretation": dust_persistence["interpretation"],
            },
        },
        "remaining_gaps": {
            "original_GoDSAT_implementation_available": original_available,
            "natural_dropout_measured_from_attempt_denominator": natural_dropout_measured,
            "complete_continuous_tasking_replay_for_all_catalog_objects": False,
            "catalog_wide_attitude_history_available": False,
            "note": "The catalog ephemeris covers all catalog objects at four-hour cadence, but catalog-wide attitude histories are unavailable; the new CASSIOPE telemetry is one spacecraft only. The trained DOE policy uses 18 targets; separate greedy references replay all fresh targets for one hour at 208 weekly dates and 48 monthly dates with six hosts, with an added second random seed for the monthly capacity experiment, and at 17 quarterly dates with nested six/12/up-to-24-host teams. These are not continuous four-year operations, and active-host history is backcast from a current snapshot. CASSIOPE attitude-solution dropout is not a ground-sensor missed-attempt denominator; sensor payloads and injected tasking dropout remain hypothetical.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/full-system-audit.json",
                        help="JSON report path, relative to the project root unless absolute")
    parser.add_argument("--skip-dust-source-recompute", action="store_true",
                        help="Use the saved independent DUST source audit without reopening its large archive")
    args = parser.parse_args()
    result = audit(recompute_dust_source=not args.skip_dust_source_recompute)
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(output),
                      "evidence_sections": list(result["evidence"]),
                      "remaining_gaps": result["remaining_gaps"]}, indent=2))


if __name__ == "__main__":
    main()
