from scripts.audit_pdf_completion_matrix import reconcile


def test_completion_matrix_maps_paper_and_open_extensions():
    result = reconcile()

    assert result["status"] == "reconciled_open_requirements"
    assert result["source_pdf"]["pages"] == 6
    assert result["pdf_contains_drop_out_term"] is False
    assert len(result["requirements"]) == 10
    statuses = {item["status"] for item in result["requirements"]}
    assert "running_checkpointed" in statuses
    assert "not_satisfied_by_available_workspace_evidence" in statuses

    progress = result["daily_campaign_progress"]
    assert progress["runner_completed_groups"] >= progress["independently_audited_groups"]
    assert progress["audit_status"] == "passed_completed_prefix_independent_audit"
    assert progress["independently_audited_response_rows"] == (
        2 * progress["independently_audited_groups"]
    )
