from scripts.analysis.analyze_dust_dropout import (
    audit_replay_csv, measure, outage_masks, summarize_internal_track_gaps,
    summarize_gap_custody_sensitivity,
)


def test_measure_counts_retention_and_grace_period_custody():
    session = {"tracks": {1: [1, 2, 3, 4, 5]}}
    # One-based frame numbers; frames 2 and 4 are lost.
    mask = [False, True, False, True, False]

    strict = measure(session, mask, grace_frames=1)
    tolerant = measure(session, mask, grace_frames=2)

    assert strict["detections_retained"] == 3
    assert strict["detection_retention"] == 0.6
    assert strict["injected_loss_rate_observed"] == 0.4
    assert strict["custody_continuity"] == 1.0
    assert tolerant["custody_continuity"] == 1.0
    assert tolerant["track_gap_fragments"] == 0


def test_measure_includes_internal_unlabeled_frames_in_zero_loss_baseline():
    session = {"tracks": {1: [1, 3, 4]}}
    no_loss = measure(session, [False] * 4, grace_frames=0)
    one_second = measure(session, [False] * 4, grace_frames=1)

    assert no_loss["internal_transit_frame_opportunities"] == 4
    assert no_loss["detections_retained"] == 3
    assert no_loss["detection_retention"] == 0.75
    assert no_loss["custody_continuity"] == 0.75
    assert one_second["custody_continuity"] == 1.0


def test_gap_fragment_requires_exceeding_the_grace_window():
    session = {"tracks": {1: [1, 3]}}
    mask = [False, True, False]

    assert measure(session, mask, grace_frames=1)["track_gap_fragments"] == 0


def test_outage_masks_are_reproducible_and_zero_rate_has_no_outages():
    assert outage_masks(100, 0.2, "burst", seed=11) == outage_masks(100, 0.2, "burst", seed=11)
    assert outage_masks(100, 0.0, "independent", seed=11) == [False] * 100


def test_internal_track_gap_summary_uses_censored_first_to_last_spans():
    sessions = {"s": {"tracks": {1: [1, 2, 4, 5], 2: [10, 12]}}}
    summary = summarize_internal_track_gaps(sessions)

    assert summary["expected_internal_transit_frames"] == 8
    assert summary["recorded_track_detections"] == 6
    assert summary["unannotated_internal_frames"] == 2
    assert summary["recorded_frame_fraction"] == 6 / 8
    assert summary["transits_with_internal_gaps"] == 2
    assert summary["internal_gap_length_frames"] == {"1": 2}
    low, high = summary["recorded_frame_fraction_session_bootstrap_ci95"]
    assert 0 <= low <= high <= 1


def test_gap_custody_sensitivity_treats_observed_gaps_as_counterfactual_misses():
    sessions = {"s": {"tracks": {1: [1, 15]}}}
    result = summarize_gap_custody_sensitivity(sessions, (1, 5, 10), draws=200)

    rows = result["results"]
    assert [row["observed_custody_equal_session_mean"] for row in rows] == [0.2, 7 / 15, 0.8]
    assert [row["gap_filled_custody_equal_session_mean"] for row in rows] == [1.0, 1.0, 1.0]
    expected = [-80.0, -100 * 8 / 15, -20.0]
    actual = [row["observed_minus_gap_filled_custody_percentage_points"] for row in rows]
    assert all(abs(a - e) < 1e-12 for a, e in zip(actual, expected))
    assert all(row["observed_track_gap_fragments"] == 1 for row in rows)
    assert all(row["gap_filled_track_gap_fragments"] == 0 for row in rows)
    assert "not natural dropout attribution" in result["assumption"]


def test_persisted_replay_audit_checks_design_and_session_denominators(tmp_path):
    import csv

    path = tmp_path / "replays.csv"
    fields = ["replicate", "session", "mode", "requested_dropout_rate", "grace_seconds",
              "internal_transit_frame_opportunities", "detection_retention",
              "injected_loss_rate_observed", "track_survival", "custody_continuity", "tracks"]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"replicate": 0, "session": "s", "mode": "independent",
            "requested_dropout_rate": 0.0, "grace_seconds": 1,
            "internal_transit_frame_opportunities": 3, "detection_retention": 1.0,
            "injected_loss_rate_observed": 0.0, "track_survival": 1.0,
            "custody_continuity": 1.0, "tracks": 1})
        writer.writerow({"replicate": 0, "session": "s", "mode": "independent",
            "requested_dropout_rate": 0.2, "grace_seconds": 1,
            "internal_transit_frame_opportunities": 3, "detection_retention": 0.8,
            "injected_loss_rate_observed": 0.2, "track_survival": 1.0,
            "custody_continuity": 1.0, "tracks": 1})

    audit = audit_replay_csv(path, {"s": 3}, 1, (0.0, 0.2), ("independent",), (1,))
    assert audit["status"] == "completed"
    assert audit["expected_rows"] == audit["observed_rows"] == 2
    assert audit["missing_rows"] == audit["duplicate_rows"] == 0

    incomplete = audit_replay_csv(path, {"s": 4}, 1, (0.0, 0.2, 0.4),
                                  ("independent",), (1,))
    assert incomplete["status"] == "invalid"
    assert incomplete["missing_rows"] == 1
    assert incomplete["session_opportunity_mismatches"] == 2
