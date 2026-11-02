import numpy as np

from godsat.scenario import line_of_sight
from scripts.experiments.catalog_visibility_census_4hour import available_host_positions


def test_unavailable_stale_host_is_reported_and_excluded_from_geometry():
    ids = np.array([10, 30, 50], dtype=np.int64)
    positions = np.array([[1., 0., 0.], [3., 0., 0.], [5., 0., 0.]])
    selected = [10, 20, 50]

    available, unavailable_count = available_host_positions(ids, positions, selected)

    np.testing.assert_array_equal(available, positions[[0, 2]])
    assert unavailable_count == 1


def test_visibility_line_of_sight_rejects_earth_occulted_pair():
    earth_radius = 6378.135
    near_side = np.array([[earth_radius + 500., 0., 0.]])
    far_side = np.array([[-earth_radius - 500., 0., 0.]])
    same_side = np.array([[earth_radius + 1000., 0., 0.]])

    assert not line_of_sight(near_side, far_side)[0]
    assert line_of_sight(near_side, same_side)[0]
