# Supplementary research code

This repository includes the additional source code used to examine four-year catalog coverage, sampled all-catalog tasking, attitude products, optical observations, and orbit-propagation sensitivity. The runners live in `scripts/`, and additional configurations live in `configs/`. The minimal paper campaign does not need these extensions.

## Inputs and dependencies

The code is committed; downloaded measurements, satellite archives, derived trajectories, trained checkpoints, and bulky run outputs are not. The ignore rules exclude local contents under `data/` and `outputs/` while retaining the pinned source manifest. Follow [the data-source guide](data-sources.md) for the historical orbital archive. Other analyses have their own input requirements; inspect a runner's `--help` and source before launching it.

The base `.[test]` install covers the paper study and portable tests. Some supplementary runners need the `awp`, `telemetry`, or `analysis` extras, and optical-image tools may need Pillow and SEP. These tools are optional and are not installed by the baseline setup.

## Saved reports

Small text and audit snapshots from the local research runs are under [`research-results/`](research-results/README.md). They are dated results, not a claim that every analysis can be rerun without first fetching its source data. Check each report's methods and limitations. In particular, the dropout work is a simulated intervention with explicit outage assumptions; it does not measure real spacecraft sensor-failure rates. The supplied paper's claimed improvements were not reproduced by this implementation.

The supplementary checks under `research_tests/` are kept outside the default `pytest` test path because some depend on local research inputs or optional packages. The ordinary `python -m pytest -q` command remains data-independent.
