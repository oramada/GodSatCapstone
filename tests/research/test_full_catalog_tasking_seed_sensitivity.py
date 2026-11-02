from scripts.validation.audit_full_catalog_tasking_seed_sensitivity import effects_by_regime, seed_comparison
from godsat.dropout import monthly_dates
from scripts.experiments.run_full_catalog_tasking import REGIMES


def _rows(seed, offset):
    rows = []
    for date_index, date in enumerate(monthly_dates()):
        for regime_index, regime in enumerate(REGIMES):
            base = 0.1 + date_index / 10000 + regime_index / 1000 + offset
            for rate in (0.0, 0.2):
                rows.append({"date": date, "orbit_regime_sensor_hosts": regime,
                    "simulation_seed": seed, "requested_outage_rate": rate,
                    "custody_continuity": base - rate / 10,
                    "observable_custody": base - rate / 20,
                    "mean_slew_energy_proxy": 0.1,
                })
    return rows


def test_full_catalog_seed_effects_pair_by_date_and_regime():
    rows = _rows(90210, 0)
    result = effects_by_regime(rows)
    assert len(result) == 4
    assert all(r["custody_change_20pct_minus_0"]["n_date_clusters"] == 48 for r in result)
    assert all(abs(r["custody_change_20pct_minus_0"]["mean"] + 0.02) < 1e-12 for r in result)


def test_seed_by_outage_interaction_is_paired_across_same_dates():
    primary = _rows(-1, 0)
    replicate = _rows(90210, 0.01)
    comparison = seed_comparison(replicate, primary)
    assert len(comparison) == 4
    assert all(abs(r["metrics"]["custody_continuity"]["seed_interaction_mean"]) < 1e-12
               for r in comparison)
    assert all(len(r["date_effects"]) == 96 for r in comparison)
