from scripts.data import finalize_state_vectors as pipeline


def test_finalization_builds_source_coverage_before_object_index(monkeypatch, tmp_path):
    stages = []
    monkeypatch.setattr(pipeline, "require_complete_export", lambda root: {"records_written": 3})
    monkeypatch.setattr(pipeline, "verify_final_artifacts", lambda root, manifest: {"status": "finalized"})

    def run(script, *args, root):
        if script == "index_state_vector_coverage.py":
            assert "audit.py" in stages
        stages.append(script)

    monkeypatch.setattr(pipeline, "run", run)
    assert pipeline.finalize(tmp_path)["status"] == "finalized"
    assert stages == ["validate_state_vectors.py", "audit.py", "index_state_vector_coverage.py"]
