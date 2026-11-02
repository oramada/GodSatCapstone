# GoDSAT study: current scientific results

Generated 2026-10-25T18:57:34.887384+00:00. The six-page governing PDF has been supplied, read and hashed. Its requirement audit currently records 0 remaining execution/audit items. The user authorized documented sensor and baseline assumptions; exact published-baseline reproduction is not claimed. This is an executed simulation study with observational reference checks.

The configured optimization does not establish an all-target custody improvement. Additional held-out dates show lower observable-target custody for the DOE recommendation. Observed availability and injected losses affect the simulated tasking responses, but neither provides a measured fleet failure-effectiveness estimate. Only results with the required completed component audits are included below.

## Implemented system and estimands

The learned-policy experiments use six present-day active-payload sensor hosts and 18 orbital targets per scene, with separate LEO, MEO, GEO and HEO host groups. Scenes select dense observable target clusters; they are not random samples of all catalogue targets. Each episode lasts one hour at 60-second steps. Historical SGP4 states determine geometry; detection probabilities, field of regard, slew constraints, custody persistence and observation failures are modeled. Current active status is backcast through time and does not establish historical operations.

The shared categorical neural actor and centralized critic differ from the available original framework’s Q-table/gradient controller and global ClaimMap state machine. A separate greedy urgency/slew scheduler scales to all fresh, usable catalogue targets. These controllers and target denominators are separate estimands. [Source fidelity comparison](../docs/source-fidelity.md).

Custody continuity concerns target-time slots within the modeled custody interval. Observable custody uses observable slots; its denominator differs from all-target custody. Slew responses are normalized angle proxies, not joules or propellant. Failed-observation proxies do not identify false physical tracks. CPU execution and zero GPU use do not establish a GPU speedup.

## Orbital coverage and physical reference checks

The reconstructed native-epoch union contains 79,405,779 records for 40,206 objects over 2022-10-09 through 2026-10-09. It includes an independently replayed final-date supplement and retains five flagged propagation failures. The readable four-hour union contains 352,687,032 planned rows, 8,772 samples per object and exact audited cohort membership.

| Four-hour row status | Rows | Fraction of planned grid |
|---|---:|---:|
| successful | 222,294,843 | 63.029% |
| sgp4 errors | 34,678 | 0.010% |
| stale or missing | 130,357,511 | 36.961% |

Missing or stale rows remain unavailable. The complete grid is not a complete measured trajectory. Sampled tasking episodes also do not imply continuous four-year operations. [Readable grid and provenance](../outputs/catalog-trajectory-combined-20261024/manifest.json).

Matched operational ILRS CPF reference samples compare historical SGP4 with numerical two-body/J2 and J2 plus solar/lunar gravity. The numerical propagators start from archived SGP4 epoch states, with explicit TEME/GCRS handling. Both simplified numerical models agree less closely with CPF on this sample; adding force terms has not demonstrated improved orbit accuracy. CPF itself is an operational product rather than independent truth.

| Target | Matched epochs | SGP4 median separation (km) | J2 (km) | J2 + Sun/Moon (km) |
|---|---:|---:|---:|---:|
| lageos1 | 487 | 0.1794 | 0.4771 | 0.4595 |
| lageos2 | 399 | 0.3512 | 1.0417 | 1.0576 |
| lares | 488 | 0.4900 | 0.7298 | 0.7257 |
| starlette | 486 | 0.3094 | 3.3260 | 3.3217 |

The tasking campaign remains bound to its frozen annual-source snapshot. A separate final-date refresh check completed 96 conditions over the two final midnight hours, with full episode cohorts, shared IDs and shared validity masks. All 16 original full-cohort responses matched exactly; independently rebuilt controls and 12 sampled replays passed. The largest change in the 20%-minus-zero effect was 0.00000710 percentage points for all-target custody and 0.00003821 points for observable custody. These two-window checks do not establish population robustness or orbit accuracy. [Source-refresh sensitivity](../outputs/final-date-tasking-source-refresh-20261024/report.md).

The separate monthly common-frame tasking comparison passed its audit. It addresses response sensitivity within one-hour scenes, not long-horizon orbit truth or equivalence. [Monthly policy and force sensitivity](../outputs/awp-sun-moon-teme-policy-monthly-20261024/report.md).

## Optimization and additional-date evaluation

The four-regime campaign completed 16 screening treatments, 15 CCD treatments, 31 BO treatments and 15 validation retrains. The selected factors were learning_rate, actor_width, critic_depth. Screening plus CCD and the BO search each use 31 treatment runs. Twelve extra center retrains are separate model-adequacy diagnostics, not part of that original matched treatment budget.

The primary paired intervals use five trained seeds after regime aggregation. The additional-date intervals first average paired seeds and regimes within each of 20 dates, then cluster by date. These intervals answer different questions and are not interchangeable.

