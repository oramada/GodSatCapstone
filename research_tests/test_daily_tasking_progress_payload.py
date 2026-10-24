import json
import hashlib

import pytest

from godsat.server import full_catalog_daily_tasking_progress_payload


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def make_fixture(root):
    folder = root / "outputs/full-catalog-tasking-daily-2022-2026"
    hashes = {}
    for regime in ("leo", "meo", "geo", "heo"):
        relative = f"cells/2022-10-15/{regime}.json"
        cell = folder / relative
        cell.parent.mkdir(parents=True, exist_ok=True)
        cell.write_text(json.dumps({"regime": regime}))
        hashes[relative] = hashlib.sha256(cell.read_bytes()).hexdigest()
    write_json(folder / "progress.json", {
        "status": "running_checkpointed", "final_results": False,
        "complete_date_count": 2, "expected_date_count": 1456,
        "verified_completed_date_regime_groups": 8,
        "expected_date_regime_groups": 5824,
        "completed_date_range": ["2022-10-15T00:00:00Z", "2022-10-16T00:00:00Z"],
        "cell_files_sha256": hashes,
    })
    write_json(folder / "completed_prefix_audit.json", {
        "status": "passed_completed_prefix_independent_audit", "dates_checked": 1,
        "date_range": ["2022-10-15", "2022-10-15"],
        "paired_date_regime_cells_checked": 4, "response_rows_checked": 8,
        "cell_files_sha256": hashes,
    })
    write_json(folder / "preliminary_prefix_effects.json", {
        "status": "preliminary_audited_prefix_effects",
        "prefix_audit_status": "passed_completed_prefix_independent_audit", "dates": 1,
        "effects": {r: {"custody_continuity": {"mean_change": -0.001,
            "date_cluster_ci95": [-0.002, -0.0001]}} for r in ("leo", "meo", "geo", "heo")},
    })
    return folder


def test_daily_progress_distinguishes_checkpoint_from_audited_prefix(tmp_path):
    make_fixture(tmp_path)
    payload = full_catalog_daily_tasking_progress_payload(tmp_path)
    assert payload["completed_dates"] == 2
    assert payload["audited_dates"] == 1
    assert payload["audited_cells"] == 4
    assert payload["final_results"] is False
    assert set(payload["custody_effects"]) == {"leo", "meo", "geo", "heo"}


def test_daily_progress_rejects_mismatched_audit_hashes(tmp_path):
    folder = make_fixture(tmp_path)
    audit_path = folder / "completed_prefix_audit.json"
    audit = json.loads(audit_path.read_text())
    audit["cell_files_sha256"]["cells/2022-10-15/leo.json"] = "wrong"
    audit_path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match="matches its independent audit hash"):
        full_catalog_daily_tasking_progress_payload(tmp_path)
