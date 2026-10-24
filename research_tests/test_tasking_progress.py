import json

from scripts.write_tasking_progress import write_progress
from scripts.run_full_catalog_tasking import REGIMES


def test_progress_counts_only_a_contiguous_complete_date_prefix(tmp_path):
    output = tmp_path / "run"
    dates = ["2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
    for date in dates:
        (output / "cells" / date[:10]).mkdir(parents=True)
        for regime in REGIMES:
            rows = [
                {"date": date, "orbit_regime_sensor_hosts": regime,
                 "requested_outage_rate": rate}
                for rate in (0.0, 0.2)
            ]
            (output / "cells" / date[:10] / f"{regime}.json").write_text(json.dumps({
                "simulator_version": 2, "source_sha256": "fixture", "rows": rows,
            }))
    (output / "cells" / dates[1][:10] / "heo.json").unlink()

    result = write_progress(output, dates)

    assert result["status"] == "running_checkpointed"
    assert result["final_results"] is False
    assert result["verified_completed_date_regime_groups"] == 4
    assert result["complete_date_count"] == 1
    assert result["completed_date_range"] == [dates[0], dates[0]]
    assert len(result["cell_files_sha256"]) == 4
