# Setup and commands

Run commands from the repository root with Python 3.11 or newer. CPU is the default. A GPU is optional; supported CUDA or Apple MPS devices can be selected explicitly.

## Install

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[test,ground]"
python -m pytest -q
python -m godsat --help
python -m godsat doctor
```

Additional dependencies are grouped as extras: `.[ground]` for terrestrial/celestial coordinate transforms, `.[awp]` for numerical propagation, `.[telemetry]` for telemetry products, and `.[analysis]` for supplementary analysis. Some optical-image tools also require separately installed image-processing libraries; inspect their imports before use. The optional AWP submodule is obtained with `git submodule update --init vendor/AWP`.

## Prepare historical data

The historical source archive is about 4.41 GB, before derived files. Allow at least 10 GB of free space. The original source manifest stays committed; downloaded files remain local.

```bash
python -m scripts.data.fetch_four_year_data
python -m scripts.data.export_current
python -m scripts.data.prepare_iridium_next_cohort
python -m godsat doctor --require-data
```

The first tool verifies the pinned annual archives and retrieves a catalogue snapshot. The second builds the reusable payload-history source. The third filters it to the committed Iridium NEXT ID allowlist and writes a provenance receipt; it does not refresh membership or reset the active scope. The broader source archive is input material, not permission to add other constellations to a scenario.

## What each check means

| Command | What success establishes | What it does not establish |
| --- | --- | --- |
| `python -m pytest -q` | Portable code tests pass | Research results or physical validity |
| `python -m godsat doctor --require-data` | Configured local data files are available | Calibrated sensor performance or a completed study |
| `python -m godsat prepare ...` | Pinned NEXT targets and six ground sites can be prepared | A completed tracking experiment |
| `python -m godsat campaign` | Configured ground/NEXT factorial campaign can execute | Full replicated diagnostics and dropout extension; use the runner below |

## Current scenario readiness

```bash
python -m godsat prepare --date 2026-10-01T00:00:00Z
```

This prepares all 80 pinned NEXT targets with six ground tracking sites. Missing historical elements stay unavailable. Ground station coordinates are published; sensor characteristics and energy are assumptions. This is not measured NEXT service performance.

Run the registered factorial, BO, five-seed validation, independently replicated CCD diagnostics and paired dropout study:

```bash
python -m scripts.experiments.run_iridium_ground_study \
  --output outputs/iridium-next-ground-20261104
```

After the runner finishes, reconcile the saved statistics/training signatures and render the shareable report:

```bash
python -m scripts.validation.audit_iridium_ground_study --input outputs/iridium-next-ground-20261104
python -m scripts.figures.render_iridium_ground_study --input outputs/iridium-next-ground-20261104
```

The runner resumes only when its registered config and source hashes match. Use a fresh output folder after changing source or configuration. The study has a fixed 40-episode training budget; it does not establish convergence. The diagnostic runs are additional to the matched 31-versus-31 search counts. MEO remains disabled. Mixed-catalogue and orbital-only tasking runners cannot bypass the active ground-system scope.

## Historical work and optional checks

Historical configs are in `configs/archive/`; they describe previous experiments and are not current-scope configurations. They cannot bypass the active Iridium NEXT/ground scope. Full raw outputs and checkpoints stay in local `outputs/`; compact shared evidence is under `reports/evidence/`.

```bash
python -m pytest tests/research --collect-only -q
python -m scripts.formal.verify_lean_study --help
```

Research tests may require optional packages, original-source checkouts, or downloaded measurements. The [research-test guide](../tests/research/README.md) describes their scope. Lean has its own pinned toolchain and [build instructions](../formal/README.md).
