import json

import numpy as np

from godsat.experiment import write_regime_replays


def test_regime_replays_keep_each_heldout_scenario_separate(tmp_path):
    scenarios = {'test': []}
    traces = []
    for index, _regime in enumerate(['leo', 'meo', 'geo', 'heo']):
        states = np.full((2, 2, 6), float(index + 1))
        scenarios['test'].append({
            'times': np.array(['2026-10-01T00:00:00Z', '2026-10-01T00:01:00Z']),
            'ids': np.array([100 + index, 200 + index]),
            'agents': 1,
            'states': states,
        })
        traces.append([{'custody': float(index)}])

    config = {'test_regimes': ['leo', 'meo', 'geo', 'heo'],
              'test_dates': ['2026-10-01T00:00:00Z']}
    write_regime_replays(tmp_path, scenarios, traces, config)

    for index, regime in enumerate(config['test_regimes']):
        replay = json.loads((tmp_path / 'replays' / f'{regime}.json').read_text())
        assert replay['orbit_regime'] == regime
        assert replay['ids'] == [100 + index, 200 + index]
        assert replay['trace'][0]['custody'] == float(index)
    default_replay = json.loads((tmp_path / 'replay.json').read_text())
    assert default_replay['orbit_regime'] == 'leo'


def test_regime_replay_export_rejects_missing_traces(tmp_path):
    config = {'test_regimes': ['leo', 'meo'], 'test_dates': ['2026-10-01T00:00:00Z']}
    try:
        write_regime_replays(tmp_path, {'test': [{}]}, [[]], config)
    except ValueError as error:
        assert 'Missing held-out scenario traces' in str(error)
    else:
        raise AssertionError('Expected an error for missing regime scenarios')
