# Current study execution

This documents the execution begun on 2026-10-24. The configured campaigns and the supplied-PDF followthrough have completed under the explicitly authorized simulation assumptions. Its authoritative state is in [`outputs/study-execution/plan.json`](../outputs/study-execution/plan.json) and the [completion inventory](../outputs/study-execution/completion-inventory.md). Generated results, model checkpoints and acquired data are local artifacts excluded from Git.

The [current scientific synthesis](../reports/current-study-20261024.md) combines the audited component findings and preserves their distinct estimands and uncertainty calculations. Its companion provenance receipt identifies the consumed source hashes. All original daily/quarterly campaigns and their audits are complete. The supplied-PDF followthrough is tracked separately below.

The governing six-page design PDF was supplied and read on 2026-10-25. The [source-bound requirement audit](governing-pdf-audit.md) identifies manuscript errata and maps every methodology item. The user authorized [documented sensor/baseline assumptions](physical-sensor-assumptions.md). A new LEO factorial/CCD/BO/five-seed campaign computes dimensioned gimbal energy and false-track rates; all 77 checkpoint selection responses and 25 held-out responses passed replay, 12 added center retrains passed audit, and 2,295 parameter/loss responses passed complete source/statistics audit plus 81 sampled independent action reconstructions. Existing `paper-exact` names alone do not prove protocol compliance.

The [source fidelity comparison](source-fidelity.md) records concrete differences between the original Q-table/gradient framework, the Python actor-critic study and the all-catalogue greedy reference. The additional GoDSAT-AT PDF has been inspected and concerns aircraft tracking with ADS-B data, and is separate from the supplied orbital-tasking design.

The [current software validation review](../outputs/study-execution/validation-review.json) records 116 core passes and two skips, plus 155 research passes and three missing-artifact failures. The broader research suite is not green; the three absent inputs are from older source-refresh, MOST and Sentinel executions. The legacy PDF completion entry point now delegates to current evidence and extracts metadata from actual hashed PDF bytes, leaving missing or unreadable content unknown instead of hard-coding page counts and section claims.

## Completed evidence

