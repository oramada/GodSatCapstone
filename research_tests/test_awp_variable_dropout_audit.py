"""Regression checks for non-default outage rates in the independent AWP audit."""
import pytest

from scripts.audit_awp_scenario_validation import dropout_design


def test_dropout_design_uses_configured_custom_rate():
    rate = 0.14552702326874942
    assert dropout_design({"dropout_outage_rate": rate}) == (rate, "14.5527pct")
    assert dropout_design({}) == (0.2, "20pct")
    with pytest.raises(ValueError, match="dropout_outage_rate"):
        dropout_design({"dropout_outage_rate": 0.0})
