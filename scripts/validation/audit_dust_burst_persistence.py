"""Independently reproduce the DUST annotation-gap burst-persistence proxy."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import collections
import json
import math
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analysis.analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, file_md5, read_sessions


def audit(output):
    output = pathlib.Path(output).resolve()
    summary = json.loads(output.read_text())
    archive = pathlib.Path(summary.get("source_archive", DEFAULT_ARCHIVE))
    if not archive.is_absolute():
        archive = ROOT / archive
    digest = file_md5(archive)
    if digest != MD5 or digest != summary.get("source_archive_md5"):
        raise ValueError("DUST archive checksum differs from the publisher or saved analysis")
    sessions, _, _, _, _ = read_sessions(archive)
    per_session = {}
    total_span = total_positive = total_missing = total_runs = total_ff = 0
    gap_lengths = collections.Counter()
    for name, session in sessions.items():
        span = positive = missing = runs = 0
        for frames in session["tracks"].values():
            ordered = sorted(set(frames))
            if not ordered:
                continue
            span += ordered[-1] - ordered[0] + 1
            positive += len(ordered)
            gaps = [b - a - 1 for a, b in zip(ordered, ordered[1:]) if b - a > 1]
            missing += sum(gaps)
            runs += len(gaps)
            gap_lengths.update(gaps)
        per_session[name] = (missing, runs)
        total_span += span
        total_positive += positive
        total_missing += missing
        total_runs += runs
        total_ff += missing - runs
    estimate = total_ff / total_missing if total_missing else None
    rng = random.Random(int(summary["session_cluster_bootstrap_seed"]))
    names = list(per_session)
    boot = []
    for _ in range(int(summary["session_cluster_bootstrap_replicates"])):
        sample = [per_session[name] for name in rng.choices(names, k=len(names))]
        failures = sum(row[0] for row in sample)
        transitions = sum(row[0] - row[1] for row in sample)
        if failures:
            boot.append(transitions / failures)
    boot.sort()
    ci = [boot[int(0.025 * len(boot))], boot[min(len(boot) - 1, int(0.975 * len(boot)))]]
    checks = {
        "archive_hash_matches": True,
        "session_count_matches": len(sessions) == summary["sessions"],
        "annotated_track_count_matches": sum(len(s["tracks"]) for s in sessions.values()) == summary["annotated_track_count"],
        "span_frames_match": total_span == summary["conditional_internal_span_frames"],
        "positive_labels_match": total_positive == summary["conditional_internal_span_frames"] - summary["unlabeled_internal_frames"],
        "unlabeled_frames_match": total_missing == summary["unlabeled_internal_frames"],
        "gap_run_count_matches": total_runs == summary["internal_gap_runs"],
        "gap_length_distribution_matches": {str(k): gap_lengths[k] for k in sorted(gap_lengths)} == summary["gap_length_frames"],
        "persistence_reproduces": math.isclose(estimate, summary["failure_state_persistence_proxy"], rel_tol=0, abs_tol=1e-14),
        "bootstrap_interval_reproduces": all(math.isclose(a, b, rel_tol=0, abs_tol=1e-14)
                                               for a, b in zip(ci, summary["session_cluster_bootstrap_ci95"])),
    }
    if not all(checks.values()):
        raise ValueError(f"DUST burst-persistence audit failed: {checks}")
    return {
        "status": "passed_independent_source_reproduction",
        "source_archive_md5": digest,
        "session_count": len(sessions),
        "annotation_spans": total_span,
        "unlabeled_internal_frames": total_missing,
        "internal_gap_runs": total_runs,
        "failure_state_persistence_proxy": estimate,
        "session_cluster_bootstrap_ci95": ci,
        "checks": checks,
        "interpretation": summary["interpretation"],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=pathlib.Path,
                        default=ROOT / "outputs/dust-burst-persistence-empirical/summary.json")
    args = parser.parse_args()
    path = args.summary if args.summary.is_absolute() else ROOT / args.summary
    result = audit(path)
    output = path.with_name("independent_audit.json")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
