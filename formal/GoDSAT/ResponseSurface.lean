import GoDSAT.CCDCertificate
import Mathlib.Algebra.BigOperators.Fin
import Mathlib.Data.Real.Basic
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.FieldSimp

namespace GoDSAT.ResponseSurface
open scoped BigOperators Matrix

def ccdMatrix : Matrix (Fin 15) (Fin 10) ℚ := fun r j => CCD.feature r j
def leftCertificate : Matrix (Fin 10) (Fin 15) ℚ := fun i r => CCD.scaledLeftInverse i r

theorem ccd_left_inverse : leftCertificate * ccdMatrix = (360 : ℚ) • (1 : Matrix (Fin 10) (Fin 10) ℚ) := by
  ext i j
  have h := CCD.left_inverse_certificate i j
  have hc : (∑ r : Fin 15, (CCD.scaledLeftInverse i r : ℚ) * (CCD.feature r j : ℚ)) =
      if i = j then 360 else 0 := by exact_mod_cast h
  simpa [Matrix.mul_apply, leftCertificate, ccdMatrix, Matrix.one_apply, smul_eq_mul] using hc

theorem ccd_columns_identifiable (v : Fin 10 → ℚ) (hv : ccdMatrix *ᵥ v = 0) : v = 0 := by
  have h : (360 : ℚ) • v = 0 := by
    calc
      _ = (leftCertificate * ccdMatrix) *ᵥ v := by
        rw [ccd_left_inverse, Matrix.smul_mulVec, Matrix.one_mulVec]
      _ = leftCertificate *ᵥ (ccdMatrix *ᵥ v) := by rw [Matrix.mulVec_mulVec]
      _ = 0 := by rw [hv]; simp
  funext i
  have hi := congrFun h i
  simpa using hi

def pureErrorAvailable (observations distinctPoints : Nat) : Prop := distinctPoints < observations

theorem single_center_ccd_no_pure_error : ¬ pureErrorAvailable 15 15 := by
  change ¬ (15 : Nat) < 15
  decide
theorem original_ccd_pure_error_df : (15 : Nat) - 15 = 0 := by decide
theorem augmented_ccd_degrees_of_freedom : ((27 : Nat) - 15, (15 : Nat) - 10) = (12,5) := by decide

abbrev Vec := Fin 3 → ℝ
abbrev Curvature := Fin 3 → Fin 3 → ℝ

def homogeneous (B : Curvature) (v : Vec) : ℝ := ∑ i, ∑ j, B i j * v i * v j
def quadratic (c : ℝ) (b : Vec) (B : Curvature) (x : Vec) : ℝ :=
  c + (∑ i, b i * x i) + homogeneous B x

def stationary (b : Vec) (B : Curvature) (x : Vec) : Prop :=
  ∀ i, b i + 2 * ∑ j, B i j * x j = 0

def polynomialForm (c : ℝ) (b pure interaction : Vec) (x : Vec) : ℝ :=
  c + (∑ i, b i * x i) + (∑ i, pure i * x i ^ 2) +
    interaction 0 * x 0 * x 1 + interaction 1 * x 0 * x 2 + interaction 2 * x 1 * x 2

noncomputable def curvatureOf (pure interaction : Vec) : Curvature :=
  fun i j => if i = j then pure i else
    if (i = 0 ∧ j = 1) ∨ (i = 1 ∧ j = 0) then interaction 0 / 2 else
    if (i = 0 ∧ j = 2) ∨ (i = 2 ∧ j = 0) then interaction 1 / 2 else interaction 2 / 2

theorem off_diagonal_halves (c : ℝ) (b pure interaction x : Vec) :
    polynomialForm c b pure interaction x = quadratic c b (curvatureOf pure interaction) x := by
  simp [polynomialForm, quadratic, homogeneous, curvatureOf, Fin.sum_univ_succ]
  ring

