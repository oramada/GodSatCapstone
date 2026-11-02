# GoDSAT: execution of the supplied factorial/RSM design

The six-page governing PDF has been read and executed as a documented simulation adaptation. The user authorized assumptions for the unavailable published actor–critic baseline, sensor hardware and false-track definition. The original PDF is preserved; its placeholder improvement claims are replaced here by measured simulation outcomes. [Protocol audit](../docs/governing-pdf-audit.md).

The DOE recommendation changes held-out true custody by -0.3519 percentage points (paired 95% interval [-6.6044, +5.9007]) and mean modeled slew energy by +0.008775 J per host-step (interval [-0.095973, +0.113522]). These five-seed results do not establish the manuscript’s claimed custody gain or energy reduction.

## Design and source corrections

The exact treatment design has 16 randomized seven-factor resolution-IV screening runs, 15 face-centered CCD runs, 31 Bayesian trials and 15 independent learned-policy validation retrains (five each for baseline, DOE and BO). Greedy/random controls add ten evaluation rows. Three historical training windows, a separate 2025 selection window and a held-out 2026 test window retain six catalogue-payload hosts, 18 orbital targets, 60-second steps and 40 training episodes per treatment. All source arrays and checkpoint bytes are hashed.

The source generators E=ABC, F=ABD, G=ACD produce I=ABCE=ABDF=ACDG=AEFG=BCFG=BDEG=CDEF. This corrects the printed equation 4. All 15 independent contrast chains are retained: seven main, seven two-factor and one three-factor chain. The high-order-only noise estimate has one df; the full-residual estimate assumes all eight remaining chains are inactive. Neither is replicated pure error. Confounded two-factor terms remain alias chains.

The source’s asserted learning-rate/discount/width ranking is not imposed. The new measured objective ranking selects learning_rate, critic_depth, actor_width. Coefficients, full covariance/ANOVA and responses are retained for every recorded response.

![All 15 contrasts](../outputs/governing-design-followthrough-20261025/governing-design-physical-leo-20261025-half-normal.png)

![Confounded interactions](../outputs/governing-design-followthrough-20261025/governing-design-physical-leo-20261025-interactions.png)

## Physical response assumptions

[Complete assumptions and equations](../docs/physical-sensor-assumptions.md). Slews are torque/speed-limited rest-to-rest rotations with 2 kg m² inertia, 0.02 N m torque, 2 deg/s maximum rate, 0.65 efficiency and 0.05 W moving-drive power. Energy is acceleration work divided by efficiency plus moving electronics energy. No regeneration, holding/tracking power, friction or wheel momentum-management budget is modeled.

Conditional on a nominal missed look without dropout, a 0.005 Bernoulli probability produces an incorrectly associated clutter report. Declared tracks last 180 seconds; the latest report determines the simulated true/false label. False-track rate counts false active declared-track slots over all active declared-track slots. The policy sees reported age, including clutter; true custody uses a separate truth state. False-observation rate is separately recorded. These are simulated association errors, not measured operational failure rates.

Geometry and custody are evaluated on 60-second slots, without resolving continuous slew/exposure timestamps or within-slot target motion. The fixed 40-episode budget supports comparison within that budget; it does not establish convergence. The greedy control outperforms the learned policies on held-out custody, so these results do not establish a learned-policy advantage.

## Held-out results

Mean ± 95% Student-t half-width over five independently retrained seeds. Energy is joules per host per 60-second step; false-track rate is a fraction. A zero observed rate and zero t interval mean no events in those five replicates, not proof of zero population risk.

| Policy | True custody | Slew J / host-step | False-track fraction | Wall seconds / seed |
|---|---:|---:|---:|---:|
| baseline | 0.195000 ± 0.025638 | 0.326351 ± 0.069944 | 0.000000 ± 0.000000 | 7.463853 ± 0.040504 |
| doe_recommended | 0.191481 ± 0.057435 | 0.335126 ± 0.074701 | 0.000000 ± 0.000000 | 7.566170 ± 0.086886 |
| bayesian_best | 0.191667 ± 0.038243 | 0.357607 ± 0.092866 | 0.000000 ± 0.000000 | 7.655441 ± 0.067999 |
| greedy | 0.746296 ± 0.004945 | 1.084685 ± 0.037037 | 0.000000 ± 0.000000 | 0.041117 ± 0.000186 |
| random | 0.520370 ± 0.020324 | 0.921893 ± 0.045098 | 0.000000 ± 0.000000 | 0.036690 ± 0.000123 |

