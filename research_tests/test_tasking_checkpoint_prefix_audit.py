import datetime as dt
import json

import numpy as np

from scripts import audit_tasking_checkpoint_prefix as audit
from scripts import audit_full_catalog_tasking as full_audit


def test_prefix_audit_verifies_cells_and_normalizes_dates(tmp_path, monkeypatch):
    date = "2025-01-01"
    output = tmp_path / "run"
    cells = output / "cells" / date
    cells.mkdir(parents=True)
    config = {
        "agents": 6, "targets": 18, "duration_minutes": 60,
        "step_seconds": 60, "max_element_age_hours": 72,
        "max_range_km": 5000, "sensor_cohort": "current_payload",
        "target_cohort": "all", "propagation_model": "sgp4",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit, "cache_key", lambda _date, cfg, regime: f"scenario-{cfg['targets']}-{regime}"
    )
    monkeypatch.setattr(audit, "sha256", lambda _path: "source-hash")
    monkeypatch.setattr(audit, "verify_rows", lambda rows, dates: rows)
    monkeypatch.setattr(
        audit, "recompute_host_state_availability",
        lambda _rows, hosts, _config, dates: {
            "cells_recomputed": len(dates), "hosts": hosts,
        },
    )
    (tmp_path / "outputs/all-orbits-paper-exact-active-hosts").mkdir(parents=True)
    (tmp_path / "outputs/all-orbits-paper-exact-active-hosts/config.json").write_text(
        json.dumps(config)
    )

    hosts = [1, 2, 3, 4, 5, 6]
    for regime in audit.REGIMES:
        # This date uses the live runner's one-target fallback scenario.
        scenario = tmp_path / f"data/scenarios/scenario-1-{regime}.npz"
        scenario.parent.mkdir(parents=True, exist_ok=True)
        np.savez(scenario, ids=np.asarray(hosts))
        scenario.with_suffix(".json").write_text(json.dumps({"agents": hosts}))
        rows = []
        for rate in (0.0, 0.2):
            rows.append({
                "date": date + "T00:00:00Z",
                "orbit_regime_sensor_hosts": regime,
                "requested_outage_rate": rate,
                "sensor_host_ids": hosts,
                "step_count": 60,
                "step_seconds": 60,
            })
        (cells / f"{regime}.json").write_text(json.dumps({
            "simulator_version": 2, "source_sha256": "source-hash", "rows": rows,
        }))

    result = audit.audit_prefix(output)

    assert result["dates_checked"] == 1
    assert result["paired_date_regime_cells_checked"] == 4
    assert result["response_rows_checked"] == 8
    assert set(result["scenario_target_counts"].values()) == {1}
    assert result["independent_historical_host_state_replay"]["hosts"] == {
        date + "T00:00:00Z": {regime: hosts for regime in audit.REGIMES}
    }
