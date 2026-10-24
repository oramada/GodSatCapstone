import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_most_published_events_do_not_imply_a_resolved_failure_rate():
    evidence = json.loads(
        (ROOT / "data/ground_sensor/most_2004_2005/attempt_audit.json").read_text()
    )
    rows = evidence["published_summary_table_rows"]
    denominator = evidence["denominator_audit"]

    assert sum(row["reported_result"] == "FAILED" for row in rows) == 4
    assert sum(row["reported_result"] == "SUCCESS" for row in rows) == 2
    assert sum(row["reported_result"] == "N/A" for row in rows) == 1
    assert denominator["listed_failed_target_names"] == 5
    assert denominator["attempt_rate_calculated"] is False
    assert evidence["scope"]["relation_to_four_year_study_window"].startswith("outside")
