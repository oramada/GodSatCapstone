# GodSatFactorial

A reproducible student starter for the supplied paper's hyperparameter design-of-experiments study, with a separate simulated sensor-dropout extension. It contains the Python code, experiment configs, data-fetch scripts, and tests. The multi-gigabyte orbital archive and generated results are downloaded or created locally; they are not stored in Git.

## What the supplied paper studies

The paper is about hyperparameter optimization, not satellite or sensor dropout. It studies seven GoDSAT agent hyperparameters using a 16-run fractional-factorial screen, then a 15-run response-surface design over the leading factors, with validation and a matched-budget Bayesian-optimization comparison. It does not state two formal numbered research questions. A useful teaching breakdown is:

1. Which agent-training settings have the largest effect on simulated tasking outcomes?
2. Which settings perform best, and how does the designed experiment compare with equal-budget Bayesian optimization?

The PDF's Results section still contains placeholders for its tables and plots even though its abstract and conclusion state numerical improvement claims. Those claims cannot be audited from the supplied results section. This repository is a runnable student implementation, not an exact reproduction of the original GoDSAT agent or a verification of the paper's claims. Read [the study protocol](docs/study-protocol.md) before interpreting results.

The repository also includes a separate controlled simulation of independent and burst sensor outages. That extension measures average policy-response changes by outage rate, mode, orbit regime, and date. It does not find which relative sensor-target geometries make an outage most valuable or costly. The PDF mentions expanding to additional LEO multi-target geometries as future work, but it does not connect that to dropout.

The repository now also includes the wider orbit-catalog, attitude, optical-observation, and tasking audits developed during the study. These supplementary runners and saved report snapshots are described in [the research extension guide](docs/research-extension.md). The base student setup remains sufficient for the paper campaign; some additional analyses require optional packages and separately downloaded data.

## Set up on a student computer

