# Study protocol and interpretation

## Questions represented by this starter

The supplied paper motivates systematic hyperparameter optimization but does not label two formal research questions. This repository treats the intended questions as:

1. Which of seven agent hyperparameters most influence tasking performance?
2. Which settings optimize that performance, and how do factorial/response-surface design and an equal-budget Bayesian search compare?

The implementation is a student research seed. It does not establish that the Python actor-critic implementation is the original GoDSAT implementation, and the paper itself leaves numerical results as placeholders. Treat results generated here as new simulation results and report the implementation and assumptions.

## Experiment stages

The `campaign` command performs a 16-run, resolution-IV fractional-factorial screen over seven factors; a face-centered response-surface design over the three leading factors; an internal Bayesian-search comparison; and five-seed validation. It records four tasking responses, run configuration, random seeds, device, and wall time. The default center replicate count is one; passing `--center-replicates 3` adds repeated center observations for a more useful estimate of experimental noise.

Training dates, a later validation date, and a held-out test date are specified in `configs/paper-exact-cpu.json`. These are short sampled episodes drawn from the four-year archive, not four years of continuous agent training. Factor effects apply to this simulator, its selected scenarios, and its reward/response definitions.

## Dropout question

The separate `dropout-study` command tests simulated independent and burst dropout across configured rates and orbit regimes. It reports changes in custody continuity and other simulator responses relative to zero dropout. This measures the simulated effect of missing sensor observations under the selected policy and assumptions. It is not a field estimate of real sensor dropout effectiveness unless the dropout and sensor models are calibrated against representative observations.

## Reproducibility and limits

- Data checksums and the SATCAT retrieval snapshot are recorded locally.
- Training and design seeds are saved with generated runs.
- `audit_campaign.py` checks that campaign records match the requested design and validation protocol.
- The current-payload cohort applies today's catalog status to old orbital records. It does not reconstruct each object's historical operational status.
- TLE records are element sets. SGP4 propagates them into states for a scenario; gaps and element updates mean the archive is not a continuous measured trajectory.
- Sensor locations, field of regard, detection probability, observation noise, and tasking outcomes are modeled. These results are not evidence of real sensor performance without independent ground observations.
- AWP comparisons are alternate force-model runs initialized from archived SGP4 states. Agreement or separation is model sensitivity, not ground-truth error.

Students should preserve their exact config, data snapshot manifests, code revision, and output audit with any report.