| Work | Current evidence and scope |
|---|---|
| Orbital source data | Five SHA-256-pinned annual archives; fresh SATCAT and current-active GP receipts; a separately pinned 2026 source refresh |
| Native-epoch states | 79,405,779 rows for 40,206 objects, including 48,265 final-date supplement rows replayed independently in full. Five flagged SGP4 failures remain in the combined dataset. [Combined manifest](../data/historical_state_vectors_combined/manifest.json) |
| Four-hour historical grid | All 352,687,032 planned rows across 1,462 daily parts passed full row/key/state checks and stratified source replay in all 49 months. A combined grid replaces the final two dates with the audited refresh and checks every row's exact cohort membership. [Combined readable dataset](../outputs/catalog-trajectory-combined-20261024/manifest.json). Rows without a recent usable source remain explicitly missing or stale. This is reconstructed ephemeris, not orbit truth. |
| Daily all-catalogue paired tasking | All 1,462 dates, 5,848 paired cells and 11,696 response rows passed the complete source/response audit. All 48 temporal intervals and 60 annual means were independently reproduced, and 24 sampled action replays matched exactly. One hour is sampled per day. [Temporal audit](../outputs/full-catalog-tasking-daily-20261024/independent_temporal_audit.json) |
| Final-date refresh | The separately pinned two-day overlay passed all-row reconciliation and 500 direct state replays. It restores 1,647 stale-to-fresh states. [Audit](../outputs/catalog-final-date-refresh-20261024/independent_audit.json) |
| Final-date tasking source sensitivity | Ninety-six conditions over the final two midnight hours compare full cohorts, shared IDs and shared validity masks. All 16 canonical baseline rows matched; source controls, 48 contrasts and 24 outage interactions passed audit, with 12 sampled numerical replays. These descriptive two-window checks do not establish general source accuracy. [Report](../outputs/final-date-tasking-source-refresh-20261024/report.md) |
| Designed experiments | Both LEO and four-regime campaigns completed 16 screening treatments, 15 CCD treatments, 31 matched-budget BO treatments and 15 validation retrains. Each integrity audit covers 77 checkpoints and 25 held-out policy/seed rows. |
| RSM diagnostics | Twelve additional independent center retrains produced 13 center observations and independently reproduced response surfaces and lack-of-fit diagnostics. |
| Geometry-conditioned loss probes | All 68 quarterly date/regime cells and five checkpoints: 340 baseline episodes, 2,253 single-observation suppressions, and 36 populated range/slew/regime groups. All contrasts and grouped date statistics audited; a separate loss-injection branch reproduced 85 probes and 12 baselines. These are conditional, exploratory 18-target learned-policy effects. [Report and figure](../outputs/geometry-single-loss-quarterly-20261024/report.md) |
| Quarterly controlled loss-rate study | All 81,600 responses across 68 date/regime cells passed complete numerical validation, including 4,080 stratified frozen-policy replays. All 288 condition estimates, 192 paired-effect estimates and 576 temporal intervals were independently reproduced. [Final report](../outputs/dropout-five-policy-quarterly-20261024/dropout_report.md) |
| Additional held-out dates | Twenty post-training dates across four regimes, three policies and five seeds: 1,200 responses with independent source and comparison-statistic checks. |
| Observed laser ranging | Four ILRS targets; 613,841 derived range comparisons. Raw CRD/CPF hashes, range arithmetic, source joins and station-day return-quality contrasts were independently reproduced. Acquired returns do not provide an acquisition-attempt denominator. |
| Numerical-force reference checks | J2 and J2 plus Sun/Moon models each evaluated the same 1,860 ILRS epochs. Both independent audits passed. [Comparison report and figures](../outputs/ilrs-force-comparison-20261024/report.md) |
| Common-frame monthly policy sensitivity | 192 one-hour scenarios, 1,920 learned-policy responses and 19,200 paired dropout responses passed independent source and numerical checks. Both policy feature streams are TEME. [Report and figure](../outputs/awp-sun-moon-teme-policy-monthly-20261024/report.md) |
| DUST imagery | All 160 annotated tracks inventoried; 156 have usable metadata, and four source exclusions were verified. Raw and star-corrected angular replays each passed audit on 2,930 held-out frames. DUST supplies no NORAD identity truth. [Report](../outputs/dust-tle-track-validation-20261024/report.md) |
| Durham optical observations | Publisher-checksummed archive; ten nights, 202,627 positive detections and 161,805 conditional in-field frame opportunities. The catalogue-gap fraction is conditional on positive tracks and is not hardware dropout probability. |
| CASSIOPE attitude | All 1,398 daily source CDFs fully reproduced, all 64 unpublished-day records verified, and 2,013,120 minute masks independently checked. Unknown days remain unknown. [Availability and coverage report](../outputs/attitude-availability-20261024/report.md) |
| Empirical-block weekly tasking | All 208 dates, 832 paired date/regime cells and 1,664 response rows passed the final independent audit, including source-mask traces and date-clustered effects. This is a hypothetical all-catalogue greedy reference using one-spacecraft availability blocks. [Audit](../outputs/measured-empirical-block-weekly-20261024/independent_audit.json) |
| Fitted-Markov weekly tasking and paired process comparison | The matching 208-date, 832-cell, 1,664-response Markov replay passed its final audit. Both processes' 832 zero-outage baseline cells match. All 36 effect vectors/means and 108 temporal intervals passed independent statistical reproduction; each process also passed 24 sampled action replays. [Complete comparison](../outputs/measured-paired-process-comparison-20261024/report.md) |
| Original-framework execution reference | The existing upstream-derived Octave port ran a fixed external-trajectory case at two seeds. Custody tick metrics reconciled and Q-table bytes matched the original source. This is a compatibility reference, without MATLAB bitwise parity or actor-critic equivalence. [Source and run provenance](../outputs/original-framework-reference-20261024/summary.json) |

To inspect the combined native-epoch dataset, use the paths in its manifest with DuckDB's `hive_partitioning=false`. The supplement is retained separately so the original experiments keep their immutable source bindings.

The all-catalogue tasking extensions use a deterministic greedy reference. The trained actor-critic policy retains its fixed 18-target action space. Full-catalogue reference results therefore do not establish full-catalogue learned GoDSAT performance or exact correspondence with the original MATLAB framework.

## Interpretation of current results

The four-regime primary comparison does not establish a custody gain. The 20-date post-training comparison also does not establish a custody gain, and its slew result does not reproduce the primary reduction. Slew quantities remain proxies rather than calibrated electrical or propellant energy. The center-replicated custody response surface shows significant lack of fit (p=0.00834). The objective test does not show significant lack of fit (p=0.0762), which does not prove model adequacy. Saddle or flat fitted surfaces are not demonstrated optima.

