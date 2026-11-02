import numpy as np
import pytest

pytest.importorskip('astropy')

from astropy.utils import iers
from godsat.environment import TaskingEnv
from godsat.orbits import teme_to_gcrs, utc
from scripts.validation.validate_awp_scenarios import gcrs_scenario_to_teme


def test_pure_frame_change_preserves_as_trained_policy_features_and_missing_states():
    times = np.asarray(['2026-10-01T00:00:00Z', '2026-10-01T00:01:00Z'])
    states = np.asarray([[[7000., 0., 0., 0., 7.5, 0.],
                          [7100., 170., 50., -.1, 7.4, .2]]] * 2)
    states[1, 1] = np.nan
    scenario = {'states': states, 'times': times, 'ids': np.asarray([100, 200]),
                'agents': 1, 'ages': np.zeros((2, 2))}
    numerical = np.full_like(states, np.nan)
    with iers.conf.set_temp('auto_download', False):
        for index, instant in enumerate(times):
            for obj in range(2):
                if np.isfinite(states[index, obj]).all():
                    numerical[index, obj] = teme_to_gcrs(states[index, obj], utc(str(instant)))
        transformed = gcrs_scenario_to_teme({**scenario, 'states': numerical})
    assert np.array_equal(np.isnan(transformed['states']), np.isnan(states))
    np.testing.assert_allclose(transformed['states'][..., :3], states[..., :3], atol=1e-8, rtol=0)
    np.testing.assert_allclose(transformed['states'][..., 3:], states[..., 3:], atol=1e-9, rtol=0)
    config = {'step_seconds': 60, 'custody_seconds': 180, 'slew_rate_deg_s': 2,
              'field_of_regard_deg': 180, 'max_range_km': 6000}
    expected, expected_mask = TaskingEnv(scenario, config).observation()
    actual, actual_mask = TaskingEnv(transformed, config).observation()
    wrong_frame, _ = TaskingEnv({**scenario, 'states': numerical}, config).observation()
    np.testing.assert_allclose(actual, expected, atol=2e-7, rtol=0)
    np.testing.assert_array_equal(actual_mask, expected_mask)
    assert np.max(np.abs(wrong_frame - expected)) > 1e-6
