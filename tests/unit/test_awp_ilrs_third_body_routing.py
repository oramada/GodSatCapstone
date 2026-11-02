import datetime as dt

import numpy as np
import pytest

pytest.importorskip('astropy')
from scripts.validation import validate_awp_against_ilrs as runner


def test_reference_validation_passes_historical_epoch_and_third_body_forces_to_integrator(tmp_path, monkeypatch):
    epoch = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    observation = epoch + dt.timedelta(minutes=30)
    source = tmp_path/'comparison.csv'; source.write_text('header\nrow\n')
    row = {'historical_element_epoch_utc': epoch.isoformat(), '_when': observation,
           '_age': .5, '_cpf': np.array([7000., 11., 0.]), '_sgp4': np.array([7000., 10.5, 0.]),
           'station_name': 'station', 'station_sod': '1800', 'cpf_file': 'source.cpf'}
    monkeypatch.setattr(runner, 'load_history', lambda norad: ([epoch], [{'epoch': epoch}], 0, 0))
    monkeypatch.setattr(runner, 'load_comparison_sample', lambda *args: ([row], source))
    class InitialSatellite:
        def sgp4(self, *args):
            return 0, [7000., 0., 0.], [0., 7.5, 0.]
    monkeypatch.setattr(runner, 'satellite', lambda tle: InitialSatellite())
    monkeypatch.setattr(runner, 'teme_to_gcrs', lambda state, when: state)
    monkeypatch.setattr(runner, 'gcrs_to_itrf', lambda times, positions, table: positions)
    calls = []
    def integrate(state, seconds, times, **kwargs):
        calls.append(kwargs)
        assert seconds == 1800.
        np.testing.assert_array_equal(times, [0., 1800.])
        return np.array([state, [7000., 10., 0., 0., 7.5, 0.]])
    monkeypatch.setattr(runner, 'awp_propagate', integrate)
    rows, design = runner.evaluate_target('lageos1', 8820, None, third_bodies=True)
    assert calls == [{'j2': True, 'drag': False, 'area_mass_m2_kg': .01,
                      'third_bodies': True, 'epoch': epoch}]
    assert design['sampled_rows'] == 1
    assert rows[0]['awp_j2_sun_moon_position_separation_km'] == 1.
    assert rows[0]['awp_minus_sgp4_separation_km'] == .5