The supported baseline is **Python 3.11** on x86-64 Windows 10/11, x86-64 or ARM64 Linux, or Apple Silicon macOS 14+. The test workflow runs on Windows, Linux, and Apple Silicon macOS, plus Python 3.13 on Linux. This follows [PyTorch's published binary platform matrix](https://github.com/pytorch/pytorch/blob/main/RELEASE.md#hardware--software-support-in-binary-build-matrix). A GPU is optional: CPU is the portable baseline, while `auto` uses CUDA or Apple MPS when PyTorch reports one as available. Current official PyTorch wheels do not support Intel Macs; see the [upstream Intel Mac note](https://github.com/pytorch/pytorch/issues/169874) and the Conda-forge setup below.

Install Python 3.11, then clone the repository. AWP is not needed for the paper campaign, so a regular clone is enough:

```bash
git clone https://github.com/oramada/GodSatFactorial.git
cd GodSatFactorial
```

On macOS or Linux:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m pytest -q
.venv/bin/python -m godsat doctor
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[test]"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m godsat doctor
```

On an Intel Mac, create the environment with Miniforge/Conda-forge so it can supply its maintained PyTorch build, then install the repository without asking pip to replace that build:

```bash
conda create -n godsat -c conda-forge python=3.11 "pytorch>=2.8,<3" duckdb matplotlib numpy pyarrow pytz scipy sgp4 pytest pip
conda activate godsat
python -m pip install --no-deps -e .
python -m pytest -q
python -m godsat doctor
```

`python -m godsat doctor` reports the Python/platform/device, checks local archive sizes and cohort files, and prints the next data-preparation commands. Add `--require-data` to make it exit with an error until those inputs are ready. It checks sizes only; the fetch script verifies the pinned SHA-256 hashes.

The full archive download is about **4.41 GB**. The filtered historical cohort adds roughly 1.6 GB in the reference run, before local scenarios, Python packages, and experiment outputs. Plan for at least 10 GB of free disk space. `--recurse-submodules` is only needed for the optional AWP source under `vendor/AWP`; the main SGP4 study and tests do not require AWP. For AWP propagation commands, install its Python dependencies with `python -m pip install -e ".[awp]"`; see [the AWP notes](docs/awp.md) for its separate licensing status.

## Download and prepare the data

```bash
.venv/bin/python scripts/fetch_four_year_data.py
.venv/bin/python scripts/export_current.py
```

In PowerShell, use `.venv\Scripts\python.exe` in place of `.venv/bin/python` in these commands and the examples below.

The first command downloads five pinned annual Parquet files from the [Space-Track TLE history mirror](https://huggingface.co/datasets/juliensimon/space-track-tle-history) and verifies their expected sizes and SHA-256 hashes. It also retrieves a SATCAT snapshot from [CelesTrak](https://celestrak.org/pub/satcat.csv), records its retrieval time and hash, and keeps that snapshot locally. Use `--refresh-catalog` when you intentionally want a newer catalog snapshot. See [data sources and limits](docs/data-sources.md).

The second command builds `data/current_payload_orbit_history.parquet` from historical elements for objects classified by that SATCAT snapshot as payloads that are currently not decayed and Earth-orbiting. It also writes a small provenance JSON beside the derived data. That filter describes current catalog status applied to old records; it cannot tell whether an object was operational at each historical epoch.

The archive is about 4.41 GB on download. The current-payload derived Parquet is additional (roughly 1.6 GB in the reference run). To use all catalog objects instead of the filtered sensor cohort, set `"sensor_cohort": "all"` in a copied config; do not edit the checked-in baseline when running a variant.

To reconstruct SGP4 TEME state vectors at all source element epochs for the full catalog, run `.venv/bin/python scripts/export_state_vectors.py --cohort all`. This creates another multi-gigabyte local dataset of irregularly sampled states. It is not a continuous or measured trajectory; see [data source limits](docs/data-sources.md).

## Run the student study

The checked-in CPU config runs without a GPU. The complete campaign is substantial: it trains the baseline and factorial treatments, fits the response surface, runs the search comparison, and retrains validation seeds. Keep the config at `cpu` for the closest cross-machine comparison. Pass `--device auto` before the subcommand if you want to use an available CUDA or Apple MPS accelerator; it may select different hardware on different computers.

```bash
.venv/bin/python -m godsat --config configs/paper-exact-cpu.json campaign \
  --output outputs/paper-exact-cpu \
  --center-replicates 3
.venv/bin/python scripts/audit_campaign.py --output outputs/paper-exact-cpu
```

For PowerShell, replace `.venv/bin/python` with `.venv\Scripts\python.exe`. In the Intel Mac Conda environment, use `python -m godsat` and `python` after activation.

The campaign writes its configurations, metrics, and report under `outputs/`. The three center replicates improve pure-error estimation. Use `--center-replicates 1` for the smaller protocol described in the paper. Outputs can be shared separately; they are intentionally ignored by Git.

To measure the modeled effect of dropout, run the intervention against the DOE-recommended checkpoints saved by that campaign:

```bash
.venv/bin/python -m godsat --config configs/paper-exact-cpu.json dropout-study \
  --baseline-output outputs/paper-exact-cpu \
  --output outputs/dropout-study \
  --replicates 20 \
  --dates quarterly
.venv/bin/python scripts/audit_dropout_results.py --output outputs/dropout-study
.venv/bin/python scripts/analyze_dropout.py outputs/dropout-study
```

This is a controlled simulation with frozen policies and synthetic outage assumptions. A quarterly, all-regime run can take substantial time; its results estimate the simulator's response, not real-world sensor effectiveness.

For an optional AWP check after preparing data:

```bash
.venv/bin/python -m godsat --config configs/paper-exact-cpu.json awp-check --date 2026-10-01T00:00:00Z
```

AWP comparison is a propagation-model sensitivity check. It is not an independent measurement of orbit error. AWP also does not replace the archived TLE source.

## What is included

- `godsat/`: orbit-history loading, scenario preparation, simulated tasking agent, factorial/response-surface campaign, dropout experiments, reports, and optional AWP adapters.
- `configs/`: default, Apple MPS, and portable CPU experiment configs.
- `scripts/`: pinned data retrieval, experiment execution, and supplementary catalog, attitude, optical-data, and tasking audits.
- `tests/` and `.github/workflows/`: portable baseline tests and cross-platform CI. `research_tests/` holds additional tests for runs that need local research data or optional dependencies.
- `docs/research-results/`: compact snapshots of the paper, dropout, and orbit-validation reports; full raw inputs, checkpoints, and generated trajectory tables remain local.
- `data/raw/source-manifest.json`: pinned source revision, file sizes, and expected hashes; the large archive itself is fetched on demand.

## License and attribution

This repository's original code is MIT licensed. The archived TLE data is a separate dataset under the source repository's CC BY 4.0 terms and must be attributed; see [data sources](docs/data-sources.md). AWP is a separate upstream project included as a pinned Git submodule, and its terms must be reviewed independently.
