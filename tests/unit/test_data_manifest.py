import json
from pathlib import Path


def test_pinned_archive_manifest_has_all_five_verified_years():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "data/raw/source-manifest.json").read_text())

    assert manifest["repository"] == "juliensimon/space-track-tle-history"
    assert manifest["revision"] == "974246e5ff943175a4a736047a87668fa0361850"
    assert [Path(item["path"]).stem for item in manifest["files"]] == [
        "tle_2022", "tle_2023", "tle_2024", "tle_2025", "tle_2026"
    ]
    assert all(
        item["size"] == item["lfs"]["size"]
        and len(item["lfs"]["oid"]) == 64
        for item in manifest["files"]
    )
    assert sum(item["lfs"]["size"] for item in manifest["files"]) == 4_408_816_978
