# Faithful GoDSAT reproduction and Lean verification

This is the stricter goal requested on 2026-10-27. The earlier assumed-model
campaigns remain adaptations; their completed audits do not establish original
controller equivalence or a published actor–critic baseline.

The governing PDF is pinned by SHA-256
`e705ce0a7bc80496f37ab8da5a8ad9ba2cefe5619e7f530b15ecc902abb64e95`.
The available cited framework is pinned at upstream commit
`672dfec2a629bd8ceb58a36e54e5ec8dd93d0776`. A read-only mirror also captures all
11 currently available branch tips and 55 reachable commits. The code-blob
audit found no actor–critic implementation matching the seven-factor design.
Bayesian trajectory predictors are not actor–critic tasking agents.

## Evidence gates before a faithful optimization run

1. Identify the authoritative original controller, baseline configuration,
   trained policy/checkpoint, training recipe and scenario data that the design
   paper means by its published baseline. Pin source/weight/input hashes and
   identify their publication or author-provided provenance.
2. Resolve the mismatch between the cited Q-table/gradient controller and the
   paper's actor–critic parameters. Do not silently assign learning rate,
   discount, actor width, critic depth, entropy or target-network update rate to
   code that never trains those components. A neural extension must be named as
   an extension, not as an equivalent original controller.
3. Reproduce the original run on its intended runtime or obtain authoritative
   native reference traces. Check orbital states, target states, pointing,
   ownership, claim-map updates, Q-mode transitions and custody flags at every
   tick. Compare any port on exactly those inputs before using it as baseline.
   The current Octave compatibility port has a documented headless semantic
   difference: it advances FOV state where the original returns at an empty
   graphics handle. That difference has now been exercised experimentally.
   Additional direct-method checks agree on five early-exit conditions in
   both implementations, but show that exits retain existing claim-map
   entries. Do not infer claim-release-on-exit from the separate claim-refresh
   lemmas. Scenario reachability and any performance consequence remain to be
   tested; the component fixtures alone do not establish them.
4. Freeze common metric definitions. The available original harness defines
   custody as `A && Q && F` with `F` meaning at least three consecutive tracked
   frames; that `F` is not the design paper's false-track rate. The earlier
   orbital adaptation used a different custody-persistence definition. These
   quantities cannot be pooled. Freeze an actual common slew-energy definition
   and unit before testing a 9% energy claim; assumed host electrical power is
   not pointing energy. The original source supplies no calibrated energy or
   false-association measurement model.
5. Keep all comparator conditions identical: constellation, targets, geometry,
   observation process, time step, starting state, custody denominator, sensor
   constraints and evaluation seeds. The cited source uses 16 satellites, 20
   ballistic targets, 2-second ticks, GRS80 and a 90×180 claim map. A six-host,
   18-orbital-target experiment is a separate scenario, not a reproduction of
   that source baseline. The design PDF does not supply its exact scenario.

The user has been asked for the separate actor–critic baseline/source artifacts.
No message has been sent to the authors. Until these gates are resolved, another
assumed-controller 16/15/31 run cannot close the reproduction requirement.

## Correct experimental execution after the source gates

Freeze the protocol and test scenes before looking at their outcomes. Record
source/configuration/checkpoint hashes, seeds, hardware, software, step counts,
wall/process time, accelerator-active time and the provenance of every energy
quantity. Establish training-budget adequacy using development data before the
factorial experiment; forty episodes must not be called converged without
evidence. The actual published baseline recipe takes precedence when available.

Run the randomized 16-treatment resolution-IV screen at the paper's exact seven
factor ranges. Follow the stated generators; the printed defining relation is
mathematically inconsistent with them. Display all 15 independent contrast
chains. Keep two-factor aliases confounded. The sole minimum-order-three chain
provides only one high-order-only noise degree of freedom; do not call the
unreplicated screen a pure-error experiment. Select factors from the observed
screening response, rather than forcing the placeholder eta/gamma/width result.

Run the exact 15-point face-centered CCD and 31-treatment BO reference under a
common training/selection budget. Retain both the matched-treatment comparison
and a prospectively cost-capped comparison if configurations have different
training costs. Log the accounting boundary and search orchestration overhead.
Do not label equal trial counts equal GPU-hours or wall time automatically.

The single center in the exact 15-run CCD gives zero pure-error df. Budget
independent diagnostic replication separately. Replicate the complete CCD
across independent seeds to check whether center-only variance represents the
whole region, and assess heteroscedasticity and run-order effects. Preserve the
original fixed-budget result alongside these diagnostics. A fitted response
surface that fails adequacy checks cannot license an accepted optimum.

If the quadratic is inadequate, use development-only sequential design: shrink
or relocate the experimental region, add replicated design points, and fit/check
the revised local model. Prespecify the stopping/acceptance rule. Keep every
failed fit and the additional run count. Compare BO under the actual enlarged
search budget as a separate comparison. Do not keep changing the region until
the paper's desired gain appears, and do not use final test outcomes for this
selection. A remaining inadequate surface is a legitimate negative finding.

Retrain each final selected configuration and the true baseline using at least
the paper's five independent seeds. Evaluate paired policies on untouched,
common scenario/noise seeds with identical target-time denominators. Report
paired absolute and relative effects and intervals; account for training-seed
and scenario dependence. Test custody gain and energy reduction as two declared
primary claims with an explicit multiplicity rule. The claimed 11–14% custody
range and 9% energy reduction must be assessed against estimates and intervals,
not used as acceptance targets. Relative effects are undefined if the baseline
denominator is zero. Zero observed false tracks are not proof of zero risk.

Release the full designs, raw responses, failed fits, diagnostics, coefficients,
validation seeds, source/configuration hashes and model artifacts locally.

## What Lean establishes

The project in [`formal`](../formal/README.md) checks exact design/alias algebra,
coding, CCD identifiability, pure-error degrees of freedom, OLS and quadratic
conditions, actuator-energy bounds under stated hypotheses, and track/claim
invariants. It also checks finite original-helper observations and a concrete
headless-output counterexample against recorded source/port traces.

The build rejects admitted proofs, custom axioms and unchecked native decision
axioms. Standard Lean/Mathlib foundational axioms are listed per theorem. The
actual experiment design CSVs are compared with a Lean-exported specification.

Lean does not turn calibration, independent noise, adequate training, native
MATLAB parity or observed performance gains into facts. The conditional trace
refinement theorem is not instantiated as original-controller equivalence: the
real one-step implementation bridge is still required. Numerical/statistical
evidence and the source-provenance gates remain separate obligations.
