from scripts.experiments.replicate_rsm_center import lack_of_fit_interpretation


def test_lack_of_fit_report_uses_current_p_values_instead_of_prior_run_claims():
    surfaces = {"objective": {"lack_of_fit": {"p_value": 0.076}},
                "custody_continuity": {"lack_of_fit": {"p_value": 0.008}},
                "gpu_hours": {"lack_of_fit": {"available": False}}}
    text = lack_of_fit_interpretation(surfaces)
    assert "rejected for: custody_continuity." in text
    assert "not rejected for: objective." in text
    assert "not estimable for: gpu_hours." in text
    assert "does not establish model adequacy" in text
