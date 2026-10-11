"""Parse CASSIOPE/e-POP daily attitude-quaternion products."""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from cdflib import CDF, cdfepoch


def parse_attquat_zip(payload: bytes) -> tuple[pa.Table, dict]:
    """Read a published CAS_AttQuat CDF zip into a typed Arrow table and audit."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".cdf")]
        if len(members) != 1:
            raise ValueError(f"Expected one CDF member, found {len(members)}")
        cdf_bytes = archive.read(members[0])
    fd, cdf_path = tempfile.mkstemp(suffix=".cdf")
    with os.fdopen(fd, "wb") as handle:
        handle.write(cdf_bytes)
    cdf = CDF(cdf_path)
    try:
        info = cdf.cdf_info()
        required = {
            "Timestamp", "q", "Yaw", "Pitch", "Roll",
            "Data_Source_Previous", "Data_Source_Next",
            "Time_To_Previous", "Time_To_Next",
        }
        variables = set(info.zVariables) | set(info.rVariables)
        missing = sorted(required - variables)
        if missing:
            raise ValueError(f"CDF is missing required variables: {missing}")

        timestamps = cdfepoch.to_datetime(cdf.varget("Timestamp"))
        q = np.asarray(cdf.varget("q"), dtype=np.float64)
        if q.ndim != 2 or q.shape[1] != 4 or len(timestamps) != len(q):
            raise ValueError(f"Unexpected time/quaternion dimensions: {timestamps.shape}, {q.shape}")
        if len(timestamps) == 0 or np.any(np.diff(timestamps).astype("timedelta64[ns]") <= np.timedelta64(0, "ns")):
            raise ValueError("Attitude timestamps must be nonempty and strictly increasing")
        if np.any(np.diff(timestamps).astype("timedelta64[s]") != np.timedelta64(1, "s")):
            raise ValueError("CAS_AttQuat timestamps are expected on a complete 1 Hz grid")

        arrays = {
            "timestamp_utc": pa.array(timestamps, type=pa.timestamp("ns", tz="UTC")),
            "q1": pa.array(q[:, 0]), "q2": pa.array(q[:, 1]),
            "q3": pa.array(q[:, 2]), "q4": pa.array(q[:, 3]),
            "yaw_deg": pa.array(cdf.varget("Yaw"), type=pa.float64()),
            "pitch_deg": pa.array(cdf.varget("Pitch"), type=pa.float64()),
            "roll_deg": pa.array(cdf.varget("Roll"), type=pa.float64()),
            "data_source_previous": pa.array(cdf.varget("Data_Source_Previous"), type=pa.int8()),
            "data_source_next": pa.array(cdf.varget("Data_Source_Next"), type=pa.int8()),
            "time_to_previous_s": pa.array(cdf.varget("Time_To_Previous"), type=pa.float32()),
            "time_to_next_s": pa.array(cdf.varget("Time_To_Next"), type=pa.float32()),
        }
        table = pa.table(arrays)
    finally:
        os.unlink(cdf_path)

    q_valid = np.isfinite(q).all(axis=1)
    previous = np.asarray(table["data_source_previous"])
    next_ = np.asarray(table["data_source_next"])
    missing_indices = np.flatnonzero(~q_valid)
    breaks = np.flatnonzero(np.diff(missing_indices) > 1) + 1
    runs = np.split(missing_indices, breaks) if len(missing_indices) else []
    audit = {
        "cdf_member": members[0],
        "cdf_sha256": hashlib.sha256(cdf_bytes).hexdigest(),
        "samples": len(timestamps),
        "first_utc": str(timestamps[0]),
        "last_utc": str(timestamps[-1]),
        "cadence_seconds": 1,
        "valid_quaternion_seconds": int(q_valid.sum()),
        "invalid_quaternion_seconds": int((~q_valid).sum()),
        "attitude_solution_dropout_events": len(runs),
        "longest_attitude_solution_dropout_seconds": max((len(run) for run in runs), default=0),
        "attitude_solution_dropout_intervals_utc": [
            {"start": str(timestamps[run[0]]), "end": str(timestamps[run[-1]]), "seconds": len(run)}
            for run in runs
        ],
        "dropout_source_previous_seconds": int((previous == 0).sum()),
        "dropout_source_next_seconds": int((next_ == 0).sum()),
        "source_previous_counts": {str(code): int((previous == code).sum()) for code in range(7)},
        "source_next_counts": {str(code): int((next_ == code).sum()) for code in range(7)},
        "finite_quaternion_norm_min": float(np.linalg.norm(q[q_valid], axis=1).min()) if q_valid.any() else None,
        "finite_quaternion_norm_max": float(np.linalg.norm(q[q_valid], axis=1).max()) if q_valid.any() else None,
    }
    return table, audit


def write_attquat_product(payload: bytes, parquet_path, audit_path) -> dict:
    """Parse, validate, and persist one source product plus a compact audit."""
    import json
    from pathlib import Path

    parquet_path, audit_path = Path(parquet_path), Path(audit_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    table, audit = parse_attquat_zip(payload)
    audit["source_zip_sha256"] = hashlib.sha256(payload).hexdigest()
    audit["source_zip_bytes"] = len(payload)
    temp = parquet_path.with_suffix(parquet_path.suffix + ".tmp")
    pq.write_table(table, temp, compression="zstd", compression_level=5)
    temp.replace(parquet_path)
    audit_path.write_text(json.dumps(audit, indent=2) + "\n")
    return audit
