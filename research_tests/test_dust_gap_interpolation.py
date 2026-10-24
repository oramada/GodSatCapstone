from scripts.audit_dust_gap_interpolation import summarize


def test_gap_interpolation_summary_clusters_uncertainty_by_session():
    errors = [
        {"session": "s1", "track_id": 1, "gap_length_frames": 1, "error_px": 1.0},
        {"session": "s1", "track_id": 2, "gap_length_frames": 1, "error_px": 1.5},
        {"session": "s2", "track_id": 1, "gap_length_frames": 1, "error_px": 8.0},
    ]

    result = summarize(errors, 1, replicates=500)

    assert result["validated_hidden_frames"] == 3
    assert result["tracks"] == 3
    assert result["sessions"] == 2
    assert result["fraction_within_2px"] == 2 / 3
    assert result["equal_session_fraction_within_2px"] == 0.5
    assert result["session_bootstrap_replicates"] == 500