Both numerical-force models agree less closely with operational CPF positions than historical SGP4 on the matched ILRS sample. CPF is an operational reference product, not independent orbital truth. Adding force terms is therefore evaluated as sensitivity rather than asserted improvement.

DUST's pooled held-out angular residuals remain large after star-derived correction. Neither candidate identities nor a 0.15-degree descriptive tolerance are calibrated association truth. The matched stars are part of the astrometric solution and are not withheld calibration truth.

The CASSIOPE minute-sampled unavailable-solution fraction is 25.30% on published days. Unpublished-day uncertainty gives deterministic whole-window bounds of 24.19–28.57%. Resampling consecutive 90-day calendar blocks gives a separate conditional interval of 21.67–29.51%, compared with 24.38–26.25% under independent-day resampling. These intervals concern different assumptions and estimands. The definitive product interpolates between sensor solutions and encodes long gaps; it is not a log of every instantaneous missing reading or prospective onboard availability.

The exact distribution of 1,930,638 overlapping within-day hour windows differs from the fitted stationary first-order Markov reference. An entirely unavailable hour occurs in 4.54% of source windows, versus about 0.0000069% under that fitted reference. Those overlapping windows are not independent samples, and the comparison is descriptive. The [hour-window report](../outputs/attitude-hour-window-model-20261024/report.md) quantifies the distribution and the small marginal-rate difference caused by within-day window sampling. The empirical-block and fitted-Markov tasking runs retain that model distinction.

In the monthly common-frame comparison, the injected 20% burst loss reduces mean custody by approximately 0.75–1.83 percentage points across regimes. All four date-clustered intervals for the force-model change in that effect include zero. This applies to the sampled one-hour learned-policy scenes and is not a long-horizon orbit-accuracy or operational-equivalence result.

The completed empirical weekly replay reduces observable-target custody by 0.069, 1.561, 5.465 and 0.283 percentage points for LEO, MEO, GEO and HEO hosts respectively. All-valid-target custody changes are much smaller because their denominator includes unobservable targets. The [complete paired measured-process report](../outputs/measured-paired-process-comparison-20261024/report.md) separates those denominators and includes circular moving-block uncertainty intervals with 1-, 4- and 13-week blocks. Markov-minus-empirical observable custody in MEO is −0.317 percentage points, with a pointwise 13-week-block interval of [−0.552, −0.110]. The corresponding LEO, GEO and HEO intervals include zero. These process contrasts include differences in realized loss counts and later adaptive actions; they do not isolate timing/burst structure at a fixed realized loss frequency. Intervals condition on the retrospective source-profile fit and do not adjust for multiple comparisons.

## Final scope and evidence

All original configured experiment workers and their final audits have completed. The newly supplied PDF has been read; followthrough uses a separate campaign and explicit user-authorized assumptions. The requirement audit records no remaining execution items under the authorized simulation assumptions. Exact published-baseline reproduction and calibrated hardware performance are not established.

The completed followthrough processes and their logs are recorded in the execution plan. Inspect that evidence before starting another execution. The final objective audit preserves the distinction between completed configured simulations and the unverified requested PDF study.

Six supplementary numerical workers completed all registered daily cells from date index 1,461 backward through index 700. Before starting, they reproduced all eight responses for the first registered date exactly. They preserved the original full-design date index, seed, configuration signature and cell format; existing differing cells caused an error. The original forward coordinator assembled the completed result and triggered its final audits. The helper receipt is `parallel_cell_execution.json` in the daily output folder. This parallel execution changed scheduling, not the scientific design.

The completed fitted-Markov weekly run used two supplementary workers for date indices 207 backward through 160, after a separate eight-response exact pilot and reconciliation of the audited source-profile hash, stationary rate, persistence and registered design signature. All 48 helper dates completed, and the original coordinator assembled and audited the full result. Its helper receipt is `parallel_cell_execution.json` in the fitted-Markov output folder.

