from scripts.audit_ztf_real_image_path_associations import audit


def test_real_image_path_association_reports_signal_and_keeps_truth_limit_explicit():
    sample = {
        "image_results": [{
            "expid": "e1",
            "candidate_results": [{
                "norad_id": 10,
                "pixel_profile_vs_parallel_controls": {
                    "samples": 20,
                    "centerline_median_excess_adu": 4.0,
                    "offset_profile": [
                        {"shift_px": -10.0, "median_excess_adu": 1.0},
                        {"shift_px": 0.0, "median_excess_adu": 7.0},
                        {"shift_px": 10.0, "median_excess_adu": 2.0},
                    ],
                },
            }, {
                "norad_id": 11,
                "pixel_profile_vs_parallel_controls": {"samples": 0},
            }],
        }],
        "opportunity_count": 2,
    }
    result = audit(sample, "fixture-hash")

    assert result["selection_and_measurement"]["profiled_opportunities"] == 1
    assert result["summary"]["predicted_band_peak_exceeds_both_parallel_control_bands"] == 1
    assert result["summary"]["peak_exactly_on_predicted_centerline"] == 1
    assert result["summary"]["image_cluster_bootstrap_95pct_interval_adu"] == [5.0, 5.0]
    assert "not independent identity labels" in result["interpretation_limit"]