Learned-policy runtime includes retraining, validation and held-out evaluation per seed; heuristic runtime covers evaluation only. These scopes are disclosed rather than pooled into an efficiency ranking.

| Comparison | Custody change (pp), paired 95% interval | Slew change (J), paired 95% interval | False-track fraction change, paired 95% interval |
|---|---:|---:|---:|
| doe_recommended − baseline | -0.351852 [-6.604405, +5.900701] | +0.008775 [-0.095973, +0.113522] | +0.000000 [+0.000000, +0.000000] |
| bayesian_best − baseline | -0.333333 [-4.598509, +3.931842] | +0.031256 [-0.065952, +0.128463] | +0.000000 [+0.000000, +0.000000] |

## Pure-error diagnostics and ridge recommendation

The original 15-point CCD has one center and cannot support a pure-error lack-of-fit test. Twelve separately randomized, independently seeded center retrains give 13 center observations, 12 pure-error df and five lack-of-fit df when variance is positive. These extra diagnostics are outside the original 31-treatment optimization budget.

| Response | Canonical classification | Lack-of-fit p | Pure-error df |
|---|---|---:|---:|
| objective | saddle_or_flat | 0.10809311140332223 | 12 |
| custody_continuity | saddle_or_flat | 0.024673650730618703 | 12 |
| slew_energy_joules | saddle_or_flat | 0.02068161835786423 | 12 |
| false_track_rate | saddle_or_flat | 0.6981527913114283 | 12 |

Failure to reject lack of fit is not proof of adequacy. Saddles, flat responses, sparse false events and weak pure-error assumptions do not establish a validated optimum. Bounded/ridge recommendations are evaluated empirically on holdout, without promoting placeholder gains into findings.

```json
{
  "learning_rate": 1.0000000000000026e-05,
  "discount": 0.9450000000000001,
  "actor_width": 256,
  "critic_depth": 2,
  "entropy": 0.055,
  "claim_resolution": 80,
  "target_tau": 0.025500000000000002
}
```

![Residual diagnostics](../outputs/governing-design-physical-leo-20261025/plots/residual_diagnostics.png)

![Quadratic contour slices](../outputs/governing-design-physical-leo-20261025/plots/response_contours.png)

## Compute cost and energy accounting

| Cost basis | DOE search cost | BO trials within that cap | Selected BO trial | Same five-seed recommendation |
|---|---:|---:|---|---|
| wall_seconds | 166.340 s | 22 | bo_11 | True |
| cpu_seconds | 543.561 s | 19 | bo_11 | True |

These are retrospective complete-trial prefixes of measured treatment cost. They exclude acquisition/orchestration overhead and do not equalize contemporaneous load. Full BO still has 31 trials; equal trial count alone does not imply equal seconds. CPU execution records zero GPU-hours, with no GPU speedup claim. The 128-run full factorial versus 31-run DOE ratio is 4.13×, not an order of magnitude.

Each treatment additionally records a host-energy scenario estimate of 50 W × measured wall duration. That is an authorized assumed-power calculation, not a calibrated power measurement or incremental process-energy attribution. All calibrated-energy fields remain unavailable. Host energy and gimbal energy have separate units and meanings. Cost-performance ratios retain their accounting boundaries.

| Learned policy | Custody / end-to-end wall second, mean ± 95% half-width | Assumed host Wh / seed, mean |
|---|---:|---:|
| baseline | 0.026125 ± 0.003413 | 0.103665 |
| doe_recommended | 0.025313 ± 0.007629 | 0.105086 |
| bayesian_best | 0.025039 ± 0.005015 | 0.106326 |

## Parameter and loss-process sensitivity

