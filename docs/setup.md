# Setup and commands

Run commands from the repository root with Python 3.11 or newer. CPU is the default. A GPU is optional; supported CUDA or Apple MPS devices can be selected explicitly.

## Install

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
python -m godsat --help
python -m godsat doctor
```

Additional dependencies are grouped as extras: `.[awp]` for numerical propagation, `.[telemetry]` for telemetry products, and `.[analysis]` for supplementary analysis. Some optical-image tools also require separately installed image-processing libraries; inspect their imports before use. The optional AWP submodule is obtained with `git submodule update --init vendor/AWP`.

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
| `python -m godsat doctor --require-data` | Configured local data files are available | Ground-system readiness or a completed study |
| `python -m godsat prepare ...` | Restricted orbital inputs can be prepared | A full-constellation or ground-network experiment |
| `python -m godsat campaign` | Currently rejected by the ground-system requirement | There is no supported complete hybrid run yet |

## Current scenario readiness

```bash
python -m godsat prepare --date 2026-10-01T00:00:00Z
```

This prepares orbital inputs from the NEXT allowlist. It does not include ground systems or produce a completed hybrid-system experiment. The configured six-host/18-target preparation is a membership-check fixture, not a full-constellation study. See [current scope](iridium-next-ground-scope.md).

`python -m godsat campaign` and `dropout-study` deliberately reject an orbital-only campaign while ground systems are required. Defining the ground-system role and implementing the matching observation or link model remain necessary. MEO is disabled; GEO/HEO and mixed-catalogue preparation are excluded.

## Historical work and optional checks

Historical configs are in `configs/archive/`; they describe previous experiments and are not current-scope configurations. They cannot bypass the active Iridium NEXT/ground scope. Full raw outputs and checkpoints stay in local `outputs/`; compact shared evidence is under `reports/evidence/`.

```bash
python -m pytest tests/research --collect-only -q
python -m scripts.formal.verify_lean_study --help
```

Research tests may require optional packages, original-source checkouts, or downloaded measurements. The [research-test guide](../tests/research/README.md) describes their scope. Lean has its own pinned toolchain and [build instructions](../formal/README.md).
