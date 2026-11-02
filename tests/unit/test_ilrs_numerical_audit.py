import pytest

from scripts.validation.audit_ilrs_sensor_quality import check_range_arithmetic, quality_contrast


def test_range_audit_detects_incorrect_bias_sign():
    row = {'observed_one_way_equivalent_range_m': '10', 'predicted_one_way_equivalent_range_m': '8',
           'range_residual_m': '2', 'dhf_range_bias_correction_m': '.5',
           'dhf_time_bias_range_equivalent_m': '.2', 'range_residual_with_dhf_biases_m': '1.3'}
    assert check_range_arithmetic(row) == 1.3
    row['range_residual_with_dhf_biases_m'] = '2.7'
    with pytest.raises(ValueError, match='DHF-corrected range'):
        check_range_arithmetic(row)


def test_station_day_contrast_excludes_invalid_rates_and_range_outliers():
    rows = [('A', 'd1', .5, 2.), ('A', 'd1', 50., 1.),
            ('B', 'd1', .5, 4.), ('B', 'd1', 50., 1.),
            ('A', 'd1', 101., 40.), ('A', 'd1', .5, 1000.)]
    result = quality_contrast(rows, 200, 7)
    assert result['clusters'] == 2
    assert result['mean'] == 2.
    assert result['ci95'] == [1., 3.]
    assert result['low_return_points'] == result['high_return_points'] == 2
