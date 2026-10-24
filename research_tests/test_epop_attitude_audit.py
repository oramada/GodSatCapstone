import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.audit_epop_attitude import audit


def test_independent_audit_accepts_and_counts_a_true_full_day_solution_dropout(tmp_path):
    data = tmp_path / "epop"
    audit_dir = data / "audits/2024"
    parquet_path = data / "processed/2024/2024-08-09.parquet"
    audit_dir.mkdir(parents=True)
    parquet_path.parent.mkdir(parents=True)
    date = "2024-08-09"
    timestamps = np.arange(
        np.datetime64(date + "T00:00:00", "ns"),
        np.datetime64(date + "T00:00:00", "ns") + np.timedelta64(86400, "s"),
        np.timedelta64(1, "s"),
    )
    table = pa.table({
        "timestamp_utc": pa.array(timestamps, type=pa.timestamp("ns", tz="UTC")),
        **{f"q{i}": pa.array(np.full(86400, np.nan)) for i in range(1, 5)},
        "data_source_previous": pa.array(np.zeros(86400, dtype=np.int8)),
        "data_source_next": pa.array(np.zeros(86400, dtype=np.int8)),
    })
    pq.write_table(table, parquet_path)
    counts = {str(i): 0 for i in range(7)}
    counts["0"] = 86400
    (audit_dir / f"{date}.json").write_text(json.dumps({
        "status": "validated", "date_utc": date, "parquet_path": str(parquet_path),
        "samples": 86400, "source_zip_sha256": "a" * 64, "source_zip_path": None,
        "source_previous_counts": counts, "source_next_counts": counts,
        "attitude_solution_dropout_events": 1,
        "longest_attitude_solution_dropout_seconds": 86400,
    }))
    (data / "manifest.json").write_text(json.dumps({
        "status": "completed", "requested_days": 1, "days_processed": 1,
        "not_published_dates": [], "per_day_status": {date: "validated"},
    }))

    result = audit(data)
    assert result["status"] == "passed_structural_and_statistical"
    assert result["totals"]["invalid_quaternion_seconds"] == 86400
    assert result["longest_solution_dropout_seconds"] == 86400
