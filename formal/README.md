# GoDSAT formal verification

Lean 4.35.0 checked **62 theorems** on 2026-10-27. The [verification receipt](../reports/evidence/lean/lean-verification.json) records source hashes, dependency pins, theorem axioms, actual build logs and bindings to executed design CSVs. Two intentionally false draft claims were rejected as negative controls outside the accepted proof library.

The checked library covers factorial generators and aliases, contrast algebra and coding, CCD identifiability, pure-error degrees of freedom, least-squares minimization, real quadratic differentiation/optimality, conditional energy and custody invariants, and explicitly conditional transition refinement. It also checks all 121 recorded original Q-table neighbor outputs and the inequality of recorded original/port headless outputs. The helper experiment exercised 1,628 cases under Octave; it does not establish whole-controller or native MATLAB equivalence.

`SensorAssumptions.lean` proves implications from explicit hypotheses. Physical calibration, noise independence, adequate training, response-surface adequacy and empirical gains still require evidence. `conditional_trace_refinement` requires an actual one-step implementation bridge; that bridge has not been proved. No theorem certifies the draft’s claimed custody/energy improvements.

## Rebuild

Lean and Mathlib are pinned by `lean-toolchain` and `lake-manifest.json`. With the pinned toolchain installed, from this directory:

```bash
MATHLIB_NO_CACHE_ON_UPDATE=1 lake update
lake exe cache get Mathlib.Data.Matrix.Mul Mathlib.Algebra.BigOperators.Fin Mathlib.Data.Fin.VecNotation Mathlib.Data.Real.Basic Mathlib.Tactic.FinCases Mathlib.Tactic.NormNum Mathlib.Tactic.Ring Mathlib.Tactic.FieldSimp Mathlib.Tactic.Linarith Mathlib.Tactic.Positivity Mathlib.Analysis.Calculus.Deriv.Pow Mathlib.Analysis.Calculus.Deriv.Add Mathlib.Analysis.Calculus.Deriv.Mul
lake build
```

The cache command is an optional build accelerator. The update environment variable avoids automatically downloading the entire Mathlib cache. Allow sufficient scratch space for Lean and dependencies.

From the repository root, the full evidence check is:

```bash
.venv/bin/python scripts/formal/verify_lean_study.py
```

This also requires the original source checkout and recorded controller probes at the paths in the script. Its external JSON/CSV/hash comparisons are Python checks against a kernel-checked finite specification, not proofs of the Python or MATLAB runtimes. The local run used `--elan-home /run/user/1000/godsat-elan-20261027`; toolchain and `.lake` caches were placed on temporary RAM filesystems because SSD space was limited. Those caches are ephemeral; tracked sources, pins and saved receipts remain reproducible inputs.

The verifier rejects `sorry`, admitted proofs, custom axioms and unchecked native-decision axioms. Standard foundational axioms are recorded per theorem.

The Q-table and helper-derived certificates originate from Ben Johnson’s BSD-3-Clause GoDSAT framework at commit `672dfec2a629bd8ceb58a36e54e5ec8dd93d0776`. See [the retained upstream license](UPSTREAM-LICENSE). Source/control-flow and compatibility transformations are recorded in the controller probe receipt.
