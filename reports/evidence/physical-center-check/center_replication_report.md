# Supplementary RSM center-point replication

This analysis preserves the exact paper-matched 15-run CCD and adds 12 independently seeded center-point retrains. The source CCD has 1 center observations; the augmented center count is 13, with 27 total response-surface observations. The added runs use the source campaign’s regimes (LEO), training/validation dates, sensor-host cohort `current_payload`, and target cohort `all`.

The selected coded factors, in design-column order, are `learning_rate, critic_depth, actor_width`. All 13 center observations use distinct training seeds. The companion integrity audit checks every added run record and checkpoint hash, refits the surfaces from saved response rows, and reports pure-error degrees of freedom [12] for measured CPU responses.

## Lack-of-fit diagnostics

| Response | Center mean | Center sample SD | Lack-of-fit F | p-value | Pure-error df | Lack-of-fit df | Augmented RMSE |
|---|---:|---:|---:|---:|---:|---:|---:|
| objective | 0.096706 | 0.025207 | 2.318 | 0.108 | 12 | 5 | 0.029694 |
| custody_continuity | 0.160328 | 0.021114 | 3.907 | 0.025 | 12 | 5 | 0.028756 |
| slew_energy_proxy | 0.018870 | 0.003291 | 2.632 | 0.079 | 12 | 5 | 0.004004 |
| false_track_proxy | 0.034801 | 0.010150 | 2.011 | 0.149 | 12 | 5 | 0.011560 |
| wall_seconds | 7.493644 | 0.273572 | 0.283 | 0.914 | 12 | 5 | 0.243021 |
| gpu_hours | 0.000000 | 0.000000 | not estimable | not estimable | not estimable | not estimable | 0.000000 |
| slew_energy_joules | 0.307435 | 0.034320 | 4.121 | 0.021 | 12 | 5 | 0.047528 |
| false_track_rate | 0.000350 | 0.001261 | 0.605 | 0.698 | 12 | 5 | 0.001185 |
| false_observation_rate | 0.000527 | 0.001900 | 0.561 | 0.729 | 12 | 5 | 0.001773 |

Responses without a positive replicated pure-error estimate have no estimable lack-of-fit test; see the table.

## Objective-surface sensitivity

| Fit | Classification | Stationary point in coded order `learning_rate, critic_depth, actor_width` | Best point constrained to [-1, 1]^3 |
|---|---|---|---|
| Prior 15-observation CCD | saddle_or_flat | `[-2.2128, -0.9599, -1.3463]` | `[-1.0, -1.0, 1.0]` |
| 27-observation augmented CCD | saddle_or_flat | `[0.1594, -0.2108, -0.9929]` | `[-0.8157, -1.0, 1.0]` |

The objective classifications are `saddle_or_flat` for the prior fit and `saddle_or_flat` after replication. The augmented stationary point exceeds the tested bounds on: no selected factors. The constrained recommendation changes from `[-1.0, -1.0, 1.0]` to `[-0.8157, -1.0, 1.0]`; its displacement is 0.1843 coded units. Use held-out validation to assess a recommendation.

At alpha=0.05, lack of fit is rejected for: custody_continuity, slew_energy_joules. It is not rejected for: objective, slew_energy_proxy, false_track_proxy, wall_seconds, false_track_rate, false_observation_rate. The test is not estimable for: gpu_hours. A failure to reject lack of fit does not establish model adequacy or validate an optimum.

The added observations estimate variation among independently seeded runs at one center configuration. They do not reproduce the unavailable original GoDSAT implementation or published baseline, add new orbit/sensor evidence, or validate real-world tasking performance.
