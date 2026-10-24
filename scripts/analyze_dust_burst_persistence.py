"""Estimate a conditional burst-persistence proxy from DUST track-label gaps."""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_dust_dropout import DEFAULT_ARCHIVE, DOI, MD5, file_md5, read_sessions


def session_counts(sessions):
    result = {}
    gap_lengths = collections.Counter()
    for name, session in sorted(sessions.items()):
        missing = runs = 0
        for frames in session["tracks"].values():
            ordered = sorted(set(frames))
            gaps = [right - left - 1 for left, right in zip(ordered, ordered[1:])
                    if right - left > 1]
            missing += sum(gaps)
            runs += len(gaps)
            gap_lengths.update(gaps)
        result[name] = {
            "missing_internal_frames": missing,
            "internal_gap_runs": runs,
            "failure_to_failure_transitions": missing - runs,
        }
    return result, gap_lengths


def ratio(rows):
    failures = sum(row["missing_internal_frames"] for row in rows)
    continuations = sum(row["failure_to_failure_transitions"] for row in rows)
    return continuations / failures if failures else None


def analyze(archive=DEFAULT_ARCHIVE, *, replicates=20000, seed=20261010):
    archive = pathlib.Path(archive).resolve()
    digest = file_md5(archive)
    if digest != MD5:
        raise ValueError(f"DUST archive checksum mismatch: expected {MD5}, found {digest}")
    sessions, inventory, _, _, _ = read_sessions(archive)
    counts, gap_lengths = session_counts(sessions)
    observed = list(counts.values())
    estimate = ratio(observed)
    rng = random.Random(seed)
    names = list(counts)
    draws = []
    for _ in range(replicates):
        sampled = [counts[name] for name in rng.choices(names, k=len(names))]
        value = ratio(sampled)
        if value is not None:
            draws.append(value)
    draws.sort()
    missing = sum(row["missing_internal_frames"] for row in observed)
    spans = sum(
        max(frames) - min(frames) + 1
        for session in sessions.values() for frames in session["tracks"].values() if frames
    )
    gaps = sum(gap_lengths.values())
    return {
        "status": "completed",
        "source": "DUST CASSIOPE/FAI MOT track annotations",
        "source_doi": DOI,
        "source_archive": archive.relative_to(ROOT).as_posix() if archive.is_relative_to(ROOT) else str(archive),
        "source_archive_md5": digest,
        "sessions": len(sessions),
        "annotated_track_count": sum(len(session["tracks"]) for session in sessions.values()),
        "conditional_internal_span_frames": spans,
        "unlabeled_internal_frames": missing,
        "unlabeled_frame_fraction": missing / spans if spans else None,
        "internal_gap_runs": gaps,
        "gap_length_frames": {str(k): gap_lengths[k] for k in sorted(gap_lengths)},
        "failure_state_persistence_proxy": estimate,
        "session_cluster_bootstrap_ci95": [
            draws[int(0.025 * len(draws))],
            draws[min(len(draws) - 1, int(0.975 * len(draws)))],
        ] if draws else [None, None],
        "session_cluster_bootstrap_replicates": replicates,
        "session_cluster_bootstrap_seed": seed,
        "session_counts": counts,
        "interpretation": (
            "Conditional annotation-gap persistence proxy: (unlabeled internal frames minus gap runs) / "
            "unlabeled internal frames. The first/last labeled frames define a censored positive-track "
            "window. Gaps may be detector misses, obscuration, annotation omissions, or track behavior; "
            "this is not a measured hardware dropout parameter or a complete sensor opportunity rate."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=pathlib.Path,
                        default=ROOT / "outputs/dust-burst-persistence-empirical/summary.json")
    parser.add_argument("--replicates", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20261010)
    args = parser.parse_args()
    summary = analyze(args.archive, replicates=args.replicates, seed=args.seed)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"status": summary["status"], "persistence_proxy": summary["failure_state_persistence_proxy"],
                      "ci95": summary["session_cluster_bootstrap_ci95"], "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
