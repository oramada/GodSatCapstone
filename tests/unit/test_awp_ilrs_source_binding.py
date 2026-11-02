import datetime as dt

import pytest

pytest.importorskip('astropy')
from scripts.validation.audit_awp_ilrs_cpf import check_source_reference


def source_rows():
    source = {'historical_element_epoch_utc': '2025-01-01T00:00:00+00:00',
              'historical_element_age_hours': '1', '_when': dt.datetime(2025, 1, 1, 1, tzinfo=dt.timezone.utc)}
    for axis, value in zip('xyz', [1., 2., 3.]):
        source[f'cpf_itrf_{axis}_km'] = str(value)
        source[f'sgp4_itrf_{axis}_km'] = str(value + .1)
    actual = dict(source, norad_id='8820', date='2025-01-01')
    return actual, source


def test_orbit_audit_rejects_common_reference_shift_even_when_separations_are_preserved():
    actual, source = source_rows()
    check_source_reference(actual, source, 8820)
    # Translating all saved vectors leaves the reported separations unchanged.
    # Binding to the original CPF/SGP4 vectors must still reject that alteration.
    actual['cpf_itrf_x_km'] = '11'
    actual['sgp4_itrf_x_km'] = '11.1'
    with pytest.raises(ValueError, match='Values differ'):
        check_source_reference(actual, source, 8820)


def test_orbit_audit_rejects_relabelled_historical_epoch():
    actual, source = source_rows()
    actual['historical_element_epoch_utc'] = '2024-12-31T23:00:00+00:00'
    with pytest.raises(ValueError, match='Historical source epoch mismatch'):
        check_source_reference(actual, source, 8820)
