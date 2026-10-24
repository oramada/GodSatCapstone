import datetime as dt

from scripts import validate_ilrs_ranges as validation
from scripts.compare_sgp4_with_ilrs_cpf import EOP, teme_to_itrf


def test_cpf_lagrange_interpolation_reproduces_polynomial():
    times = [float(i) for i in range(10)]
    values = [(t**3, 2*t**2, -t) for t in times]
    result = validation.lagrange10(times, values, 4.25)
    assert abs(result[0] - 4.25**3) < 1e-9
    assert abs(result[1] - 2*4.25**2) < 1e-9
    assert abs(result[2] + 4.25) < 1e-9


def test_predicted_two_way_light_time_for_stationary_target():
    instant = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    center = dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)
    query = (instant - center).total_seconds()
    eph = {'times': [query + i - 5 for i in range(11)],
           'xyz_m': [(10_000_000.0, 0.0, 0.0)] * 11,
           'h5_com_correction_m': 0.245, 'com_applied': 0}
    station = [0.0, 0.0, 0.0]
    one_way, tof = validation.predicted_range(eph, instant, station)
    assert abs(one_way - (10_000_000 - 0.245)) < 1e-6
    assert abs(tof - 2*10_000_000/validation.SPEED_OF_LIGHT_M_S) < 1e-12
    assert abs(validation.predicted_range(dict(eph, com_applied=1), instant, station)[0] - 10_000_000) < 1e-6
    assert abs(validation.predicted_range(eph, instant, station, crd_com_applied=1)[0] - 10_000_000) < 1e-6


def test_station_coordinates_propagate_to_normal_point_epoch():
    midpoint = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    station = {'position_epoch_utc': midpoint.isoformat(),
        'optical_reference_x_m': '100', 'optical_reference_y_m': '200',
        'optical_reference_z_m': '300', 'velocity_x_m_per_year': '2',
        'velocity_y_m_per_year': '-1', 'velocity_z_m_per_year': '0.5'}
    when = midpoint + dt.timedelta(days=365.25)
    assert validation.station_at(station, when) == [102.0, 199.0, 300.5]


def test_teme_to_itrf_uses_eop_without_changing_geocentric_radius():
    from astropy.utils.iers import IERS_A
    table = IERS_A.open(str(EOP))
    when = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    result = teme_to_itrf([when], [[7000.0, 0.0, 0.0]], table)[0]
    assert abs(sum(x*x for x in result) ** 0.5 - 7000.0) < 1e-8
