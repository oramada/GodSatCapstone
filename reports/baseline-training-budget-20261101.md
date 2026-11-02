# Development-only actor–critic budget check — 2026-11-01

The supplied paper is being executed using documented implementation choices. This diagnostic retains the existing actor–critic reference; it does not recover a published baseline. Its prospective plan, source snapshot, raw responses and checkpoints are saved in [the diagnostic output](../outputs/baseline-training-budget-20261101/).

Nine complete training runs compare 40, 160 and 640 episodes with three paired training seeds. Each checkpoint was evaluated with three development noise seeds, giving 27 responses; evaluation noise seeds are averaged within training seed before uncertainty calculation. No final test scenario was loaded. The geometry is a single development date, so these intervals do not measure scenario-population uncertainty.

| Episodes | Mean development custody | 95% interval across three training seeds |
| --- | ---: | ---: |
| 40 | 15.20% | [9.74%, 20.65%] |
| 160 | 16.90% | [11.77%, 22.04%] |
| 640 | 23.42% | [10.39%, 36.44%] |

The paired 640-minus-160 change is +6.51 percentage points, with 95% interval [-7.92, +20.94]. The predeclared requirement that this interval lie within ±2 percentage points was not met. This does not certify convergence or justify silently declaring 640 episodes sufficient.

Development custody means were 62.38% for greedy and 44.29% for random scheduling. These are evaluation controls, without a training cost. No actor–critic advantage is established.

![Training-budget diagnostic](../outputs/baseline-training-budget-20261101/training-budget.png)

The earlier 40-episode campaign remains a finite-budget experiment, not evidence of converged performance. This new diagnostic does not revise its results or establish the paper’s claimed gains. Before a revised factorial campaign, isolate actor width from critic width, then explicitly freeze the training protocol and report its adequacy limits. Retain all failed response-surface fits; do not optimize until the desired gains appear.

The [execution decisions](../docs/paper-execution-decisions.md) supply the missing methodological choices without asking the user for unavailable author context. Exact published-baseline reproduction and full paper completion remain unverified.
