import datetime as dt
from collections import defaultdict

from scripts.data import download_ilrs_cpf


def test_parse_cpf_reads_sequence_provider_target_and_interval(tmp_path):
    path = tmp_path / "sample.cpf"
    path.write_text(
        "H1 CPF 2 SGF 2026 6 28 2 179 01 lageos1 NONE\n"
        "H2 7603901 1155 08820 2026 6 27 0 0 0 2026 7 2 23 54 0 300 1 1 0 0 0 1\n"
    )
    meta = download_ilrs_cpf.parse_cpf(path)
    assert meta["provider"] == "sgf"
    assert meta["year"] == 2026
    assert meta["sequence"] == "17901"
    assert meta["satellite_id"] == "8820"
    assert meta["start"] == dt.datetime(2026, 6, 27, tzinfo=dt.timezone.utc)
    assert meta["end"] == dt.datetime(2026, 7, 2, 23, 54, tzinfo=dt.timezone.utc)


def test_two_digit_year_pivot_matches_sinex_convention():
    assert download_ilrs_cpf.year_from_crd("26") == 2026
    assert download_ilrs_cpf.year_from_crd("76") == 1976


def test_cpf_archive_year_follows_h2_span_across_new_year(tmp_path):
    path = tmp_path / 'new_year_fixture.cpf'
    path.write_text(
        "H1 CPF 2 SGF 2025 1 1 2 001 01 lageos1 NONE\n"
        "H2 7603901 1155 08820 2024 12 31 0 0 0 2025 1 5 23 54 0 300 1 1 0 0 0 1\n"
    )
    meta = download_ilrs_cpf.parse_cpf(path)
    assert meta['year'] == 2024
    assert meta['production_year'] == 2025
    assert meta['start'].year == 2024


def test_cpf_directory_index_supports_other_target_slugs():
    parser = download_ilrs_cpf.Links('lares')
    parser.feed('<a href="lares_cpf_261009_28201.dgf">valid</a>')
    parser.feed('<a href="lageos1_cpf_261009_28201.dgf">other target</a>')
    assert parser.values == ['lares_cpf_261009_28201.dgf']


def test_dhf_bias_parser_reads_range_and_time_units(tmp_path):
    from scripts.validation.validate_ilrs_ranges import parse_dhf_biases, dhf_correction
    path = tmp_path / 'handling.snx'
    path.write_text(
        '+MODEL/RANGE_BIAS\n'
        ' 7119 51 501 A 22:001:00000 00:000:00000 R 9.5 1.0 mm\n'
        '-MODEL/RANGE_BIAS\n'
        '+MODEL/TIME_BIAS\n'
        ' 7119 -- 501 A 22:001:00000 00:000:00000 T -2.0 1.0 0.0 us\n'
        '-MODEL/TIME_BIAS\n')
    biases = parse_dhf_biases(path)
    when = dt.datetime(2023, 1, 2, tzinfo=dt.timezone.utc)
    assert dhf_correction(biases, 'range', '7119', when) == 0.0095
    assert abs(dhf_correction(biases, 'time', '7119', when) + 299.792458) < 1e-9
