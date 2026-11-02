import csv
import io

from scripts.data import parse_ilrs_lageos


def test_parse_crd_normal_point_preserves_station_time_and_range(tmp_path, monkeypatch):
    monkeypatch.setattr(parse_ilrs_lageos, "ROOT", tmp_path)
    path = tmp_path / "sample.np2"
    path.write_text(
        "h1 CRD 2 2026 10 9 3\n"
        "h2 HARL 7501 6 2 3 ILRS\n"
        "h3 lageos1 7603901 1155 8820 0 1 1\n"
        "h5 1 26 100900 sgf 17901\n"
        "h4 1 2026 10 9 0 14 43 2026 10 9 0 20 55 0 0 0 0 1 0 2 0\n"
        "11 923.3005614 0.045481628786 new 2 120.0 167 60.0 0.096 0.099 na 27.83 0 0\n"
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=parse_ilrs_lageos.FIELDS)
    writer.writeheader()
    records, warnings = parse_ilrs_lageos.parse_file(path, writer)
    row = next(csv.DictReader(io.StringIO(output.getvalue())))

    assert records == 1
    assert warnings == 0
    assert row["station_name"] == "HARL"
    assert row["station_cdp_id"] == "7501"
    assert row["norad_id"] == "8820"
    assert row["observation_time_utc"].startswith("2026-10-09T00:15:23.300561")
    assert abs(float(row["two_way_range_km_from_time_of_flight"]) - 6817.525) < 0.1
    assert row["center_of_mass_correction_applied"] == "0"
    assert row["refraction_correction_applied"] == "0"
    assert row["station_system_delay_applied"] == "1"
    assert row["range_type"] == "2"
    assert row["prediction_type"] == "1"
    assert row["prediction_year"] == "26"
    assert row["prediction_provider"] == "sgf"
    assert row["prediction_sequence"] == "17901"


def test_parse_crd_assigns_post_midnight_seconds_to_next_session_day(tmp_path, monkeypatch):
    monkeypatch.setattr(parse_ilrs_lageos, "ROOT", tmp_path)
    path = tmp_path / "midnight.np2"
    path.write_text(
        "H1 CRD 2 2026 10 9 3\n"
        "H2 HARL 7501 6 2 3 ILRS\n"
        "H3 lageos1 7603901 1155 8820 0 1 1\n"
        "H4 1 2026 10 8 23 58 0 2026 10 9 0 5 0 0 0 0 0 1 0 2 0\n"
        "11 86399 0.045 new 2 120 10 30 0 0 na 3 0 0\n"
        "11 30 0.045 new 2 120 10 30 0 0 na 3 0 0\n"
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=parse_ilrs_lageos.FIELDS)
    writer.writeheader()
    records, warnings = parse_ilrs_lageos.parse_file(path, writer)
    rows = list(csv.DictReader(io.StringIO(output.getvalue())))

    assert records == 2
    assert warnings == 0
    assert rows[0]["observation_time_utc"].startswith("2026-10-08T23:59:59")
    assert rows[1]["observation_time_utc"].startswith("2026-10-09T00:00:30")
