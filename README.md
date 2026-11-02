# GoDSAT Factorial

Satellite-tasking experiments, sensor-dropout analysis, and Lean verification for the supplied [methodology paper](docs/papers/methodology.pdf).

**Current scope: Iridium NEXT and ground systems.** MEO is an optional future extension and is disabled. Ground-system roles are unresolved, so the current orbital-only runner rejects a combined-study campaign. Earlier experiments used different satellite selections and do not establish results for this new scope.

## Start here

- [Project status and results](reports/README.md): what ran, what was found, and what remains incomplete.
- [Setup and commands](docs/setup.md): install, prepare data, and check the runtime.
- [Current system scope](docs/iridium-next-ground-scope.md): membership, exclusions, and ground-system requirements.
- [Documentation index](docs/README.md): methodology, assumptions, and reproduction limits.
- [Lean verification](formal/README.md): checked mathematics and proof boundaries.

The implemented actor–critic study has not established the draft's claimed custody or energy improvements. It is a documented simulation adaptation; published-baseline reproduction and whole-controller equivalence remain unverified.

## Quick setup

Use Python 3.11 or newer. From the repository root:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
python -m godsat doctor
```

Tests do not require the large datasets. `doctor` reports missing local data; it does not download it or certify that the ground-system model is ready. See [setup](docs/setup.md) for data preparation and optional dependencies.

## Repository map

| Directory | Contents |
| --- | --- |
| `godsat/` | Simulation, actor–critic training, experimental design, scope checks, CLI |
| `configs/` | Active scope, pinned Iridium NEXT membership, current config |
| `configs/archive/` | Historical mixed-catalogue experiment configurations |
| `scripts/` | Tools grouped into data, experiments, analysis, validation, figures, and formal checks |
| `tests/unit/` | Portable automated tests; the default CI suite |
| `tests/research/` | Supplementary tests requiring optional dependencies or local evidence |
| `docs/` | Setup, methodology, assumptions, and the supplied paper |
| `reports/` | Result summaries, compact evidence, and historical report snapshots |
| `formal/` | Lean source, pinned dependencies, and proof documentation |
| `data/`, `outputs/` | Local datasets and generated results; excluded from Git |
| `vendor/AWP/` | Optional upstream propagation submodule |

Use `python -m scripts.<group>.<tool>` for research tools. The [tool index](scripts/README.md) lists common commands. The [migration map](docs/repository-layout.json) locates files moved from the earlier flat layout. Historical numerical evidence and provenance receipts are preserved; archived reports may retain their original paths.

## Attribution

Original repository code is MIT licensed. Orbital source data, the original GoDSAT framework, and optional AWP code have separate terms. See [data sources](docs/data-sources.md), [upstream GoDSAT attribution](formal/UPSTREAM-LICENSE), and [AWP notes](docs/awp.md).
