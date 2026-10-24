#!/usr/bin/env python3
"""Reconcile each explicit supplied-PDF study requirement with saved evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from godsat.orbits import ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reconcile(root: Path = ROOT) -> dict:
    pdf = root / "Systematic_Hyperparameter_Optimization_of_GoDSAT_Sensor_Tasking_Agents_via_Fractional_Factorial_Design_and_Response_Surface_Methodology.pdf"
    execution = root / "outputs/full-paper-study"
    paper = json.loads((execution / "summary.json").read_text())
    system = json.loads((root / "outputs/full-system-audit.json").read_text())
    daily_path = root / "outputs/full-catalog-tasking-daily-2022-2026/progress.json"
    daily = json.loads(daily_path.read_text()) if daily_path.exists() else None
    prefix_path = root / "outputs/full-catalog-tasking-daily-2022-2026/completed_prefix_audit.json"
    prefix = json.loads(prefix_path.read_text()) if prefix_path.exists() else None
    effects_path = root / "outputs/full-catalog-tasking-daily-2022-2026/preliminary_prefix_effects.json"
    effects = json.loads(effects_path.read_text()) if effects_path.exists() else None
    # Keep runner completion separate from independent validation. The runner
    # may advance while the (more expensive) source and historical-state replay
    # audit is running, so a single "progress" count can overstate evidence.
    campaign_progress = None
    if daily:
        campaign_progress = {
            "status": daily.get("status"),
            "expected_groups": daily.get("expected_date_regime_groups"),
            "runner_completed_groups": daily.get("completed_date_regime_groups"),
            "runner_completed_dates": daily.get("complete_date_count"),
            "runner_completed_range": daily.get("completed_date_range"),
            "independently_audited_groups": (
                prefix.get("paired_date_regime_cells_checked") if prefix else 0
            ),
            "independently_audited_dates": prefix.get("dates_checked") if prefix else 0,
            "independently_audited_response_rows": (
                prefix.get("response_rows_checked") if prefix else 0
            ),
            "independently_audited_range": prefix.get("date_range") if prefix else None,
            "audit_status": prefix.get("status") if prefix else "not_run",
        }
    gaps = system.get("remaining_gaps", {})
    # The supplied PDF was extracted with system Python's pypdf during this
    # audit; avoid making pypdf an undeclared project-runtime dependency.
    page_count = 6
    contains_dropout = False
    items = [
        {
            "pdf_section": "3.1-3.2; 4",
            "requirement": "Randomized 16-run 2^(7-3) resolution-IV screening at all seven stated low/high factor levels; estimate main and aliased effects for the four responses.",
            "evidence": ["outputs/full-paper-study/screening_design.csv", "outputs/full-paper-study/screening_analysis.json", "outputs/full-paper-study/summary.json"],
            "status": "executed_in_replacement_implementation" if paper.get("screening_runs") == 16 else "incomplete",
            "limitations": ["The available GoDSAT MATLAB source and pretrained assets are absent; this is not an exact GoDSAT reproduction."],
        },
        {
            "pdf_section": "3.2; 4",
            "requirement": "Select the three influential factors from screening and document alias/half-normal analysis.",
            "evidence": ["outputs/full-paper-study/screening_analysis.json", "outputs/full-paper-study/summary.json"],
            "status": "executed_in_replacement_implementation" if len(paper.get("selected_factors", [])) == 3 else "incomplete",
            "selected_factors": paper.get("selected_factors"),
            "limitations": ["Selected factors follow replacement-study response data and are not claimed to match the paper's unsupported narrative selection."],
        },
        {
            "pdf_section": "3.3; 4",
            "requirement": "Run a 15-treatment face-centered CCD; fit quadratic response surfaces; assess pure error, lack of fit, residuals, stationary point and ridge recommendation.",
            "evidence": ["outputs/full-paper-study-15-run/", "outputs/full-paper-study-center-replication/", "outputs/full-paper-study/response_surfaces.json", "outputs/full-paper-study/anova_all_responses.json", "outputs/full-paper-study/coefficient_uncertainty_all_responses.json"],
            "status": "executed_with_augmented_replication_and_model_adequacy_caveats",
            "limitations": ["The exact 15-run budget alone has no replicated center; augmented center replication provides pure error, and four-regime active-host diagnostics reject quadratic adequacy for objective and custody."],
        },
        {
            "pdf_section": "3.4; 4",
            "requirement": "Validate recommended policy with five independent seeds against the original baseline and equal-compute-budget Bayesian reference; report custody, slew, false tracks, compute and metadata.",
            "evidence": ["outputs/all-orbits-paper-exact/summary.json", "outputs/all-orbits-paper-exact/validation.csv", "outputs/multi-date-robustness-monthly-active-hosts/independent_integrity_audit.json"],
            "status": "replacement_policy_comparison_executed_claimed_gains_not_reproduced",
            "limitations": ["Original baseline configuration and policy assets are unavailable; confidence intervals do not establish the paper's stated custody or slew improvements."],
        },
        {
            "pdf_section": "3.5",
            "requirement": "Record randomized execution, fixed seeds, software/node/energy metadata, wall time and GPU-hours for every treatment.",
            "evidence": ["outputs/full-paper-study/replay.json", "outputs/full-paper-study/runs/", "outputs/full-paper-study/summary.json"],
            "status": "partially_recorded",
            "limitations": ["CPU wall-time and environment/checkpoint metadata are recorded; GPU-hours are unavailable for CPU campaigns, and original distributed-node/energy telemetry cannot be reconstructed."],
        },
        {
            "pdf_section": "4; 5",
            "requirement": "Provide numerical tables, main-effect and half-normal plots, ANOVA, contours/ridge diagnostics, validation and release response data.",
            "evidence": ["outputs/full-paper-study/final_execution_report.md", "outputs/full-paper-study/plots/", "outputs/full-paper-study/responses.csv", "outputs/full-paper-study/PDF_execution_audit.md"],
            "status": "replacement_study_artifacts_present_pdf_results_placeholder",
            "limitations": ["The PDF says its own Section 4 numerical results and Section 5 data release are placeholders/future work; current artifacts document a replacement experiment."],
        },
        {
            "pdf_section": "user_requested_extension",
            "requirement": "Evaluate sensitivity to sensor dropout using real observation outcomes where available and clearly distinguish simulated interventions.",
            "evidence": ["outputs/full-catalog-tasking-epop-empirical-block-weekly-2022-2026/", "outputs/dust-annotation-gap-dropout-sensitivity/", "outputs/full-system-audit.json"],
            "status": "simulated_sensitivity_executed_natural_ground_dropout_not_estimable",
            "limitations": ["No source has a reconciled planned/attempted ground-observation denominator with failures. Sensor dropout effectiveness cannot be measured as a real-world rate."],
        },
        {
            "pdf_section": "user_requested_extension",
            "requirement": "Use historical catalog orbit data, a realistic propagator and validate state/orbit outputs.",
            "evidence": ["data/raw/manifest.json", "outputs/catalog-trajectory-all-4hour-2022-2026/validation.json", "outputs/awp-ilrs-cpf-iers-earth-constants-2022-2026/independent_audit.json", "outputs/full-system-audit.json"],
            "status": "four_year_four_hour_catalog_reconstructed_and_validated_awp_sensitivity_validated",
            "limits": ["This is a four-hour historical TLE/GP reconstruction, not precision ephemeris or catalog-wide attitude. AWP orbital differences versus CPF were evaluated; SGP4 is closer for the four laser-ranged targets."],
        },
        {
            "pdf_section": "user_requested_extension",
            "requirement": "Run complete daily all-catalog tasking comparison over the four-year history with paired outage treatments.",
            "evidence": ["outputs/full-catalog-tasking-daily-2022-2026/progress.json", "outputs/full-catalog-tasking-daily-2022-2026/cells/"],
            "status": "running_checkpointed" if daily and daily.get("status") == "running_checkpointed" else "not_complete",
            "progress": daily,
            "independently_audited_prefix": prefix,
            "preliminary_prefix_effects": effects,
            "limitations": ["This remains 60 minutes sampled at each daily UTC epoch, not continuous sensor tasking. The main runner may need resumption after interruption; cell outputs are checkpointed."],
        },
        {
            "pdf_section": "system_level_blockers",
            "requirement": "Exact original GoDSAT reproduction, all-spacecraft attitude coverage, measured natural ground dropout, and continuous four-year all-catalog tasking.",
            "evidence": ["outputs/full-system-audit.json"],
            "status": "not_satisfied_by_available_workspace_evidence",
            "unresolved": {key: value for key, value in gaps.items() if key != "note"},
            "limitations": [gaps.get("note", "See full-system audit for evidence gaps.")],
        },
    ]
    return {
        "status": "reconciled_open_requirements",
        "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "source_pdf": {"path": str(pdf.relative_to(root)), "sha256": sha256(pdf), "pages": 6},
        "system_audit_status": system.get("status"),
        "full_paper_summary_status": paper.get("status"),
        "pdf_contains_drop_out_term": contains_dropout,
        "pdf_page_count": page_count,
        "daily_campaign_progress": campaign_progress,
        "requirements": items,
        "interpretation": "This matrix maps the supplied paper and user-requested extensions to current workspace artifacts. It distinguishes completed replacement-study evidence from original-GoDSAT reproduction and external data requirements that are not met.",
    }


if __name__ == "__main__":
    result = reconcile()
    target = ROOT / "outputs/full-paper-study/current_completion_matrix.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "requirements": len(result["requirements"]),
                      "system_audit_status": result["system_audit_status"],
                      "daily_campaign_status": result["requirements"][-2]["status"],
                      "output": str(target)}, indent=2))
