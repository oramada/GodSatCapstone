import datetime as dt

import numpy as np
import pytest

from godsat import scenario


def test_awp_scenario_replay_restarts_at_new_element_and_does_not_bridge_gaps(monkeypatch):
    times = [dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
             + dt.timedelta(minutes=i) for i in range(4)]
    states = np.arange(4 * 6, dtype=float).reshape(4, 1, 6)
    states[2] = np.nan
    epochs = np.array([['element-a'], ['element-a'], [''], ['element-b']])
    transformed = []
    propagated = []

    def fake_transform(state, when):
        transformed.append((state.copy(), when))
        return state + 100

    def fake_propagate(state, seconds, offsets, **kwargs):
        propagated.append((state.copy(), seconds, offsets.copy(), kwargs))
        return np.tile(state, (len(offsets), 1)) + offsets[:, None]

    monkeypatch.setattr(scenario, 'teme_to_gcrs', fake_transform)
    monkeypatch.setattr(scenario, 'awp_propagate', fake_propagate)

    result = scenario.replay_with_awp_j2(states, epochs, times, 60)

    assert len(transformed) == 2
    assert len(propagated) == 1
    np.testing.assert_array_equal(propagated[0][2], [0, 60])
    np.testing.assert_allclose(result[0, 0], states[0, 0] + 100)
    np.testing.assert_allclose(result[1, 0], states[0, 0] + 160)
    assert np.isnan(result[2, 0]).all()
    np.testing.assert_allclose(result[3, 0], states[3, 0] + 100)


def test_awp_scenario_replay_rejects_an_irregular_time_grid():
    times = [dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
             dt.datetime(2026, 1, 1, 0, 1, tzinfo=dt.timezone.utc),
             dt.datetime(2026, 1, 1, 0, 3, tzinfo=dt.timezone.utc)]
    states = np.ones((3, 1, 6))
    epochs = np.full((3, 1), 'element-a')
    with pytest.raises(ValueError, match='strictly spaced'):
        scenario.replay_with_awp_j2(states, epochs, times, 60)


def test_awp_solar_lunar_replay_passes_each_arc_epoch(monkeypatch):
    times = [dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
             + dt.timedelta(minutes=i) for i in range(3)]
    states = np.ones((3, 1, 6))
    epochs = np.full((3, 1), 'element-a')
    calls = []

    monkeypatch.setattr(scenario, 'teme_to_gcrs', lambda state, when: state.copy())

    def fake_propagate(state, seconds, offsets, **kwargs):
        calls.append(kwargs)
        return np.tile(state, (len(offsets), 1))

    monkeypatch.setattr(scenario, 'awp_propagate', fake_propagate)
    result = scenario.replay_with_awp_j2_sun_moon(states, epochs, times, 60)

    assert np.isfinite(result).all()
    assert calls == [{'j2': True, 'drag': False, 'third_bodies': True,
                      'epoch': times[0]}]