theorem quadratic_increment (c : ℝ) (b : Vec) (B : Curvature) (x v : Vec)
    (symmetric : ∀ i j, B i j = B j i) :
    quadratic c b B (fun i => x i + v i) - quadratic c b B x =
      (∑ i, (b i + 2 * ∑ j, B i j * x j) * v i) + homogeneous B v := by
  simp [quadratic, homogeneous, Fin.sum_univ_succ]
  rw [symmetric 1 0, symmetric 2 0, symmetric 2 1]
  ring

theorem stationary_increment (c : ℝ) (b : Vec) (B : Curvature) (x v : Vec)
    (symmetric : ∀ i j, B i j = B j i) (hs : stationary b B x) :
    quadratic c b B (fun i => x i + v i) - quadratic c b B x = homogeneous B v := by
  rw [quadratic_increment c b B x v symmetric]
  simp [stationary] at hs
  simp [hs]

theorem negative_semidefinite_stationary_is_maximum (c : ℝ) (b : Vec) (B : Curvature) (x : Vec)
    (symmetric : ∀ i j, B i j = B j i) (hs : stationary b B x)
    (hB : ∀ v, homogeneous B v ≤ 0) : ∀ y, quadratic c b B y ≤ quadratic c b B x := by
  intro y
  have h := stationary_increment c b B x (fun i => y i - x i) symmetric hs
  have hv := hB (fun i => y i - x i)
  have same : (fun i => x i + (y i - x i)) = y := by funext i; ring
  rw [same] at h
  linarith

theorem homogeneous_scales (B : Curvature) (v : Vec) (t : ℝ) :
    homogeneous B (fun i => t * v i) = t ^ 2 * homogeneous B v := by
  simp [homogeneous, Fin.sum_univ_succ]
  ring

theorem indefinite_stationary_has_both_directions (c : ℝ) (b : Vec) (B : Curvature) (x v w : Vec)
    (symmetric : ∀ i j, B i j = B j i) (hs : stationary b B x)
    (hv : homogeneous B v < 0) (hw : 0 < homogeneous B w) (t : ℝ) (ht : 0 < t) :
    quadratic c b B (fun i => x i + t * v i) < quadratic c b B x ∧
    quadratic c b B x < quadratic c b B (fun i => x i + t * w i) := by
  have h1 := stationary_increment c b B x (fun i => t * v i) symmetric hs
  have h2 := stationary_increment c b B x (fun i => t * w i) symmetric hs
  rw [homogeneous_scales] at h1 h2
  have positive : 0 < t ^ 2 := sq_pos_of_pos ht
  constructor
  · have := mul_neg_of_pos_of_neg positive hv
    linarith
  · have := mul_pos positive hw
    linarith

def squaredNorm (v : Vec) : ℝ := ∑ i, v i ^ 2

theorem ridge_certificate (c : ℝ) (b : Vec) (B : Curvature) (x : Vec) (lambda : ℝ)
    (symmetric : ∀ i j, B i j = B j i)
    (hstation : ∀ i, b i + 2 * ∑ j, B i j * x j = 2 * lambda * x i)
    (hlambda : 0 ≤ lambda)
    (dualBound : ∀ v, homogeneous B v ≤ lambda * squaredNorm v) :
    ∀ y, squaredNorm y ≤ squaredNorm x → quadratic c b B y ≤ quadratic c b B x := by
  intro y hnorm
  have change := quadratic_increment c b B x (fun i => y i - x i) symmetric
  have same : (fun i => x i + (y i - x i)) = y := by funext i; ring
  rw [same] at change
  simp_rw [hstation] at change
  have bound := dualBound (fun i => y i - x i)
  have radial : lambda * (squaredNorm y - squaredNorm x) ≤ 0 :=
    mul_nonpos_of_nonneg_of_nonpos hlambda (sub_nonpos.mpr hnorm)
  have identity : (∑ i, (2 * lambda * x i) * (y i - x i)) +
      lambda * squaredNorm (fun i => y i - x i) =
      lambda * (squaredNorm y - squaredNorm x) := by
    simp [squaredNorm, Fin.sum_univ_succ]
    ring
  linarith

end GoDSAT.ResponseSurface
