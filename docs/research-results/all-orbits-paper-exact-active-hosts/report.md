# GoDSAT historical-orbit research run

Study: **paper-exact 15-run CCD and 31-run Bayesian reference across four orbit regimes; current-active-payload sensor hosts**. All reported values were measured in this implementation.

This is a new shared-policy multi-agent actor-critic implementation. The original GoDSAT code, published baseline configuration, and calibrated sensor model were not supplied. The manuscript contains placeholder results; its 11–14% custody and 9% energy claims are not reproduced or assumed here.

**Ground-sensor data:** the workspace includes 247,322 ILRS LAGEOS-1 laser-ranging normal points from 39 stations. These observations were not used to fit the tasking policy or dropout model. The tasking study still assumes hypothetical satellite-hosted optical/radar sensors; no catalog-wide calibration or failed-acquisition telemetry is available.

Executed 16 screening treatments, 15 response-surface treatments, 31 Bayesian treatments, and 15 independent retrains. Training wall time: 104.2 seconds on cpu; measured accelerator-active time: 0.000000 GPU-hours. No calibrated machine energy estimate is available.

## Data and scenario

Historical source spans October 2022–October 2026. Training windows are separated by date from the 2025 selection window and 2026 held-out test window. Scenario orbit regimes: {"training": ["leo", "meo", "geo", "heo"], "validation": ["leo", "meo", "geo", "heo"], "test": ["leo", "meo", "geo", "heo"]}. Sensor-host candidates come from the `current_active_payload` cohort; targets come from the `all` cohort, which includes debris and rocket bodies when set to `all`. Each episode selects a dense observable cluster with hypothetical sensor hardware. These are short sampled windows, not four years of continuous training. All inference uses element epochs at or before the sampled time.
The sensor-host set intersects the current CelesTrak active-GP snapshot with no-decay Earth payloads in SATCAT. This current snapshot is backcast through historical element records; it does not establish that each spacecraft was operational at every sampled historical date.
AWP two-body plus J2 was compared with historical SGP4 over one hour after transforming the SGP4 TEME states to GCRS with Astropy: LEO NORAD 63166: 1.866 km; MEO NORAD 25773: 1.191 km; GEO NORAD 32794: 0.130 km; HEO NORAD 23420: 14.014 km. These are model separations, not errors against measured truth.

## Screening

Correct defining relation from E=ABC, F=ABD, G=ACD: I = ABCE = ABDF = ACDG = AEFG = BCFG = BDEG = CDEF.
The manuscript’s printed relation differs from its generators. Main effects are clear of two-factor interactions, but two-factor aliases cannot be individually identified.

| Factor | Objective effect | Custody effect | Slew-proxy effect | False-track effect | Runtime effect |
|---|---:|---:|---:|---:|---:|
| learning_rate | -0.008507 | -0.001860 | -0.002541 | -0.010665 | 0.077087 | 0.000000 |
| discount | 0.001852 | -0.001068 | 0.002313 | 0.005400 | 0.060594 | 0.000000 |
| actor_width | 0.008391 | -0.000637 | 0.009537 | 0.018054 | 0.063723 | 0.000000 |
| critic_depth | -0.004282 | 0.000069 | 0.005118 | 0.002964 | 0.115722 | 0.000000 |
| entropy | -0.008912 | 0.000457 | -0.002730 | -0.006573 | -0.085418 | 0.000000 |
| claim_resolution | -0.004225 | -0.000968 | 0.001491 | -0.002607 | 0.064818 | 0.000000 |
| target_tau | 0.003009 | -0.000888 | 0.002604 | 0.001621 | -0.074589 | 0.000000 |

Factors selected by measured absolute objective effect: actor_width, learning_rate, entropy.
Their identities are selected from these observations; the manuscript’s learning-rate/discount/width ranking is not imposed.

![Main effects](plots/main_effects.png)
![All response main effects](plots/all_response_main_effects.png)
![Half-normal](plots/half_normal.png)

## Response surface

The exact paper-matched 15-run face-centered CCD has eight factorial points, six axial points, and one center observation. With no replicated center, pure training error and a formal lack-of-fit test cannot be estimated; see the augmented follow-up campaign for that extension. Bayesian optimization receives the matched 31-treatment budget.

| Response | Canonical classification | Residual RMSE | Lack-of-fit result |
|---|---|---:|---|
| custody_continuity | saddle_or_flat | 0.032132 | not estimable |
| slew_energy_proxy | saddle_or_flat | 0.001540 | not estimable |
| false_track_proxy | saddle_or_flat | 0.007483 | not estimable |
| objective | saddle_or_flat | 0.028365 | not estimable |
| wall_seconds | saddle_or_flat | 0.009919 | not estimable |
| gpu_hours | saddle_or_flat | 0.000000 | not estimable |
Bounded local recommendation (integer factors rounded before retraining):

```json
{
  "learning_rate": 0.0006550509078745036,
  "discount": 0.9450000000000001,
  "actor_width": 256,
  "critic_depth": 3,
  "entropy": 0.1,
  "claim_resolution": 80,
  "target_tau": 0.025500000000000002
}
```

