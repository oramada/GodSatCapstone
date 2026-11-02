# Faithful reproduction status — 2026-10-27

The user-requested verification and full-paper execution goal is **incomplete**. Its remaining faithful optimization work is blocked on identifying the intended actor–critic implementation or explicitly defining a new extension. Earlier campaigns tested a documented simulation adaptation. They do not establish original-controller equivalence, published-baseline reproduction, or the draft's positive custody/energy claims.

## Verified mathematics and executed checks

The [Lean receipt](../outputs/faithful-reproduction-20261027/lean-verification.json) records a successful Lean 4.35.0 build of 62 theorems, per-theorem axiom audits, source hashes and exact design-coordinate comparisons for three prior campaigns. There are no admitted proofs, custom axioms or unchecked native-decision axioms in the accepted library. The exact scope and rebuild commands are in [formal/README.md](../formal/README.md).

The generator-consistent defining group is `I, ABCE, ABDF, ACDG, AEFG, BCFG, BDEG, CDEF`. The draft's printed relation is inconsistent with its generators. The 15 distinct CCD points have full quadratic column rank but zero pure-error degrees of freedom. Negative controls confirm Lean rejects the incorrect relation and the assertion of available pure error for that unreplicated design. The run-count ratio 128/31 is approximately 4.13; it does not establish tenfold compute savings.

Conditional energy/track invariants and a conditional trace-refinement theorem are proved. Their physical hypotheses and implementation bridge remain separate obligations. Lean does not prove empirical improvement, calibrated spacecraft energy, independent errors or adequate regression fit.

## Controller evidence

The [source audit](../outputs/faithful-reproduction-20261027/upstream-source-audit.json) examined 11 available upstream branch tips, 55 reachable commits and 358 historical MATLAB/Python/notebook code blobs. No actor–critic implementation matching the draft's factors was found. The cited original source implements Q-table/gradient tasking. This audit cannot exclude private or unpublished code.

The [controller experiment](../outputs/faithful-reproduction-20261027/controller-probes/original-controller-probe.json) compared the unchanged original neighbor helper with an independent implementation on 1,628 cases. All matched. The Lean finite certificate checks all 121 original Q-table cell outputs against the recorded observations. These results cover the helper, not the whole controller.

A same-input pending-slew experiment found a concrete headless mismatch: the original source returns at an empty graphics handle before advancing FOV, while the existing compatibility port advances it. Their resulting boresights differ by approximately two degrees. Original-source execution here used Octave with recorded property-annotation removal and compatibility geometry routines; it is not native MATLAB parity. The kernel proves the recorded output values differ, rather than proving the interpreter's semantics.

The original harness's custody flag combines detection, Q-mode and at least three consecutive tracked frames. Its `F` flag is not false-track rate. The prior adaptation's custody persistence and energy model therefore cannot silently serve as original-baseline measurements.

### Additional original-controller exit tests

The [exit-guard receipt](../outputs/faithful-reproduction-20261027/exit-guard-probes/receipt.json) records 30 executed checks: five public `updateFOV` early-exit conditions, three initial own-claim counts, and two implementations. Conditions cover invalid target index, missing target position, lost LOS, landed target and confirmed ownership handoff. The source-preserving class and the existing port agree on all tested outputs. Both reset Q-mode/index/lost counter and command a nadir slew, while preserving the claim map. In all 20 fixtures with initially nonzero own claims, those claims remain after exit.

The fixtures call `updateFOV` directly with explicit synthetic states, retaining original control flow. They establish neither scenario reachability nor a custody deficit; they also do not erase the separate `updatePosition` headless mismatch. The Lean refresh-claim invariants describe the refresh operation, which is not executed by these early exits. No global claim-release-on-exit invariant has been established. The runner is [probe_original_exit_guards.py](../scripts/probe_original_exit_guards.py); its receipt pins the script, driver, original class, property-type-erased class, port and observations.

## Remaining execution obligations

| Obligation | Current evidence | Required next result |
| --- | --- | --- |
| Intended controller identity | Cited source is Q-table/gradient; draft specifies actor–critic factors | Identify a separate published implementation, or explicitly define a new neural extension |
| Whole-controller equivalence | Helper checks pass; headless port counterexample exists | Native/reference tick traces and a defined implementation relation for the selected runtime |
| Published baseline reproduction | No matching actor–critic source/checkpoint/recipe identified | Pin authoritative baseline artifacts and reproduce its scenario and metrics |
| Physical assumptions | Conditional Lean results and prior assumed-model sensitivity | Validate/calibrate the selected energy and observation model, or report a clearly defined simulation-only extension |
| Custody and energy claims | Earlier adaptation did not establish gains | Paired held-out baseline comparisons with independent retraining and declared uncertainty/multiplicity |
| Response-surface adequacy | Some earlier adaptation fits failed | Replicated development design, adequacy assessment and any prospectively bounded refinement |
| Fair search comparison | Equal treatment counts are defined | Log actual training/search costs and account for all added diagnostics/refinement |

The [prospective protocol](../docs/faithful-reproduction-protocol.md) specifies the corrected screen, CCD replication, adequacy handling, baseline matching and independent validation. Failed fits and negative outcomes must remain in the record. A new run of an assumed controller would not resolve the source mismatch.

The pending research-definition question is whether this paper describes a new actor–critic extension using the original Q-table controller as a comparator, or a separate existing actor–critic implementation. Dependent neural experiments have not been launched without that definition. No positive result or full-study completion is claimed.

A final [related-project search](../outputs/faithful-reproduction-20261027/related-baseline-search.json) records the exact local file inventory, hashes, pattern and exclusions, together with external queries. No matching actor–critic code was identified in the two related local checkouts or through the targeted external search. This does not prove that private/unpublished code is absent. The author's [institutional publication list](https://ep.jhu.edu/faculty/amir-saeed/) confirms the cited 2026 GoDSAT paper and related 2024 papers, but supplies no matching baseline artifact. Direct IEEE/GitHub page retrieval limits are recorded rather than treated as evidence of absence.

The same controller-identity blocker has persisted across three consecutive goal turns. Source/history searches, mathematical verification and the independently available controller boundary tests are complete for their stated scopes. Further assumed neural campaigns would not establish the requested published-baseline result. The next required input is either an authoritative implementation/checkpoint/configuration path or an explicit choice to formulate a new actor–critic extension and revise the baseline claim accordingly. Such an extension would remain a new study, not reproduction of an unidentified published neural baseline.
