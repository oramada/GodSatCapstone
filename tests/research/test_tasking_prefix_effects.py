import json
import hashlib

import pytest

from scripts.analysis.analyze_tasking_checkpoint_prefix import analyze
from scripts.validation.audit_full_catalog_tasking import REGIMES


def test_prefix_effects_use_only_audited_cells(tmp_path):
    output = tmp_path / "run"
    days = ["2025-01-01", "2025-01-02"]
    cells = output / "cells"
    cell_hashes = {}
    for day in days:
        (cells / day).mkdir(parents=True)
        for regime in REGIMES:
            payload = {"rows": [
                {"requested_outage_rate": 0.0, "custody_continuity": .9,
                 "observable_custody": .8, "mean_slew_energy_proxy": .2,
                 "catalog_objects_in_episode": 18, "valid_target_fraction": .5,
                 "target_observable_step_count": 4, "target_valid_step_count": 8,
                 "sensor_actions": 0, "detections": 0},
                {"requested_outage_rate": .2, "custody_continuity": .89,
                 "observable_custody": .78, "mean_slew_energy_proxy": .21,
                 "catalog_objects_in_episode": 18, "valid_target_fraction": .5,
                 "target_observable_step_count": 4, "target_valid_step_count": 8,
                 "sensor_actions": 0, "detections": 0},
            ]}
            rel = f"cells/{day}/{regime}.json"
            cell_path = output / rel
            cell_path.write_text(json.dumps(payload))
            cell_hashes[rel] = hashlib.sha256(cell_path.read_bytes()).hexdigest()
    audit = {
        "status": "passed_completed_prefix_independent_audit",
        "dates_checked": 2, "date_range": days,
        "paired_date_regime_cells_checked": 8,
        "cell_files_sha256": cell_hashes,
    }
    (output / "completed_prefix_audit.json").write_text(json.dumps(audit))

    result = analyze(output, replicates=50)

    assert result["status"] == "preliminary_audited_prefix_effects"
    assert result["dates"] == 2
    assert result["effects"]["leo"]["custody_continuity"]["mean_change"] == pytest.approx(-.01)
    assert result["baseline_context"]["leo"]["mean_catalog_objects_per_episode"] == 18
    assert result["baseline_context"]["leo"]["mean_sensor_actions_per_hour"] == 0
    assert "not natural ground-sensor" in result["interpretation_limit"]


def test_prefix_effects_require_cells_covered_by_audit(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    (output / "completed_prefix_audit.json").write_text(json.dumps({
        "status": "passed_completed_prefix_independent_audit",
        "dates_checked": 1, "date_range": ["2025-01-01", "2025-01-01"],
        "paired_date_regime_cells_checked": 4, "cell_files_sha256": {},
    }))
    with pytest.raises(ValueError, match="covered by the independent audit"):
        analyze(output, replicates=20)