| Response | Primary DOE − baseline, 95% interval | Additional 20 dates, DOE − baseline, date-clustered 95% interval |
|---|---:|---:|
| All-target custody (pp) | -1.7037 [-6.4869, +3.0795] | -0.5558 [-1.2290, +0.1174] |
| Normalized slew proxy | -0.003651 [-0.006757, -0.000544] | +0.001097 [+0.000005, +0.002188] |
| Reward/objective units | -0.0155 [-0.0625, +0.0314] | -0.0014 [-0.0084, +0.0057] |

On the additional dates, observable-target custody changes by -3.1462 [-4.7163, -1.5762] percentage points. The primary slew reduction does not persist on those dates. These results do not justify a general improvement claim.

The center-replicated custody surface has lack-of-fit p=0.00834; the objective surface has p=0.07623. Nonrejection for the objective does not prove adequacy. The fitted stationary-point classification is saddle_or_flat; it is not a demonstrated optimum.

## Measured availability and paired loss-process sensitivity

The audited CASSIOPE attitude product supplies 1,398 published daily products in a 1,462-day request; 64 publisher-confirmed unpublished days remain unknown. The unavailable one-minute solution fraction is 25.301% on published days. Definitive attitude solutions interpolate sensor information; these flags are not a log of every instantaneous sensor failure or prospective onboard availability. Unknown-day bounds and serial-dependence sensitivity are reported separately. [Availability analysis](../outputs/attitude-availability-20261024/report.md).

Across 1,930,638 overlapping within-day hour windows, the completely unavailable-hour fraction is 4.538%; the fitted stationary Markov reference gives 0.00000690%. Those windows overlap and are not independent samples. This descriptive mismatch does not by itself quantify tasking consequences.

Both tasking processes now cover the same 208 weekly dates, four regimes and paired zero/source-rate conditions: 1,664 responses each. All 832 baseline cells match, and all 108 reported moving-block intervals were independently reproduced. Each process also passed 24 sampled deterministic action replays. The following changes concern observable-target custody, in percentage points.

| Hosts | Empirical loss − zero | Markov loss − zero | Markov − empirical | 13-week-block interval for process contrast |
|---|---:|---:|---:|---:|
| LEO | -0.0692 | -0.0723 | -0.0031 | [-0.0081, +0.0019] |
| MEO | -1.5612 | -1.8779 | -0.3167 | [-0.5522, -0.1099] |
| GEO | -5.4645 | -5.3330 | +0.1315 | [-0.0997, +0.3729] |
| HEO | -0.2825 | -0.2955 | -0.0129 | [-0.0573, +0.0238] |

These are pointwise, fixed-profile conditional intervals. Realized loss counts, timing and later adaptive actions all differ between processes; the contrast does not isolate burst structure at equal realized loss frequency. One spacecraft’s retrospectively fitted availability applied independently to hypothetical hosts does not establish fleet reliability. [Complete paired-process analysis](../outputs/measured-paired-process-comparison-20261024/report.md).

Geometry sensitivity uses 340 baseline episodes and 2,253 paired single-successful-observation suppressions across 68 quarterly cells. All grouped statistics passed audit, and an alternate loss branch reproduced 85 sampled counterfactuals. These 18-target learned-policy probes condition on a successful baseline observation and occupied range/slew bin. Differences between bins also reflect date, target and checkpoint composition. They are separate from all-catalogue loss-rate effects. [Geometry results and figure](../outputs/geometry-single-loss-quarterly-20261024/report.md).

## Observational cross-checks and remaining limits

| Source | Valid use | Inference not established |
|---|---|---|
| DUST onboard star-tracker imagery | Capture/annotation gaps and angular candidate consistency | Hardware dropout rates, NORAD identity accuracy or held-out stellar calibration truth |
| ILRS acquired normal points and CPF | Range arithmetic, acquired-return quality associations and operational orbit-product consistency | Unsuccessful acquisition probability, independent CPF orbit truth or causal return-quality effects |
| Durham optical detections | Catalogue/astrometric checks and gaps conditional on bracketed detections | Unconditional acquisition or hardware-failure rates |
| CASSIOPE definitive attitudes | Published-product validity masks and hypothetical availability sensitivity | Historical fleet availability or prospective sensor-failure prediction |

[Source and audit index](../outputs/study-execution/evidence-index.json) identifies the individual reports and receipts. Synthetic probabilities remain assumptions even when orbital geometry and availability sequences originate in real data.


## Daily all-catalogue paired loss study

All 1,462 daily UTC epochs and four host regimes completed, giving 5,848 paired cells and 11,696 response rows. Each date samples one hour, so this covers approximately 4.17% of the calendar hours rather than continuous four-year tasking. Targets are fresh valid catalogue objects at each epoch; population size and observability change with time.

