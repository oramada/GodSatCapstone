import hashlib
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.validation.audit_epop_dropout_masks import audit


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_empirical_mask_archive_replays_quaternion_source(tmp_path):
    data = tmp_path / "attitude"
    (data / "processed" / "2024").mkdir(parents=True)
    day = "2024-01-01"
    n = 86_400
    q = np.ones(n, dtype=np.float64)
    q[0] = np.nan
    q[60] = np.nan
    table = pa.table({
        "q1": pa.array(q), "q2": pa.array(np.ones(n)),
        "q3": pa.array(np.ones(n)), "q4": pa.array(np.ones(n)),
    })
    pq.write_table(table, data / "processed" / "2024" / f"{day}.parquet")
    (data / "independent_audit.json").write_text(json.dumps({
        "status": "passed_structural_and_statistical", "validated_dates": [day],
        "downloaded_days": 1,
    }))
    profile = {
        "status": "completed", "one_minute_attitude_solution_dropout_rate": 2 / 1440,
        "per_day": [{"date": day, "dropout_minutes": 2}],
    }
    (data / "dropout_profile_1minute.json").write_text(json.dumps(profile))
    profile_path = data / "dropout_profile_1minute.json"
    masks_path = data / "dropout_masks_1minute.npz"
    mask = np.zeros((1, 1440), dtype=bool)
    mask[0, :2] = True
    np.savez_compressed(masks_path, dates=np.asarray([day]), dropout=mask)
    sidecar = {
        "status": "completed", "source_profile_sha256": sha(profile_path),
        "mask_archive_sha256": sha(masks_path), "mask_archive_path": str(masks_path),
        "validated_days": 1, "cadence_seconds": 60, "minutes_per_day": 1440,
        "sample_count": 1440, "dropout_count": 2,
    }
    masks_path.with_suffix(".json").write_text(json.dumps(sidecar))

    result = audit(data, masks_path)
    assert result["status"] == "passed_independent_source_replay"
    assert result["sample_count_checked"] == 1440
    assert result["mismatched_samples"] == 0

    mask[0, 2] = True
    np.savez_compressed(masks_path, dates=np.asarray([day]), dropout=mask)
    with pytest.raises(ValueError, match="checksum"):
        audit(data, masks_path)
