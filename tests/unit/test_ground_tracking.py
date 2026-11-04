import json

import numpy as np
import pytest
import torch

from godsat.ground import GroundTrackingEnv, station_positions
from godsat.learning import Agent, resolved_hyperparameters
from godsat.orbits import utc
from godsat.scope import validate_execution
from test_sensorphysics import inputs
from scripts.validation.audit_physical_campaign import reconstruct_trace


def ground_case():
    scenario, config = inputs(detection=1, clutter=0)
    scenario['states'][:, 0, :3] = [6378.137, 0, 0]
    scenario['states'][:, 1, :3] = [7158.137, 0, 0]
    scenario['ground_up'] = np.tile([[[1., 0, 0]]], (4, 1, 1))
    scenario['itrs_to_teme'] = np.tile(np.eye(3), (4, 1, 1))
    config.update(ground_min_elevation_deg=10, sensor_response_model='ground_tracking_gimbal_and_clutter_v1',
                  scenario_kind='ground_tracks_iridium_next_v1')
    return scenario, config


def test_ground_surface_is_not_rejected_by_space_to_space_earth_clearance():
    scenario, config = ground_case()
    env = GroundTrackingEnv(scenario, config)
    assert env.geometry()[-1][0, 0]
    env.step([0])
    assert env.metrics()['custody_continuity'] == 1


@pytest.mark.parametrize('position', [[6378.137, 1000, 0], [6200, 0, 0]])
def test_ground_horizon_and_elevation_exclude_unobservable_targets(position):
    scenario, config = ground_case()
    scenario['states'][:, 1, :3] = position
    env = GroundTrackingEnv(scenario, config)
    assert not env.geometry()[3][0, 0]
    env.step([0])
    assert env.metrics()['custody_continuity'] == 0


def test_earth_fixed_mount_rotates_with_earth_between_commands():
    scenario, config = ground_case()
    rotation = np.asarray([[0., -1, 0], [1, 0, 0], [0, 0, 1]])
    scenario['itrs_to_teme'][1:] = rotation
    scenario['states'][1:, :, :3] = scenario['states'][1:, :, :3] @ rotation.T
    scenario['ground_up'][1:] = scenario['ground_up'][1:] @ rotation.T
    env = GroundTrackingEnv(scenario, config)
    env.step([0])
    np.testing.assert_allclose(env.pointing[0], [0, 1, 0], atol=1e-12)
    assert env.geometry()[2][0, 0] == pytest.approx(0)


def test_ground_dropout_suppresses_both_true_and_false_returns():
    scenario, config = ground_case()
    config['false_association_probability_per_missed_look'] = 1
    env = GroundTrackingEnv(scenario, config, dropout_probability=.5)
    env.dropout_uniforms[:] = 0
    for _ in range(env.steps):
        env.step([0])
    assert env.metrics()['custody_continuity'] == 0
    assert env.metrics()['reported_observations'] == 0


def test_ground_action_metrics_match_independent_work_and_detection_reconstruction():
    scenario, config = ground_case()
    scenario['states'][:, 1, :3] = [7158.137, 100, 0]
    env = GroundTrackingEnv(scenario, config, seed=79, dropout_probability=.2)
    for _ in range(env.steps):
        env.step([0])
    audited = reconstruct_trace(scenario, config, 79, env.trace, probability=.2)
    for key, value in audited.items():
        assert value == pytest.approx(env.metrics()[key])


def test_ground_coordinate_solution_gaps_are_not_interpolated():
    sites = [{'site_id': '1', 'solutions': [{'start': '2020-01-01T00:00:00Z',
        'end': '2021-01-01T00:00:00Z', 'reference_epoch': '2020-01-01T00:00:00Z',
        'xyz_m': [6378137, 0, 0], 'velocity_m_per_year': [1, 0, 0]}]}]
    with pytest.raises(ValueError, match='No unique dated ground solution'):
        station_positions(sites, [utc('2022-01-01T00:00:00Z')])


def test_isolated_actor_width_preserves_critic_architecture_and_legacy_loading():
    hp = {'actor_width': 64, 'critic_depth': 3}
    small = Agent(20, 5, resolved_hyperparameters(hp, {'fixed_critic_width': 128}))
    large = Agent(20, 5, resolved_hyperparameters({**hp, 'actor_width': 256}, {'fixed_critic_width': 128}))
    assert [tuple(p.shape) for p in small.critic.parameters()] == [tuple(p.shape) for p in large.critic.parameters()]
    assert small.actor[0].out_features != large.actor[0].out_features
    legacy = Agent(20, 5, hp)
    restored = Agent(20, 5, hp)
    restored.load_state_dict(legacy.state_dict())
    assert legacy.critic[0].out_features == 64


def test_ground_gate_requires_model_and_pinned_sites(tmp_path):
    # Existing orbital-only scope tests cover rejection. A named role alone
    # cannot authorize a ground run without matching coordinates and model.
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs/active-study-scope.json').write_text(json.dumps({
        'ground_systems_required': True, 'ground_system_role': 'tracking_sensors'}))
    with pytest.raises(ValueError, match='requires ground systems'):
        validate_execution(tmp_path, {'scenario_kind': 'ground_tracks_iridium_next_v1'})
