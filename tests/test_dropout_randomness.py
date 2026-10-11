import numpy as np
import pytest

from godsat.environment import rescale_markov_persistence


def test_markov_persistence_rescaling_preserves_stationary_outage_rate():
    rate = 0.14552702326874942
    persistence = 0.32457938338030573
    same = rescale_markov_persistence(persistence, rate, 8.8345, 8.8345)
    assert same == pytest.approx(persistence)
    scaled = rescale_markov_persistence(persistence, rate, 8.8345, 60)
    assert scaled == pytest.approx(0.145548, abs=1e-5)
    entry = rate * (1 - scaled) / (1 - rate)
    assert rate * scaled + (1 - rate) * entry == pytest.approx(rate)


@pytest.mark.parametrize("persistence", [0.071, 0.425531914893617, 0.550])
def test_one_hz_dust_persistence_interval_collapses_at_one_minute_steps(persistence):
    # DUST's annotation-gap proxy is estimated at its nominal 1 Hz frame cadence.
    # At GoDSAT's 60-second step, every endpoint maps to an effectively memoryless
    # outage process while retaining the configured stationary outage fraction.
    scaled = rescale_markov_persistence(persistence, 0.2, 1.0, 60.0)
    assert scaled == pytest.approx(0.2, abs=1e-12)
from pathlib import Path
from types import SimpleNamespace

from godsat.environment import TaskingEnv
from godsat.scenario import _cache_is_cloud_placeholder


def scenario():
    states=np.zeros((3,2,6),dtype=float)
    states[:,:,0]=[[7000.,8000.],[7000.,8000.],[7000.,8000.]]
    return {
        'states':states,
        'ages':np.zeros((3,2)),
        'ids':np.array([10,20]),
        'times':np.array(['t0','t1','t2']),
        'agents':1,
    }


def config():
    return {
        'step_seconds':60,'max_range_km':6000,'slew_rate_deg_s':2,
        'field_of_regard_deg':180,'custody_seconds':180,
        'detection_probability':1.,'range_detection_penalty':0.,
        'stale_detection_penalty':0.,'max_element_age_hours':72,
        'slew_penalty':0.,'false_penalty':0.,'collision_penalty':0.,
        'dropout_burst_persistence':.8,
    }


def test_dropout_treatments_share_exogenous_random_draws():
    reference=TaskingEnv(scenario(),config(),seed=421,dropout_probability=0.)
    treatment=TaskingEnv(scenario(),config(),seed=421,dropout_probability=.4)

    np.testing.assert_array_equal(reference.detection_uniforms,treatment.detection_uniforms)
    np.testing.assert_array_equal(reference.dropout_uniforms,treatment.dropout_uniforms)
    np.testing.assert_array_equal(
        reference.priority_rng.permutation(100),
        treatment.priority_rng.permutation(100),
    )


def test_burst_outage_clock_advances_during_idle_sensor_steps():
    env=TaskingEnv(scenario(),config(),seed=17,dropout_probability=.5,dropout_mode='burst')
    env.dropout_state[0]=True
    env.burst_transition_uniforms[1,0]=.99

    env.step(np.array([1]))  # idle at the first timestep
    assert env.dropout_state[0]
    env.step(np.array([1]))  # transition occurs although still idle

    assert not env.dropout_state[0]


def test_burst_persistence_override_controls_recovery_transition():
    cfg=config()
    cfg['dropout_burst_persistence']=.425531914893617
    env=TaskingEnv(scenario(),cfg,seed=23,dropout_probability=.5,dropout_mode='burst')
    env.dropout_state[0]=True
    env.burst_transition_uniforms[1,0]=.5

    env.step(np.array([1]))
    env.step(np.array([1]))

    assert not env.dropout_state[0]


def test_scenario_cache_detects_macos_dataless_placeholder(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, 'stat', lambda self: SimpleNamespace(st_flags=0x40000000))
    assert _cache_is_cloud_placeholder(tmp_path / 'scenario.npz')

    monkeypatch.setattr(Path, 'stat', lambda self: SimpleNamespace(st_flags=0))
    assert not _cache_is_cloud_placeholder(tmp_path / 'scenario.npz')


def test_empirical_block_replay_preserves_measured_blocks_and_is_seeded():
    from godsat.dropout import sample_empirical_dropout_blocks

    masks = np.asarray([
        [False, True, True, False, False, False],
        [True, True, False, True, False, False],
    ])
    sampled = sample_empirical_dropout_blocks(masks, steps=4, agents=5, seed=91)
    repeated = sample_empirical_dropout_blocks(masks, steps=4, agents=5, seed=91)
    assert sampled.shape == (4, 5)
    assert np.array_equal(sampled, repeated)
    assert all(any(np.array_equal(sampled[:, agent], row[start:start + 4])
                   for row in masks for start in range(3)) for agent in range(5))


def test_empirical_block_replay_rejects_short_or_empty_masks():
    from godsat.dropout import sample_empirical_dropout_blocks

    with pytest.raises(ValueError, match="daily rows"):
        sample_empirical_dropout_blocks(np.zeros((2, 3), dtype=bool), steps=4, agents=1, seed=1)
    with pytest.raises(ValueError, match="positive"):
        sample_empirical_dropout_blocks(np.zeros((2, 4), dtype=bool), steps=0, agents=1, seed=1)
