import Mathlib.Data.Matrix.Mul
import Mathlib.Algebra.BigOperators.Fin
import Mathlib.Tactic.FinCases
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Linarith

/-! Exact mathematics of the supplied paper's 2^(7-3) design.
The seven columns are generated from four independent binary coordinates.
These proofs certify this finite rational/integer specification; a separate
CSV/source binding check is needed for each executed experiment.
-/
namespace GoDSAT.Design
open scoped BigOperators

set_option maxRecDepth 100000
set_option maxHeartbeats 16000000

abbrev Row := Fin 16
abbrev Factor := Fin 7

def sign (r : Row) (bit : Nat) : ℤ :=
  if r.val / 2 ^ bit % 2 = 0 then -1 else 1

def code (r : Row) (j : Factor) : ℤ :=
  match j.val with
  | 0 => sign r 0
  | 1 => sign r 1
  | 2 => sign r 2
  | 3 => sign r 3
  | 4 => sign r 0 * sign r 1 * sign r 2
  | 5 => sign r 0 * sign r 1 * sign r 3
  | _ => sign r 0 * sign r 2 * sign r 3

theorem generators (r : Row) :
    code r 4 = code r 0 * code r 1 * code r 2 ∧
    code r 5 = code r 0 * code r 1 * code r 3 ∧
    code r 6 = code r 0 * code r 2 * code r 3 := by
  exact ⟨rfl, rfl, rfl⟩

theorem balanced : ∀ j : Factor, ∑ r : Row, code r j = 0 := by decide

theorem orthogonal : ∀ i j : Factor,
    ∑ r : Row, code r i * code r j = if i = j then 16 else 0 := by decide

theorem main_clear_of_two_factor : ∀ i j k : Factor, j ≠ k →
    ∑ r : Row, code r i * code r j * code r k = 0 := by decide

def aliasColumn (r : Row) (word : Fin 128) : ℤ :=
  ∏ j : Factor, if word.val.testBit j.val then code r j else 1

-- Bits A..G have weights 1,2,4,8,16,32,64.
-- I, ABCE, ABDF, CDEF, ACDG, BDEG, BCFG, AEFG.
def definingMasks : Finset (Fin 128) := {0, 23, 43, 60, 77, 90, 102, 113}

theorem corrected_defining_group : ∀ word : Fin 128,
    (∀ r : Row, aliasColumn r word = 1) ↔ word ∈ definingMasks := by decide

-- ADEFG, printed in equation (4), already fails on the all-low row.
theorem printed_relation_counterexample : aliasColumn 0 121 = -1 := by decide

theorem printed_relation_is_not_identity :
    ¬ (∀ r : Row, aliasColumn r 121 = 1) := by
  intro h
  have impossible := h 0
  rw [printed_relation_counterexample] at impossible
  norm_num at impossible

def linearResponse (intercept : ℚ) (beta : Factor → ℚ) (r : Row) : ℚ :=
  intercept + ∑ j : Factor, beta j * (code r j : ℚ)

def mainEffect (response : Row → ℚ) (j : Factor) : ℚ :=
  (1 / 8 : ℚ) * ∑ r : Row, (code r j : ℚ) * response r

theorem main_effect_recovers_coefficient (intercept : ℚ) (beta : Factor → ℚ)
    (j : Factor) : mainEffect (linearResponse intercept beta) j = 2 * beta j := by
  fin_cases j <;>
    norm_num [mainEffect, linearResponse, Fin.sum_univ_succ, code, sign] <;> ring

theorem main_effect_with_residual (intercept : ℚ) (beta : Factor → ℚ)
    (residual : Row → ℚ) (j : Factor) :
    mainEffect (fun r => linearResponse intercept beta r + residual r) j =
      2 * beta j + mainEffect residual j := by
  calc
    _ = mainEffect (linearResponse intercept beta) j + mainEffect residual j := by
      simp only [mainEffect, mul_add, Finset.sum_add_distrib]
    _ = _ := by rw [main_effect_recovers_coefficient]

theorem screening_and_ccd_count : (16 : Nat) + 15 = 31 := by decide
theorem not_tenfold_run_reduction : ¬ ((2 ^ 7 : Nat) ≥ 10 * (16 + 15)) := by decide
theorem equal_trials_can_have_unequal_cost :
    (∑ _ : Fin 31, (1 : ℚ)) ≠ (∑ _ : Fin 31, (2 : ℚ)) := by norm_num

def decode (low high coded : ℚ) : ℚ := (low + high) / 2 + coded * (high - low) / 2
def encode (low high actual : ℚ) : ℚ := (actual - (low + high) / 2) / ((high - low) / 2)

theorem decode_low (low high : ℚ) : decode low high (-1) = low := by
  unfold decode
  ring

theorem decode_high (low high : ℚ) : decode low high 1 = high := by
  unfold decode
  ring

theorem encode_decode (low high coded : ℚ) (different : high ≠ low) :
    encode low high (decode low high coded) = coded := by
  have nonzero : high - low ≠ 0 := sub_ne_zero.mpr different
  unfold encode decode
  field_simp [nonzero] <;> ring

theorem decoded_region_bounds (low high coded : ℚ)
    (ordered : low ≤ high) (lower : -1 ≤ coded) (upper : coded ≤ 1) :
    low ≤ decode low high coded ∧ decode low high coded ≤ high := by
  unfold decode
  have lo := mul_nonneg (sub_nonneg.mpr ordered) (show 0 ≤ coded + 1 by linarith)
  have hi := mul_nonneg (sub_nonneg.mpr ordered) (show 0 ≤ 1 - coded by linarith)
  constructor <;> nlinarith

end GoDSAT.Design
