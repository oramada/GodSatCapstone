import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.analysis.analyze_epop_solution_quality import analyze


def test_analyze_quality_classes_and_nearest_solution_spacing(tmp_path):
    data = tmp_path / "attitude"
    processed = data / "processed" / "2024"
    processed.mkdir(parents=True)
    day = "2024-01-01"
    n = 86_400
    q = np.zeros(n, dtype=np.float64)
    q[2 * 60] = np.nan
    previous = np.full(n, 5, dtype=np.int8)
    next_ = np.full(n, 5, dtype=np.int8)
    previous[0] = next_[0] = 1
    previous[60] = next_[60] = 4
    previous[120] = next_[120] = 0
    previous[180] = next_[180] = 6
    tt_prev = np.full(n, 2.0, dtype=np.float32)
    tt_next = np.full(n, 4.0, dtype=np.float32)
    tt_prev[60] = 75.0
    tt_next[60] = 80.0
    table = pa.table({
        "q1": pa.array(q), "q2": pa.array(np.zeros(n)),
        "q3": pa.array(np.zeros(n)), "q4": pa.array(np.ones(n)),
        "data_source_previous": pa.array(previous),
        "data_source_next": pa.array(next_),
        "time_to_previous_s": pa.array(tt_prev),
        "time_to_next_s": pa.array(tt_next),
    })
    pq.write_table(table, processed / f"{day}.parquet")
    (data / "independent_audit.json").write_text(json.dumps({
        "status": "passed_structural_and_statistical", "validated_dates": [day],
        "downloaded_days": 1, "first_day": day, "last_day": day,
    }))
    (data / "dropout_profile_1minute.json").write_text(json.dumps({
        "status": "completed", "one_minute_samples": 1440,
    }))

    result = analyze(data)
    assert result["quality_class_counts"] == {
        "dropout": 1, "coarse_sun_magnetometer": 1, "star_tracker": 1438,
        "unknown": 0,
    }
    assert result["source_code_counts"]["previous"]["0"] == 1
    assert result["source_code_counts"]["previous"]["1"] == 1
    age_report = result["nearest_definitive_solution_spacing_seconds_on_valid_quaternion_samples"]
    assert age_report["sample_count"] == 1439
    assert age_report["quantiles_seconds"]["0.5"] == 2.0
    assert age_report["fractions_above_seconds"]["60"] > 0
