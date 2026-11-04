# Registered NEXT/ground rerun — 2026-11-04

This rerun implements the requested participant restriction. It does not reproduce
an unavailable published actor–critic checkpoint or claim calibrated ground
sensor performance. The ground role is a documented assumption: six generic
tracking sensors at published ground monuments observe NEXT targets.

The runner writes `registered-plan.json` before fitting or inspecting final
performance. The exact source snapshot and scenario hashes accompany the run. After execution, run `scripts.validation.audit_iridium_ground_study` and `scripts.figures.render_iridium_ground_study` to reconcile and publish the saved evidence.
The [scope definition](iridium-next-ground-scope.md) records geometry and sensor
assumptions.

## Frozen experiment

- Six ground sites and all 80 pinned NEXT target IDs; no MEO.
- Training: 2022-10-15, 2023-10-15 and 2024-10-15 UTC, one hour each.
- Development: 2025-10-15 UTC, one hour.
- Held-out comparison: 2026-08-15 and 2026-09-15 UTC, one hour each.
- Forty training episodes per treatment and validation retrain, with no
  convergence claim. Sixty-second steps and 180-second true-custody persistence.
- Exact 16-treatment resolution-IV screen, 15-point CCD, and 31 BO trials.
- Five independently trained seeds for baseline, DOE candidate and BO candidate;
  greedy and random controls use the same held-out scenes and noise convention.
- Actor width affects the actor only; critic width is fixed at 128. Earlier
  experiments coupled these widths, so their width effects cannot be reused.

All settings come from the same seven-factor ranges in the supplied paper.
Factor ranking is measured, not forced to match placeholder text. The reference
settings are the implementation's predefined baseline, not a recovered original
published policy. No final-test outcome changes which candidate is selected.

## Adequacy and uncertainty

Forty-five additional training runs repeat each CCD point three times with
unique training seeds and fixed development evaluation noise. These diagnostic
responses are separate from the optimization budget. Classical lack-of-fit tests
are conditional diagnostics with independence/normality/variance assumptions;
nonrejection does not prove the response model is adequate. Failed fits remain
reported, and their candidate is not promoted to a validated optimum.

Paired custody and modeled-energy comparisons use five training-seed averages
over the two test scenes. Ordinary 95% intervals are descriptive. The two declared
primary claims additionally use 97.5% intervals each, providing a Bonferroni
family error bound of 5%. They do not estimate variation across all possible
historical geometries.

Dropout tests use baseline and DOE policies from all five training seeds, plus a
greedy reference, on both test dates. Six nominal probabilities (0, .05, .10,
.20, .40, .60), independent and burst processes, and 20 paired Monte Carlo seeds
produce 5,280 episode responses. Monte Carlo intervals average the frozen
checkpoints and dates within each noise replicate; they exclude training- and
scenario-population uncertainty. Zero-loss controls must match across processes.

## Compute accounting

Screening, CCD and retraining use four independent worker processes; BO is
sequential. Equal treatment counts are not equal elapsed time. Aggregate measured
per-treatment wall/CPU time, actual end-to-end elapsed time and extra diagnostic
cost are reported separately. This CPU run makes no GPU speedup, calibrated
machine-energy, or tenfold compute-saving claim.

## Reproduction boundaries

The archive contains 290,075 element records for the pinned members, but these
experiments sample dated hours. Missing/stale states are never filled with
invented positions. The model excludes weather, exposure/settling dynamics,
continuous within-slot target motion, tracking-electronics power and measured
false-association calibration. The energy unit is joules per ground sensor per
60-second step. Results describe this simulation and budget only.
