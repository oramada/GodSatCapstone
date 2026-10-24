import csv
import hashlib
import json

import pytest

from scripts.audit_random_search_reference import audit


def dump(path, value):
    path.write_text(json.dumps(value) + "\n")


def write_rows(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fixture_campaign(root):
    (root / "runs").mkdir(parents=True)
    (root / "models").mkdir()
    config = {"budget": 2, "config": {"validation_seeds": [101]}}
    checkpoint_hashes = {}
    for index, objective in enumerate((0.1, 0.2)):
        name = f"random_{index:02d}"
        dump(root / "runs" / f"{name}.json", {"objective": objective})
        checkpoint = root / "models" / f"{name}.pt"
        checkpoint.write_bytes(f"checkpoint-{name}".encode())
        checkpoint_hashes[name] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    validation_name = "validate_random_search_best_101"
    checkpoint = root / "models" / f"{validation_name}.pt"
    checkpoint.write_bytes(b"heldout-checkpoint")
    checkpoint_hashes[validation_name] = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    dump(root / "config.json", config)
    dump(root / "summary.json", {
        "selected_run": "random_01",
        "selection_split": "validation",
        "heldout_test_dates": ["2026-10-01T00:00:00Z"],
        "checkpoint_sha256": checkpoint_hashes,
    })
    write_rows(root / "random_search_design.csv", [
        {"name": "random_00", "run": 0}, {"name": "random_01", "run": 1},
    ])
    write_rows(root / "responses.csv", [
        {"name": "random_00", "objective": 0.1},
        {"name": "random_01", "objective": 0.2},
    ])
    write_rows(root / "validation.csv", [
        {"configuration": "random_search_best", "seed": 101},
    ])


def test_audit_accepts_complete_random_search_campaign(tmp_path):
    fixture_campaign(tmp_path)

    result = audit(tmp_path)

    assert result["status"] == "validated_complete"
    assert result["selected_run"] == "random_01"


def test_audit_rejects_changed_checkpoint(tmp_path):
    fixture_campaign(tmp_path)
    (tmp_path / "models" / "random_01.pt").write_bytes(b"changed")

    with pytest.raises(ValueError, match="missing or changed"):
        audit(tmp_path)