The intervention is injected 20% persistent burst loss versus a paired zero-loss reference. The following intervals use circular blocks of 30 consecutive daily paired effects, conditional on these modeled episodes. They are serial-dependence sensitivity estimates, not calibrated fleet reliability bounds.

| Hosts | All-target custody change (pp) | 30-day block interval (pp) | Observable custody change (pp) | 30-day block interval (pp) |
|---|---:|---:|---:|---:|
| LEO | -0.0169 | [-0.0174, -0.0164] | -0.0565 | [-0.0581, -0.0548] |
| MEO | -0.0160 | [-0.0165, -0.0156] | -1.2511 | [-1.5706, -0.9572] |
| GEO | -0.0166 | [-0.0171, -0.0162] | -4.1730 | [-4.2995, -4.0436] |
| HEO | -0.0153 | [-0.0158, -0.0147] | -0.2705 | [-0.3482, -0.2037] |

All-target and observable-target denominators remain distinct. Other block lengths and annual sensitivity are retained in [the temporal analysis](../outputs/full-catalog-tasking-daily-20261024/temporal_uncertainty.json). This greedy catalogue reference is separate from the 18-target learned-policy studies.
All 48 temporal intervals and 60 annual means were independently reproduced. Twenty-four complete response records from first/middle/last dates also matched fresh deterministic action replays; this does not constitute a replay of every unsampled action.

## Quarterly frozen-policy loss-rate study

The full grid contains 81,600 responses: 17 sampled dates, four host regimes, five frozen checkpoints, 20 paired simulation replicates, two loss processes and six requested rates. Model-training seed and simulation replicate are paired across rates; responses are averaged within sampled date before date-level uncertainty is estimated.

The table selects the 20% burst-loss contrast against zero. Six-date moving blocks are blocks of consecutive sampled dates, not six calendar days. Other rates, both processes and 3-/6-/12-date block sensitivities remain in the component report. Intervals are pointwise and conditional on the simulated scenes; they do not turn 81,600 rows into independent observational samples.

| Hosts | Mean custody change (pp) | 6-sampled-date block interval (pp) |
|---|---:|---:|
| LEO | -1.5959 | [-1.8312, -1.3901] |
| MEO | -1.5618 | [-1.6611, -1.4604] |
| GEO | -0.5848 | [-0.6687, -0.4733] |
| HEO | -1.3221 | [-1.5495, -1.1866] |

Complete rate/mode responses and uncertainty sensitivity: [quarterly component report](../outputs/dropout-five-policy-quarterly-20261024/dropout_report.md). These are injected losses under synthetic detection assumptions, without dropout-specific policy retraining.

## Supplied-PDF physical-response followthrough

The new LEO campaign follows the supplied design under user-authorized baseline and sensor assumptions. It completed another 16 screening, 15 CCD and 31 BO treatments plus five-seed validation. Unlike the earlier proxy studies, it reports torque/speed-limited actuator energy in joules and explicit simulated false-track slots. All 77 checkpoint selection responses and 25 held-out responses passed replay and independent action reconstruction.

DOE − baseline custody is -0.3519 [-6.6044, +5.9007] percentage points; modeled mean slew energy changes by +0.008775 [-0.095973, +0.113522] J per host-step. These results do not establish the manuscript placeholder gains.

Separate center replication and 2,295 quarterly parameter/loss sensitivity responses complete the assumed-model validation. They do not calibrate hardware or change the original campaigns retrospectively. [Full supplied-design report, figures and sensitivity results](governing-design-study-20261025.md).

## Software validation scope

The current combined run records 116 core tests passed, 2 core tests skipped, 155 research tests passed and 3 research tests failed. All three research failures are missing-artifact errors for older source-refresh, MOST 2004/2005 and Sentinel inventory outputs. The broader suite is not green. [Exact counts and missing artifacts](../outputs/study-execution/validation-review.json).

The legacy PDF audit now reads metadata from hashed source bytes and leaves unavailable or unextractable content unknown. Its missing-file and actual-page-count regressions do not establish the governing PDF’s compliance.

## Final component evidence and protocol review

| Requirement | Current evidence |
|---|---|
| Daily all-catalogue final source/response audit | passed; results integrated above |
| Daily temporal-dependence analysis | passed; results integrated above |
| Daily temporal statistics reproduction | passed; results integrated above |
| Quarterly five-checkpoint dropout final audit | passed; results integrated above |
| Quarterly temporal uncertainty reproduction | passed; results integrated above |
| Source protocol compliance | requirement_by_requirement_verified |

[Governing PDF requirement audit](../docs/governing-pdf-audit.md); [Authorized sensor assumptions](../docs/physical-sensor-assumptions.md).

The governing protocol has been executed as an explicitly documented simulation adaptation under user-authorized baseline and sensor assumptions. Exact published-controller replication, calibrated hardware performance and positive placeholder improvement claims are not established.
