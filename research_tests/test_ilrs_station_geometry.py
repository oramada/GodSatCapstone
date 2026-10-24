import datetime as dt

from scripts import join_ilrs_station_geometry as geometry


def test_sinex_two_digit_year_pivot_and_open_ended_epoch():
    assert geometry.snx_epoch("76:001:00000") == dt.datetime(1976, 1, 1, tzinfo=dt.timezone.utc)
    assert geometry.snx_epoch("22:001:00000") == dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc)
    assert geometry.snx_epoch("00:000:00000", open_end=True) is None


def test_une_offset_axes_are_orthogonal_at_equator_greenwich():
    # At lat=lon=0, up points +X, north +Z, and east +Y.
    assert geometry.une_to_ecef(1, 0, 0, 0, 0) == [1, 0, 0]
    assert geometry.une_to_ecef(0, 1, 0, 0, 0) == [0, 0, 1]
    assert geometry.une_to_ecef(0, 0, 1, 0, 0) == [0, 1, 0]


def test_dated_coordinates_propagate_velocity_from_reference_epoch():
    reference = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    solution = {"reference_epoch": reference, "xyz_m": [1, 2, 3],
                "velocity_m_per_year": [2, -4, 0.5]}
    when = reference + dt.timedelta(days=365.25)
    assert geometry.dated_xyz(solution, when) == [3, -2, 3.5]
