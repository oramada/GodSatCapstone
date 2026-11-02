import datetime as dt

from scripts.validation.audit_catalog_orbit_availability import classify_lifecycle


UTC = dt.timezone.utc


def test_catalog_lifecycle_uses_calendar_day_bounds():
    launch = dt.date(2024, 2, 1)
    decay = dt.date(2024, 3, 1)
    assert classify_lifecycle(dt.datetime(2024, 1, 31, 23, 59, tzinfo=UTC), launch, decay) == "before_launch"
    assert classify_lifecycle(dt.datetime(2024, 2, 1, tzinfo=UTC), launch, decay) == "catalog_lifetime_estimate"
    assert classify_lifecycle(dt.datetime(2024, 3, 1, 23, 59, tzinfo=UTC), launch, decay) == "catalog_lifetime_estimate"
    assert classify_lifecycle(dt.datetime(2024, 3, 2, tzinfo=UTC), launch, decay) == "after_decay"


def test_catalog_lifecycle_preserves_unknown_metadata():
    when = dt.datetime(2024, 2, 1, tzinfo=UTC)
    assert classify_lifecycle(when, None, None) == "lifecycle_unknown"
    assert classify_lifecycle(when, dt.date(2024, 1, 1), None, catalog_matched=False) == "lifecycle_unknown"