The quarterly tail used a separate handoff after all 1,200 responses in an already completed cell matched exactly. An immutable checkpoint preserved 74,400 responses from 62 cells; six workers computed the remaining 7,200 responses. The complete original grid was finalized and integrity-validated before replacing the original worker. The final exit observer encountered a disappearing `/proc` working-directory entry after that commit. The executed controller source and original error receipt are retained; the observer is corrected and regression-tested. The [handoff reconciliation](../outputs/study-execution/quarterly-handoff/reconciliation.json) verifies every preserved and supplementary row against the committed CSV. The subsequent full numerical/source-policy and temporal-statistics audits passed independently.

`outputs/study-execution/finish_simulation_audits.py` watched the exact recorded monthly-AWP, quarterly-dropout and daily-catalogue workers, then ran their final audit pipelines. The quarterly pipeline checked every reported temporal interval using an independent cumulative-block-sum calculation. Every pipeline now records successful completion and its audit log; failed predecessors did not advance automatically.

## Review commands

The supplied-design physical-response campaign is reproducible separately from the frozen proxy-model studies. Run each command only after the preceding dependency has completed. Use a fresh output directory if the source/configuration changes.

```bash
.venv/bin/python -m godsat --config configs/archive/governing-design-physical-leo.json campaign --output outputs/governing-design-physical-leo-20261025
.venv/bin/python scripts/validation/audit_physical_campaign.py --input outputs/governing-design-physical-leo-20261025
.venv/bin/python scripts/experiments/replicate_rsm_center.py --campaign outputs/governing-design-physical-leo-20261025 --output outputs/governing-design-physical-leo-center-20261025 --additional-replicates 12
.venv/bin/python scripts/validation/audit_rsm_center_replication.py --output outputs/governing-design-physical-leo-center-20261025
.venv/bin/python scripts/experiments/run_physical_sensitivity.py
.venv/bin/python scripts/validation/audit_physical_sensitivity.py
.venv/bin/python scripts/analysis/analyze_governing_design.py
.venv/bin/python scripts/validation/audit_governing_protocol.py
.venv/bin/python scripts/figures/render_physical_study.py
.venv/bin/python scripts/figures/render_study_results.py
```

Refresh the completion inventory without rerunning experiments:

```bash
.venv/bin/python scripts/validation/audit_study_completion.py
```

The inventory reports recorded audit status, exact design dimensions and stale evidence-index hashes. It does not replace the underlying source/numerical auditors or scientific review of the protocol and conclusions.

The supplemental reports can be regenerated from their audited inputs:

```bash
.venv/bin/python scripts/analysis/analyze_measured_tasking.py \
  --empirical outputs/measured-empirical-block-weekly-20261024 \
  --output outputs/measured-tasking-comparison-20261024
.venv/bin/python scripts/figures/render_ilrs_force_comparison.py \
  --j2 outputs/awp-ilrs-cpf-j2-20261024 \
  --sun-moon outputs/awp-ilrs-cpf-sun-moon-20261024 \
  --output outputs/ilrs-force-comparison-20261024
.venv/bin/python scripts/figures/render_epop_availability.py \
  --output outputs/attitude-availability-20261024
```

For the completed paired comparison, add `--markov outputs/measured-fitted-markov-weekly-20261024` and use `--output outputs/measured-paired-process-comparison-20261024`. The comparison requires identical dates, source profile, host identities, zero-outage responses and target denominators. Reproduce its full uncertainty audit with `scripts/validation/audit_measured_comparison.py --input outputs/measured-paired-process-comparison-20261024 --empirical outputs/measured-empirical-block-weekly-20261024 --markov outputs/measured-fitted-markov-weekly-20261024` using the project Python environment.

Sampled task-assignment reproducibility can be checked separately with
`scripts/validation/replay_catalog_tasking_sample.py --input <completed-output-folder>` using the project Python environment. It rebuilds orbital inputs and reruns both conditions for the first, middle and last sampled dates, checking every returned response field exactly. This is a deterministic replay of the same scheduler, not an independent scheduler implementation or a check of every unsampled action.

Both measured weekly runs passed this check for 24 responses each on 2022-10-15, 2024-10-12 and 2026-10-03, covering all four host regimes and both conditions. Every returned field matched exactly. The [empirical receipt](../outputs/measured-empirical-block-weekly-20261024/sampled_action_replay.json) and [Markov receipt](../outputs/measured-fitted-markov-weekly-20261024/sampled_action_replay.json) record the tested dates and code/input hashes; the other 1,640 response rows per process were not numerically rerun by this check.
