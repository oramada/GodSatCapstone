# Study protocol and interpretation

## Source authority and configured scope

The governing six-page factorial/RSM design PDF was supplied and inspected on 2026-10-25. Its SHA-256 is `e705ce0a7bc80496f37ab8da5a8ad9ba2cefe5619e7f530b15ecc902abb64e95`. The [requirement audit](governing-pdf-audit.md) maps the actual sections to implementation and evidence. It confirms the 16-run resolution-IV screen, 15-run face-centered CCD, five-seed retraining and 31-treatment Bayesian reference.

The printed defining relation differs from its generators; the implementation follows E=ABC, F=ABD, G=ACD. One center observation provides no pure-error estimate, so separate independent center retrains support lack-of-fit testing. Claims of 11–14% custody gain and 9% energy reduction are unsubstantiated placeholders in the supplied Results section. The study reports observed outcomes, including negative results.

The user authorized documented simulation assumptions for the unavailable published actor–critic baseline and calibrated sensor definitions. A new [mechanical/clutter model](physical-sensor-assumptions.md) and separate LEO campaign implement those assumptions. Their dimensioned slew energy and simulated false-track responses are distinct from the original proxy-based campaigns. Exact published-baseline reproduction, hardware calibration and MATLAB parity remain outside the evidence.

The [source fidelity comparison](source-fidelity.md) distinguishes the shared neural actor/central critic from the available original Q-table/gradient framework. The [execution guide](study-execution.md) records completed studies and the ongoing PDF followthrough.

## Experiment stages

The `campaign` command performs a 16-run, resolution-IV fractional-factorial screen over seven factors; a face-centered response-surface design over the three leading factors; an internal Bayesian-search comparison; and five-seed validation. It records four tasking responses, run configuration, random seeds, device, and wall time. The default center replicate count is one; passing `--center-replicates 3` adds repeated center observations for a more useful estimate of experimental noise.

Training dates, a later validation date, and a held-out test date are specified in `configs/archive/paper-exact-cpu.json`. These are short sampled episodes drawn from the four-year archive, not four years of continuous agent training. Factor effects apply to this simulator, its selected scenarios, and its reward/response definitions.

## Separate simulated dropout extension

The `dropout-study` command tests simulated independent and burst sensor outages across configured rates, orbit regimes, and dates, then reports aggregate response changes relative to zero dropout. It uses injected losses rather than measured outage telemetry. Separate measured-profile runs apply audited CASSIOPE attitude-solution availability to hypothetical hosts; these remain simulated tasking interventions rather than measured fleet reliability. The supplied PDF contains no dropout experiment; these are user-requested extensions.

Orbit-regime averages do not identify which individual sensor-target geometry benefits or suffers most from a lost observation. A separate [single-observation sensitivity study](../outputs/geometry-single-loss-quarterly-20261024/report.md) now samples successful baseline observations within joint range/slew groups and suppresses one at a time. It pairs subsequent random draws and allows the frozen policy to adapt, then measures whole-episode custody changes. This is conditional on a successful baseline observation and the selected occupied geometry group; it does not estimate unconditional operational outage value. Other geometry dimensions, including line-of-sight clearance, field-of-regard margin and contention, are not independently resolved by those two-dimensional groups. This geometry extension is requested by the user, rather than specified by the supplied PDF.

## Reproducibility and limits

- Data checksums and the SATCAT retrieval snapshot are recorded locally.
- Training and design seeds are saved with generated runs.
- `audit_campaign.py` checks that campaign records match the requested design and validation protocol.
- The current-payload cohort applies today's catalog status to old orbital records. It does not reconstruct each object's historical operational status.
- TLE records are element sets. SGP4 propagates them into states for a scenario; gaps and element updates mean the archive is not a continuous measured trajectory.
- Sensor locations, field of regard, detection probability, observation noise, and tasking outcomes are modeled. These results are not evidence of real sensor performance without independent ground observations.
- AWP comparisons are alternate force-model runs initialized from archived SGP4 states. Agreement or separation is model sensitivity, not ground-truth error.

Students should preserve their exact config, data snapshot manifests, code revision, and output audit with any report. Each campaign summary records Python, OS/architecture, GoDSAT package, dependency versions, a source-code hash, and a hash of the prepared scenario arrays. Cached treatments are reused only when those inputs and the device/runtime match; use a new output directory when they change. Keep CPU selected for the closest cross-machine comparison. Some current Apple MPS gradient operations do not have strict deterministic implementations; MPS runs use seeded execution with PyTorch warning-only determinism and can vary by backend and hardware.
