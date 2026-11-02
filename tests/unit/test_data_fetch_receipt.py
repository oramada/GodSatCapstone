import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.data import fetch_four_year_data as fetcher


def configure_fetch(monkeypatch, tmp_path):
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    manifest = raw / "source-manifest.json"
    manifest.write_text(json.dumps({"repository": "test/history", "revision": "pinned",
                                    "files": [{"lfs": {"size": 1}}]}))
    monkeypatch.setattr(fetcher, "ROOT", tmp_path)
    monkeypatch.setattr(fetcher, "MANIFEST_PATH", manifest)
    monkeypatch.setattr("sys.argv", ["fetch_four_year_data.py"])
    return raw


def test_receipt_published_after_archive_and_catalog_verification(monkeypatch, tmp_path):
    raw = configure_fetch(monkeypatch, tmp_path)
    files = [{"path": "data/raw/test.parquet", "sha256": "verified"}]
    catalog = {"sha256": "snapshot"}
    monkeypatch.setattr(fetcher, "fetch_archive", lambda *args: files)
    monkeypatch.setattr(fetcher, "fetch_catalog", lambda *args: catalog)

    assert fetcher.main() == 0
    receipt = json.loads((raw / "manifest.json").read_text())
    assert receipt["status"] == "verified"
    assert receipt["files"] == files
    assert receipt["catalog"] == catalog
    assert receipt["source_manifest_sha256"] == fetcher.sha256_file(raw / "source-manifest.json")


def test_failed_fetch_cannot_leave_stale_verified_receipt(monkeypatch, tmp_path):
    raw = configure_fetch(monkeypatch, tmp_path)
    (raw / "manifest.json").write_text('{"status": "verified"}')
    monkeypatch.setattr(fetcher, "fetch_archive", lambda *args: [])

    def fail(*args):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(fetcher, "fetch_catalog", fail)
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        fetcher.main()
    assert not (raw / "manifest.json").exists()


def test_cohort_export_rejects_incomplete_annual_history(tmp_path):
    scripts = tmp_path / "scripts/data"
    scripts.mkdir(parents=True)
    script = scripts / "export_current.py"
    shutil.copyfile(Path(fetcher.__file__).with_name("export_current.py"), script)
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (raw / "tle_2022.parquet").write_bytes(b"x")
    (raw / "satcat.csv").write_text("NORAD_CAT_ID\n")
    (raw / "source-manifest.json").write_text(json.dumps({"files": [
        {"path": f"data/tle_{year}.parquet", "lfs": {"size": 1}}
        for year in (2022, 2023)
    ]}))

    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)

    assert result.returncode != 0
    assert "Archive input missing or incomplete: tle_2023.parquet" in result.stderr
    assert not (tmp_path / "data/current_payload_orbit_history.parquet").exists()
