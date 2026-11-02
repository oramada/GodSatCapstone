import numpy as np
import astropy.units as units
from astropy.coordinates import CartesianDifferential, CartesianRepresentation, GCRS, TEME
from astropy.time import Time

from godsat.orbits import teme_to_gcrs


def test_teme_to_gcrs_transforms_position_and_velocity_and_round_trips():
    epoch = Time('2026-10-01T00:00:00', scale='utc')
    original = np.array([-4096.0, -1570.9, -5249.2, 3.0619, -6.9854, -0.3692])

    transformed = teme_to_gcrs(original, '2026-10-01T00:00:00Z')
    assert not np.allclose(transformed, original)
    assert np.isclose(np.linalg.norm(transformed[:3]), np.linalg.norm(original[:3]), rtol=1e-12)
    assert np.isclose(np.linalg.norm(transformed[3:]), np.linalg.norm(original[3:]), rtol=1e-8)

    rep = CartesianRepresentation(
        transformed[:3] * units.km,
        differentials=CartesianDifferential(transformed[3:] * units.km / units.s),
    )
    recovered = GCRS(rep, obstime=epoch).transform_to(TEME(obstime=epoch))
    recovered_state = np.concatenate((recovered.cartesian.xyz.to_value(units.km),
                                      recovered.velocity.d_xyz.to_value(units.km / units.s)))
    np.testing.assert_allclose(recovered_state, original, rtol=0, atol=1e-8)
