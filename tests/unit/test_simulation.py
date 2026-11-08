import datetime as dt
import json
import numpy as np
import pytest
from sgp4.api import Satrec
from godsat.simulation.catalog import load_catalog, make_times, propagate, build_scene, to_itrs, position_derivatives
from godsat.simulation.environment import validate_environment, active_samples, ionospheric_group_delay_m
from godsat.studio.scene import load_scene, base

# Vallado/CelesTrak SGP4 verification case 00005; epoch vector from tcppver.out.
LINE1 = '1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753'
LINE2 = '2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667'


def record():
    return ('5', 'VANGUARD 1', Satrec.twoline2rv(LINE1, LINE2))


def epoch():
    return dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=178.78495062)


def environment():
    return {'schema': 'godsat.environment.v1',
            'sources': [{'id': 'test', 'name': 'Test fixture', 'kind': 'illustrative', 'reference': 'unit fixture'}],
            'samples': [{'source_id': 'test', 'time_utc': '2000-06-27T00:00:00Z',
                         'valid_until_utc': '2000-06-28T00:00:00Z', 'latitude_deg': 0,
                         'longitude_deg': 0, 'altitude_km': 350, 'values': {'vertical_tec_tecu': 10}}]}


def test_vallado_epoch_reference_and_future_stale_masks():
    pos, vel, codes, _ = propagate([record()], [epoch()])
    np.testing.assert_allclose(pos[0, 0], [7022.46529266, -1400.08296755, 0.03995155], atol=2e-5, rtol=0)
    np.testing.assert_allclose(vel[0, 0], [1.893841015, 6.405893759, 4.534807250], atol=2e-8, rtol=0)
    assert codes.tolist() == [[0]]
    pos, _, codes, _ = propagate([record()], [epoch()-dt.timedelta(hours=1), epoch()+dt.timedelta(hours=73)])
    assert codes.tolist() == [[-2, -1]]
    assert np.isnan(pos).all()


def test_tle_integrity_and_unique_identity(tmp_path):
    path = tmp_path/'catalog.tle'
    path.write_text('VANGUARD 1\n'+LINE1+'\n'+LINE2+'\n')
    records, source = load_catalog(path, 'tle')
    assert records[0][0:2] == ('5', 'VANGUARD 1')
    assert len(source['sha256']) == 64
    path.write_text((LINE1+'\n'+LINE2+'\n')*2)
    with pytest.raises(ValueError, match='unique'): load_catalog(path, 'tle')
    path.write_text(LINE1[:-1]+'4\n'+LINE2+'\n')
    with pytest.raises(ValueError): load_catalog(path, 'tle')


def test_export_roundtrip_preserves_environment_provenance_and_unknown_observations(tmp_path):
    result = build_scene([record()], make_times(epoch().isoformat(), 60, 10), {'sha256': 'fixture'}, frame='ITRS', environment=environment())
    assert result['source']['kind'] == 'modeled'
    assert result['source']['frame_transform']['eop_sha256']
    assert result['observations'] is None
    assert np.linalg.norm(result['objects'][0]['positions_km'][0]) == pytest.approx(np.linalg.norm([7022.46529266, -1400.08296755, 0.03995155]), abs=.001)
    path = tmp_path/'scene.json'; path.write_text(json.dumps(result))
    assert load_scene(path) == result


def test_itrs_transform_preserves_radius_and_roundtrips():
    import astropy.units as u
    from astropy.coordinates import ITRS, TEME, CartesianRepresentation
    from astropy.time import Time
    from astropy.utils import iers
    p, _, _, _ = propagate([record()], [epoch()])
    fixed, _ = to_itrs(p, [epoch()])
    np.testing.assert_allclose(np.linalg.norm(fixed, axis=2), np.linalg.norm(p, axis=2), atol=1e-9)
    t = Time(epoch())
    with iers.conf.set_temp('auto_download', False):
        back = ITRS(CartesianRepresentation(fixed[0, 0]*u.km), obstime=t).transform_to(TEME(obstime=t))
    np.testing.assert_allclose(back.cartesian.xyz.to_value(u.km), p[0, 0], atol=1e-8)


