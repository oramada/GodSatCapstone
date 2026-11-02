import datetime as dt

import numpy as np
import duckdb

from scripts.data.export_state_vectors import parallel_state_batch, write_state_part


def test_parallel_sgp4_batch_matches_sequential_states():
    epoch = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    rows = [
        (25544 + i, epoch + dt.timedelta(seconds=i), 51.64, 120.0 + i,
         0.0005, 80.0, 10.0 + i, 15.5, 0.0, 0.00001)
        for i in range(8)
    ]
    sequential = parallel_state_batch(rows, 1)
    parallel = parallel_state_batch(rows, 2)
    for left, right in zip(sequential, parallel):
        np.testing.assert_array_equal(left, right)


def test_columnar_state_part_writer_preserves_schema_and_values(tmp_path):
    epoch = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    rows = [
        (25544, epoch, 51.64, 120.0, 0.0005, 80.0, 10.0, 15.5, 0.0, 0.00001),
        (25545, epoch + dt.timedelta(seconds=1), 51.65, 121.0, 0.0006,
         81.0, 11.0, 15.4, 0.0, 0.00002),
    ]
    ids = np.array([25544, 25545], dtype=np.int32)
    errors = np.array([0, 0], dtype=np.int16)
    states = np.arange(12, dtype=np.float64).reshape(2, 6)
    output = tmp_path / "part-00000.parquet"

    write_state_part(output, rows, ids, errors, states)

    con = duckdb.connect()
    result = con.execute("SELECT * FROM read_parquet(?) ORDER BY norad_id", [str(output)])
    names = [column[0] for column in result.description]
    materialized = result.fetchall()
    con.close()
    assert names == ["norad_id", "epoch", "sgp4_error", "x_teme_km", "y_teme_km",
                     "z_teme_km", "vx_teme_km_s", "vy_teme_km_s", "vz_teme_km_s"]
    assert [row[:3] for row in materialized] == [(25544, epoch, 0),
                                                 (25545, epoch + dt.timedelta(seconds=1), 0)]
    np.testing.assert_array_equal(np.asarray([row[3:] for row in materialized]), states)
