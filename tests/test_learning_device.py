import math
import hashlib
import json

import numpy as np
import pytest
import torch

from godsat.experiment import run_treatment
from godsat.learning import compute_device, evaluate, train


def _tiny_scenario():
    radius = 6378.135 + 500.0
    angle = math.radians(20)
    first = np.array([radius, 0.0, 0.0, 0.0, 7.6, 0.0])
    second = np.array([radius * math.cos(angle), radius * math.sin(angle), 0.0,
                       -2.6, 7.1, 0.0])
    return {
        'agents': 1,
        'ids': np.array([100, 200], dtype=np.int32),
        'times': np.arange(4),
        'states': np.repeat(np.stack([first, second])[None, :, :], 4, axis=0),
        'ages': np.zeros((4, 2), dtype=float),
    }


def _config(device):
    return {
        'compute_device': device,
        'training_episodes': 1,
        'step_seconds': 60,
        'max_element_age_hours': 72,
        'max_range_km': 6000,
        'slew_rate_deg_s': 2,
        'field_of_regard_deg': 180,
        'custody_seconds': 180,
        'detection_probability': 1.0,
        'range_detection_penalty': 0.0,
        'stale_detection_penalty': 0.0,
        'slew_penalty': 0.03,
        'false_penalty': 0.2,
        'collision_penalty': 0.1,
    }


def _hyperparameters():
    return {
        'learning_rate': 1e-3,
        'discount': 0.95,
        'actor_width': 8,
        'critic_depth': 1,
        'entropy': 0.01,
        'claim_resolution': 8,
        'target_tau': 0.01,
    }


def test_cpu_device_is_the_default():
    assert compute_device({}).type == 'cpu'


def test_cached_cpu_treatment_is_upgraded_with_compute_provenance(tmp_path):
    config = _config('cpu')
    hp = _hyperparameters()
    signature = hashlib.sha256(
        json.dumps({'hp': hp, 'config': config, 'seed': 123}, sort_keys=True).encode()
    ).hexdigest()
    runs = tmp_path / 'runs'
    runs.mkdir()
    record_path = runs / 'cached.json'
    record_path.write_text(json.dumps({'signature': signature, 'wall_seconds': 1.0}))

    record = run_treatment('cached', hp, {}, config, tmp_path, 123)
    persisted = json.loads(record_path.read_text())

    assert record['compute_device'] == 'cpu'
    assert record['gpu_hours'] == 0.0
    assert record['gpu_active_seconds'] == 0.0
    assert persisted == record


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason='Apple MPS is unavailable')
def test_mps_training_is_repeatable_and_records_device_active_time():
    config = _config('mps')
    scenario = _tiny_scenario()
    models = []
    results = []
    for _ in range(2):
        model, history, _, gpu_seconds = train([scenario], config, _hyperparameters(), 123, episodes=1)
        metrics, _, evaluation_gpu_seconds = evaluate(
            model, [scenario], config, _hyperparameters(), 456
        )
        assert next(model.parameters()).device.type == 'mps'
        assert gpu_seconds > 0 and evaluation_gpu_seconds > 0
        assert all(np.isfinite(value) for value in metrics.values())
        models.append(model.state_dict())
        results.append((history[0]['loss'], metrics['custody_continuity']))

    assert results[0] == results[1]
    for key in models[0]:
        torch.testing.assert_close(models[0][key].cpu(), models[1][key].cpu(), rtol=0, atol=0)
