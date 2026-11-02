from godsat.design import FACTORS
from scripts.figures.render_campaign_report import correct_screening_table


def test_screening_effects_are_paired_with_correct_response_labels():
    analyses = {"custody_continuity": {"main_effects": {factor: 0.2 for factor in FACTORS}},
                "objective": {"main_effects": {factor: -0.7 for factor in FACTORS}},
                "gpu_hours": {"main_effects": {factor: 0.0 for factor in FACTORS}}}
    report = "# Results\n\n| Factor | Wrong label |\n|---|---|\n| learning_rate | 999 |\n\nNext section\n"
    corrected = correct_screening_table(report, analyses)
    assert "| Factor | Objective effect | Custody effect | GPU-hours effect |" in corrected
    assert "| learning_rate | -0.700000 | 0.200000 | 0.000000 |" in corrected
    assert "Wrong label" not in corrected
    assert corrected.endswith("Next section\n")
