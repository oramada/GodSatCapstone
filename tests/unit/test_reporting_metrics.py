from godsat.experiment import cost_performance_ratios


def test_cost_performance_ratios_are_per_seed_and_keep_accounting_units():
    rows = [
        {"configuration": "policy", "custody_continuity": 0.5,
         "slew_energy_proxy": 0.2, "wall_seconds": 2.0},
        {"configuration": "policy", "custody_continuity": 0.8,
         "slew_energy_proxy": 0.1, "wall_seconds": 4.0},
    ]

    ratios = cost_performance_ratios(rows)["policy"]

    # Average the per-seed ratios: (0.25 + 0.20) / 2, not
    # mean(custody) / mean(runtime), which would silently change the estimand.
    assert ratios["custody_per_wall_second"]["mean"] == 0.225
    assert ratios["slew_proxy_per_wall_second"]["mean"] == 0.0625
    assert ratios["custody_per_wall_second"]["n"] == 2
    assert ratios["custody_per_wall_second"]["ci95_half_width"] > 0


def test_cost_performance_ratios_skip_nonpositive_runtime():
    rows = [
        {"configuration": "policy", "custody_continuity": 0.5,
         "slew_energy_proxy": 0.2, "wall_seconds": 0.0},
    ]

    ratios = cost_performance_ratios(rows)["policy"]

    assert ratios["custody_per_wall_second"] == {
        "mean": None, "ci95_half_width": None, "n": 0
    }


def test_cost_performance_ratios_skip_legacy_missing_runtime():
    rows = [
        {"configuration": "heuristic", "custody_continuity": 0.6,
         "slew_energy_proxy": 0.3, "wall_seconds": ""},
    ]

    ratios = cost_performance_ratios(rows)["heuristic"]

    assert ratios["custody_per_wall_second"]["n"] == 0
