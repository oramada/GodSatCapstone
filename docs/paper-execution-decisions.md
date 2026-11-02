# Executing the supplied paper with no additional author context

> **Status update.** The training-budget diagnostic described below has completed: nine training runs and 27 development evaluations, with no established convergence. See the [results](../reports/README.md). The subsequently requested [Iridium NEXT/ground scope](iridium-next-ground-scope.md) supersedes the older mixed-catalogue setup. Ground-system roles remain unresolved, and a new combined-study campaign has not run.

On 2026-11-01 the user clarified that the assignment was simply to execute the
supplied paper, with no additional context. Missing methodology is therefore an
implementation decision to document, rather than a question the user must answer.
The earlier authorization to use documented simulation assumptions still applies.

## Working interpretation

Retain the paper's scientific question: factorial screening and response-surface
refinement of seven actor–critic/tasking parameters, with matched search budgets
and independent evaluation. A Monte Carlo observation-loss study is a useful
extension, but does not replace the assigned optimization study.

The repository's actor–critic implementation is the documented experimental
reference. Its fixed starting settings are an implementation baseline, not a
recovered published checkpoint. The available cited GoDSAT controller remains a
Q-table/gradient implementation; comparison with it requires a common scenario,
metric and runtime definition. Do not claim exact published reproduction from a
newly specified baseline, and do not silently pool their different custody rules.

Retain the existing actuator, clutter and historical-geometry assumptions with
their limits. The draft's claimed gains are hypotheses. Preserve all earlier
results, failed fits, design corrections and source/port discrepancies.

## First execution step: training-budget adequacy

The earlier 40-episode campaign did not establish convergence. Before launching
a revised optimization campaign, run the existing baseline configuration for
40, 160 and 640 episodes with three independent training seeds. Evaluate each
on three development noise seeds. Keep final test scenarios out of this step.
Randomize run order; save complete histories, checkpoints, hashes and runtime.

The prospective diagnostic definition is written before training in
`outputs/baseline-training-budget-20261101/prospective-plan.json`. The runner is
`scripts/experiments/check_baseline_training_budget.py`. A predeclared two-percentage-point
stability margin concerns only the final two budgets on development custody;
meeting it would not prove convergence or generalization. Do not extend the
budget merely until a favorable result appears.

Before a new factorial campaign, audit whether each coded factor changes only
its intended implementation choice. In particular, the current `actor_width`
also sets critic hidden width. The baseline uses width 128 for both, but this
coupling affects interpretation of prior width contrasts. A revised campaign
must either isolate actor width with fixed critic width or name the coupled
factor explicitly. Any source change requires a new versioned campaign.

## Required subsequent results

Freeze the justified training protocol and architecture, run the corrected
screen, select factors from measured effects, replicate the response-surface
design to support adequacy checks, and compare with BO under disclosed costs.
Use separate final evaluation scenes for any new recommendations; earlier test
results are already known and must not guide model selection while being called
untouched validation. Report custody and energy effects with uncertainty even
when the outcome is negative. Do not accept an optimum from an inadequate fit.

The Lean library continues to establish its stated mathematical results. It
does not certify a newly changed training implementation, empirical assumptions
or observed performance without the corresponding evidence.
