import numpy as np
import pytest

from godsat.orbits import AWP_EARTH_CONSTANTS, EARTH_MU, EARTH_RADIUS, awp_propagate


def test_awp_uses_physical_iers_earth_constants():
    assert AWP_EARTH_CONSTANTS == {
        'mu': 398600.4418,
        'radius': 6378.1366,
        'J2': 1.0826359e-3,
    }


def test_awp_solar_lunar_force_requires_an_epoch():
    state=np.array([42164.0,0.0,0.0,0.0,3.07466,0.0])
    with pytest.raises(ValueError,match='epoch is required'):
        awp_propagate(state,3600.0,[0.0,3600.0],third_bodies=True)


def test_awp_solar_lunar_third_body_propagation_is_finite():
    state=np.array([42164.0,0.0,0.0,0.0,3.07466,0.0])
    propagated=awp_propagate(state,6*3600.0,[0.0,3*3600.0,6*3600.0],
        j2=True,third_bodies=True,epoch='2025-01-01T00:00:00Z')
    assert propagated.shape==(3,6)
    assert np.isfinite(propagated).all()
    assert np.linalg.norm(propagated[-1,:3])>40000


def test_awp_drag_force_changes_low_orbit_arc_and_rejects_invalid_ballistic_parameter():
    radius=EARTH_RADIUS+400.0
    state=np.array([radius,0.0,0.0,0.0,np.sqrt(EARTH_MU/radius),0.0])
    times=np.array([0.0,1800.0,3600.0])
    no_drag=awp_propagate(state,3600.0,times,drag=False)
    with_drag=awp_propagate(state,3600.0,times,drag=True,area_mass_m2_kg=0.4)
    assert np.isfinite(with_drag).all()
    assert np.linalg.norm(with_drag[-1,:3]-no_drag[-1,:3])>1.0
    with pytest.raises(ValueError,match='must be positive'):
        awp_propagate(state,3600.0,times,drag=True,area_mass_m2_kg=0.0)