The constrained numerical optimum is exploratory. Review residuals and holdout performance before accepting it; an optimizer returning a point is not evidence of model adequacy.

![Surface contours](plots/response_contours.png)
![Residual diagnostics](plots/residual_diagnostics.png)

## Held-out comparison

Means with 95% Student-t interval half-widths over five independent training/evaluation seeds. Slew energy is a normalized squared-angle proxy; false-track rate is the failed-observation proxy, not measured false positives. Wall time is end-to-end per seed: training, validation, and held-out evaluation for learned policies; held-out evaluation for non-learning baselines. “not recorded” marks legacy results whose non-learning baseline runtimes were not measured.

| Configuration | Custody | Slew proxy | False-track proxy | Mean end-to-end wall seconds per seed | GPU-hours per seed |
|---|---:|---:|---:|---:|---:|
| baseline | 0.1569 ± 0.0172 | 0.0102 ± 0.0011 | 0.0617 ± 0.0105 | 1.356 ± 0.013 | 0.000000 ± 0.000000 |
| doe_recommended | 0.1595 ± 0.0315 | 0.0101 ± 0.0046 | 0.0630 ± 0.0169 | 1.456 ± 0.011 | 0.000000 ± 0.000000 |
| bayesian_best | 0.1618 ± 0.0265 | 0.0113 ± 0.0027 | 0.0671 ± 0.0087 | 1.498 ± 0.015 | 0.000000 ± 0.000000 |
| greedy | 0.6102 ± 0.0059 | 0.0574 ± 0.0044 | 0.0975 ± 0.0093 | 0.105 ± 0.001 | 0.000000 ± 0.000000 |
| random | 0.4223 ± 0.0032 | 0.0563 ± 0.0011 | 0.0900 ± 0.0067 | 0.091 ± 0.001 | 0.000000 ± 0.000000 |

![Validation](plots/validation.png)

Descriptive cost-performance ratios use held-out custody or normalized slew proxy divided by measured end-to-end wall seconds for the same seed. They are not electrical energy efficiency. Learned-policy time includes training and test evaluation; greedy/random time covers evaluation only, so these accounting scopes differ. No calibrated energy measurement or GPU-hours are available for this CPU campaign.

| Configuration | Custody per wall second | Slew proxy per wall second |
|---|---:|---:|
| baseline | 0.115685 ± 0.012908 | 0.007503 ± 0.000750 |
| bayesian_best | 0.108072 ± 0.017801 | 0.007569 ± 0.001808 |
| doe_recommended | 0.109530 ± 0.021580 | 0.006930 ± 0.003122 |
| greedy | 5.830940 ± 0.069531 | 0.548810 ± 0.044627 |
| random | 4.629839 ± 0.048703 | 0.616688 ± 0.008343 |

Paired DOE-minus-baseline changes:

```json
{
  "custody_continuity": {
    "paired_mean_change": 0.0025708061002178593,
    "paired_ci95_half_width": 0.037480198870772745,
    "relative_change_percent": 1.638575966395317
  },
  "slew_energy_proxy": {
    "paired_mean_change": -8.886725308658514e-05,
    "paired_ci95_half_width": 0.005335258615238085,
    "relative_change_percent": -0.8730331838707861
  },
  "false_track_proxy": {
    "paired_mean_change": 0.0012299008184924562,
    "paired_ci95_half_width": 0.01025267774024363,
    "relative_change_percent": 1.9919947830202345
  },
  "objective": {
    "paired_mean_change": 0.0011984721178104729,
    "paired_ci95_half_width": 0.03685070924158731,
    "relative_change_percent": 1.0471721008837864
  }
}
```

Bayesian optimization uses a fixed-prior Matérn-3/2 Gaussian process with expected improvement over a 2,048-point candidate pool and the same number of training treatments. The kernel uses a unit length scale and 0.1 observation noise with Cholesky stabilization. It is budget-matched by run count and episode count, not equal wall time. Hyperparameter widths/depths change compute cost.

A 128-run two-level full factorial versus 31 DOE runs is about a 4.1× reduction, not an order of magnitude. A separate 31-trial random-search reference is reported in `outputs/all-orbits-random-search-31/`.

## Reproducibility

See design CSVs, per-run JSON metadata, model checkpoints, validation seeds, raw responses, coefficients/covariance, ANOVA, and cached scenario source epochs. The baseline is an explicitly chosen reference configuration, not the unpublished original baseline.

The full campaign completed as configured, but the results remain exploratory. Short episode windows, one date in each validation/test split, unavailable published baseline implementation/configuration, missing catalog-wide sensor calibration, and reduced-precision orbital elements limit scientific conclusions. The ILRS observations are not used as sensor-model calibration or dropout labels. Original raw TLE/OMM and representative calibrated sensor data are needed for operational claims.
The independent center-point replication and lack-of-fit audit is reported separately in `outputs/all-orbits-active-hosts-center-replication/center_replication_report.md`; it rejects the quadratic fit for both objective and custody, so this campaign’s fitted optimum is not accepted as validated.