def test_itrs_velocity_includes_earth_rotation_and_scene_rejects_malformed_velocity():
    from astropy.coordinates import ITRS, TEME, CartesianRepresentation, CartesianDifferential
    from astropy.time import Time
    from astropy.utils import iers
    import astropy.units as u
    p, v, _, _ = propagate([record()], [epoch()])
    fixed, fixed_v, _ = to_itrs(p, [epoch()], v)
    with iers.conf.set_temp('auto_download', False):
        state = CartesianRepresentation(fixed[0,0]*u.km, differentials=CartesianDifferential(fixed_v[0,0]*u.km/u.s))
        back = ITRS(state, obstime=Time(epoch())).transform_to(TEME(obstime=Time(epoch())))
    np.testing.assert_allclose(back.velocity.d_xyz.to_value(u.km/u.s), v[0,0], atol=1e-8)
    # Rotation changes speed; simply rotating an inertial velocity is insufficient.
    assert abs(np.linalg.norm(v[0,0])-np.linalg.norm(fixed_v[0,0])) > .1
    obj={'id':'1','kind':'satellite','positions_km':[[7000,0,0]],'velocities_km_s':[[1,2]]}
    with pytest.raises(ValueError, match='Velocities'):
        base('bad velocity', 'ITRS', [epoch().isoformat()], [obj], {})


def test_environment_validity_units_and_missing_components():
    bundle = validate_environment(environment())
    assert len(active_samples(bundle, '2000-06-28T00:00:00Z')) == 1
    assert active_samples(bundle, '2000-06-28T00:00:01Z') == []
    bundle['samples'][0]['values'] = {'cloud_fraction': 1.1}
    with pytest.raises(ValueError, match='cloud_fraction'): validate_environment(bundle)
    bundle['samples'][0]['values'] = {'magnetic_east_nt': 100}
    with pytest.raises(ValueError, match='all three'): validate_environment(bundle)
    assert ionospheric_group_delay_m(10, 1575.42e6) == pytest.approx(1.623724475, abs=1e-9)
    assert ionospheric_group_delay_m(10, 1575.42e6/2) == pytest.approx(4*1.623724475, abs=1e-8)


def test_ten_thousand_objects_fit_but_sample_budget_is_enforced():
    objects = [{'id': str(i), 'name': str(i), 'kind': 'satellite', 'positions_km': [[7000, 0, 0]]} for i in range(10000)]
    assert len(base('capacity', 'ITRS', ['2000-01-01T00:00:00Z'], objects, {})['objects']) == 10000
    with pytest.raises(ValueError, match='position samples'):
        base('too big', 'ITRS', [t.isoformat() for t in make_times('2000-01-01T00:00:00Z', 120, 1)], objects, {})


def test_position_derivatives_regression_for_eccentric_and_deep_space_orbits():
    from pathlib import Path
    records,_=load_catalog(Path(__file__).parents[1]/'fixtures/sgp4-interpolation-omm.json')
    times=make_times('2026-11-08T18:55:00Z',600,30)
    p,reported,codes,_=propagate(records,times)
    derivatives=position_derivatives(records,times,codes)
    old_errors=[]; corrected_errors=[]
    for u in [.25,.5,.75]:
        instants=[t+dt.timedelta(seconds=30*u) for t in times[:-1]]
        truth,_,_,_=propagate(records,instants)
        def interpolate(v):
            return ((2*u**3-3*u**2+1)*p[:,:-1]+(-2*u**3+3*u**2)*p[:,1:]
                    +(u**3-2*u**2+u)*30*v[:,:-1]+(u**3-u**2)*30*v[:,1:])
        old_errors.extend(np.linalg.norm(interpolate(reported)-truth,axis=2).ravel()*1000)
        corrected_errors.extend(np.linalg.norm(interpolate(derivatives)-truth,axis=2).ravel()*1000)
    assert max(corrected_errors)<.1
    assert max(old_errors)>1
