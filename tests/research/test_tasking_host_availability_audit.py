import numpy as np
import pytest

from scripts.validation import audit_full_catalog_tasking as audit


class FakeHistory:
    class _DB:
        def close(self):
            pass

    db = _DB()

    def replay(self, ids, times, max_age_hours):
        states = np.zeros((len(times), len(ids), 6), dtype=float)
        states[:, :, 0] = 7000.0
        ages = np.zeros((len(times), len(ids)), dtype=float)
        errors = np.zeros((len(times), len(ids)), dtype=np.int16)
        states[3, 0, :3] = np.nan
        return states, ages, errors, None

def test_host_availability_audit_recomputes_missing_steps_from_archived_states(monkeypatch):
    date = "2025-01-01T00:00:00+00:00"
    monkeypatch.setattr(audit, "monthly_dates", lambda: [date])
    monkeypatch.setattr(audit, "History", lambda *_args, **_kwargs: FakeHistory())
    hosts = {date: {regime: [17] for regime in audit.REGIMES}}
    rows = {
        (date.replace("+00:00", "Z"), regime, rate): {"host_state_missing_agent_steps": 1}
        for regime in audit.REGIMES for rate in audit.RATES
    }

    result = audit.recompute_host_state_availability(rows, hosts, {
        "step_seconds": 60, "max_element_age_hours": 72,
    })

    assert result["cells_recomputed"] == 4
    assert result["missing_agent_steps_by_host_regime"] == {regime: 1 for regime in audit.REGIMES}
    assert result["missing_agent_steps_total"] == 4


def test_host_availability_audit_rejects_a_saved_count_that_disagrees_with_states(monkeypatch):
    date = "2025-01-01T00:00:00+00:00"
    monkeypatch.setattr(audit, "monthly_dates", lambda: [date])
    monkeypatch.setattr(audit, "History", lambda *_args, **_kwargs: FakeHistory())
    hosts = {date: {regime: [17] for regime in audit.REGIMES}}
    rows = {
        (date.replace("+00:00", "Z"), regime, rate): {"host_state_missing_agent_steps": 0}
        for regime in audit.REGIMES for rate in audit.RATES
    }

    with pytest.raises(ValueError, match="Host-state availability differs"):
        audit.recompute_host_state_availability(rows, hosts, {
            "step_seconds": 60, "max_element_age_hours": 72,
        })