The frozen-policy extension has 2,295 responses: 17 quarterly dates × three learned configurations × five training seeds × nine nominal/parameter/loss variants. No policy retraining is performed under changed hardware or losses. These dates include the original training/selection/test epochs; this is sensitivity analysis, not 17 independent holdouts. Average paired seeds within date before computing pointwise circular moving-block intervals; blocks of six sampled dates are not six calendar days.

| Policy | Variant − nominal | Custody change (pp) | Six-date block interval (pp) |
|---|---|---:|---:|
| baseline | no_clutter | +0.00000 | [+0.00000, +0.00000] |
| baseline | high_clutter | +0.00000 | [+0.00000, +0.00000] |
| baseline | low_inertia | -0.29739 | [-0.43028, -0.19172] |
| baseline | high_inertia | +0.39978 | [+0.29085, +0.48260] |
| baseline | no_drive_power | +0.00000 | [+0.00000, +0.00000] |
| baseline | high_drive_power | +0.00000 | [+0.00000, +0.00000] |
| baseline | independent_loss_20pct | -0.94227 | [-0.98693, -0.89216] |
| baseline | burst_loss_20pct | -1.77778 | [-2.08279, -1.51852] |
| doe_recommended | no_clutter | +0.00000 | [+0.00000, +0.00000] |
| doe_recommended | high_clutter | -0.00218 | [-0.00327, +0.00000] |
| doe_recommended | low_inertia | -0.20806 | [-0.31373, -0.10131] |
| doe_recommended | high_inertia | -0.01525 | [-0.28322, +0.23096] |
| doe_recommended | no_drive_power | +0.00000 | [+0.00000, +0.00000] |
| doe_recommended | high_drive_power | +0.00000 | [+0.00000, +0.00000] |
| doe_recommended | independent_loss_20pct | -1.04466 | [-1.10458, -0.97930] |
| doe_recommended | burst_loss_20pct | -1.86710 | [-2.16454, -1.55880] |
| bayesian_best | no_clutter | +0.00000 | [+0.00000, +0.00000] |
| bayesian_best | high_clutter | +0.00000 | [+0.00000, +0.00000] |
| bayesian_best | low_inertia | -0.29412 | [-0.53600, -0.03047] |
| bayesian_best | high_inertia | +0.10022 | [-0.04684, +0.25272] |
| bayesian_best | no_drive_power | +0.00000 | [+0.00000, +0.00000] |
| bayesian_best | high_drive_power | +0.00000 | [+0.00000, +0.00000] |
| bayesian_best | independent_loss_20pct | -1.13399 | [-1.40196, -0.87361] |
| bayesian_best | burst_loss_20pct | -2.23312 | [-2.61332, -1.80283] |

The raw summary also contains modeled-energy and false-track effects with 1-/3-/6-date intervals. No-clutter controls must produce zero false reports. Changing inertia changes both slew feasibility and energy. Clutter changes reported ages and can change later actions. No single parameter contrast is a calibrated fleet effect.

## Validation and release

All 77 saved checkpoint selection responses and all 25 held-out policy/seed responses were replayed. All 77 treatment signatures and finite 40-episode loss histories were verified; three complete training reruns matched every history value and checkpoint tensor exactly. Independent action reconstruction checks accepted looks, positive torque work, nominal/clutter draws, true custody and false-track slots. Sensitivity audit verifies all 2,295 rows, 72 paired effect vectors and 216 block intervals; 81 sampled policy/physics replays cover first/middle/last dates, all policies and variants at the first model seed.

[Physical campaign inputs, raw responses and checkpoints](../outputs/governing-design-physical-leo-20261025/) · [Center diagnostics](../outputs/governing-design-physical-leo-center-20261025/center_replication_report.md) · [Sensitivity source and statistics](../outputs/physical-sensor-sensitivity-20261025/summary.json) · [Complete screening and compute-prefix analysis](../outputs/governing-design-followthrough-20261025/report.md).

The earlier four-regime optimization, all-catalogue historical reconstruction, daily/quarterly injected loss studies, measured-product availability, optical and ILRS reference checks remain separate audited experiments. [Combined scientific report](current-study-20261024.md). This new experiment does not retroactively change their sensor model or denominators.
