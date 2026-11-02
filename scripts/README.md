# Research tools

Run tools from the repository root as Python modules, for example:

```bash
python -m scripts.data.fetch_four_year_data --help
python -m scripts.formal.verify_lean_study --help
```

Direct paths also work, such as `python scripts/data/fetch_four_year_data.py --help`.

| Group | Purpose | Examples |
| --- | --- | --- |
| `data/` | Download, filter, propagate, and index source inputs | `fetch_four_year_data`, `export_current`, `prepare_iridium_next_cohort` |
| `experiments/` | Training, search, dropout, and campaign orchestration | `check_baseline_training_budget`, `run_dropout_campaign`, `run_physical_sensitivity` |
| `analysis/` | Statistics and comparisons over saved responses | `analyze_governing_design`, `analyze_dropout` |
| `validation/` | Data audits, deterministic replays, and physical cross-checks | `audit_physical_campaign`, `validate_awp_against_ilrs` |
| `figures/` | Figures and reports from saved evidence | `render_physical_study`, `render_study_results` |
| `formal/` | Lean evidence checks and original-controller probes | `verify_lean_study`, `probe_original_controller` |
| `archive/` | Historical archive coverage check, still used by the finalization pipeline | `audit` |

Many tools describe historical experiments. Their presence does not mean they are applicable to the current scope or runnable without their inputs. Several write output files when executed; `archive/audit` executes its historical coverage check when invoked; it is not a help-only command. Use the supported [setup guide](../docs/setup.md) first.

The active scope excludes mixed-constellation tasking, and the existing orbital-only campaign is blocked while ground systems are required. Do not interpret archived configurations or output folders as completed Iridium NEXT plus ground results.

## Which tools do I actually need?

For the current setup, use only:

1. `python -m scripts.data.fetch_four_year_data` — fetch and verify the pinned source archive.
2. `python -m scripts.data.export_current` — build the payload-history source.
3. `python -m scripts.data.prepare_iridium_next_cohort` — extract the pinned NEXT membership.
4. `python -m godsat doctor` — check local runtime and input availability.
5. `python -m godsat prepare --date 2026-10-01T00:00:00Z` — prepare the restricted orbital fixture.

These steps do not run a complete Iridium NEXT/ground experiment. The current
campaign gate remains in force until the ground-system model is defined.

The other groups preserve earlier experiments, validation methods and their
reproducibility tools. Use them only for the corresponding documented study;
they are not extra setup steps. See the [maintenance review](../docs/maintenance.md)
for the removal decision and the [results index](../reports/README.md) for evidence.
