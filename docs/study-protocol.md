# Study protocol and interpretation

## Scope of the supplied paper

The paper studies hyperparameter optimization for GoDSAT tasking agents. It does not include satellite/sensor dropout as a research question, and it does not rank outage value by sensor-target geometry. It does not label formal numbered research questions. A useful teaching breakdown of its scope is:

1. Which of seven agent hyperparameters most influence tasking performance?
2. Which settings optimize that performance, and how do factorial/response-surface design and an equal-budget Bayesian search compare?

The protocol is a 16-run resolution-IV fractional-factorial screen over seven factors, followed by a 15-run face-centered response-surface design over the three leading factors. The paper also describes five-seed validation and a Bayesian-optimization comparison with a 31-run budget. It names custody continuity, slew energy, false-track rate, and GPU-hours as responses. The Results section contains a placeholder for numerical tables and plots, although the abstract and conclusion state improvement claims; those claims are not auditable from the supplied results section.

This implementation is a student research seed. It does not establish that the Python actor-critic implementation is the original GoDSAT implementation. Treat outputs as new simulation results and report the implementation and assumptions.

## Experiment stages

The `campaign` command performs a 16-run, resolution-IV fractional-factorial screen over seven factors; a face-centered response-surface design over the three leading factors; an internal Bayesian-search comparison; and five-seed validation. It records four tasking responses, run configuration, random seeds, device, and wall time. The default center replicate count is one; passing `--center-replicates 3` adds repeated center observations for a more useful estimate of experimental noise.

Training dates, a later validation date, and a held-out test date are specified in `configs/paper-exact-cpu.json`. These are short sampled episodes drawn from the four-year archive, not four years of continuous agent training. Factor effects apply to this simulator, its selected scenarios, and its reward/response definitions.

## Separate simulated dropout extension

The `dropout-study` command is an extension beyond the supplied paper. It tests simulated independent and burst sensor outages across configured rates, orbit regimes, and dates, then reports aggregate response changes relative to zero dropout. It neither uses measured outage telemetry nor identifies the most valuable or harmful sensor-target geometries.

To answer a geometry-specific dropout question, a follow-on study needs to define what makes a dropout valuable, preserve paired outage/no-outage trials, and report effects within geometry groups such as range, line-of-sight margin, slew angle, field-of-regard margin, and target contention. Those grouped estimates are not currently implemented. The PDF's future-work note about adding LEO multi-target geometries is separate from its hyperparameter study and does not specify an outage analysis.

## Reproducibility and limits

- Data checksums and the SATCAT retrieval snapshot are recorded locally.
- Training and design seeds are saved with generated runs.
- `audit_campaign.py` checks that campaign records match the requested design and validation protocol.
- The current-payload cohort applies today's catalog status to old orbital records. It does not reconstruct each object's historical operational status.
- TLE records are element sets. SGP4 propagates them into states for a scenario; gaps and element updates mean the archive is not a continuous measured trajectory.
- Sensor locations, field of regard, detection probability, observation noise, and tasking outcomes are modeled. These results are not evidence of real sensor performance without independent ground observations.
- AWP comparisons are alternate force-model runs initialized from archived SGP4 states. Agreement or separation is model sensitivity, not ground-truth error.

Students should preserve their exact config, data snapshot manifests, code revision, and output audit with any report.
