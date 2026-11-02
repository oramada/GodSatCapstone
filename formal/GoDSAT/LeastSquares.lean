import Mathlib.Data.Real.Basic
import Mathlib.Data.Matrix.Mul
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith

/-! Deterministic OLS geometry. No stochastic noise law is assumed or proved.
Normal equations are an explicit premise; floating solver output requires its
own residual/certificate check before these results apply exactly.
-/
namespace GoDSAT.LeastSquares
open scoped BigOperators

variable {Row Column : Type*} [Fintype Row] [Fintype Column]

def predict (X : Row → Column → ℝ) (beta : Column → ℝ) (row : Row) : ℝ :=
  ∑ j, X row j * beta j

def residual (X : Row → Column → ℝ) (y : Row → ℝ) (beta : Column → ℝ) (row : Row) : ℝ :=
  y row - predict X beta row

def sse (X : Row → Column → ℝ) (y : Row → ℝ) (beta : Column → ℝ) : ℝ :=
  ∑ row, residual X y beta row ^ 2

def normalEquations (X : Row → Column → ℝ) (y : Row → ℝ) (beta : Column → ℝ) : Prop :=
  ∀ j, ∑ row, X row j * residual X y beta row = 0

theorem prediction_add (X : Row → Column → ℝ) (beta delta : Column → ℝ) (row : Row) :
    predict X (fun j => beta j + delta j) row = predict X beta row + predict X delta row := by
  simp [predict, mul_add, Finset.sum_add_distrib]

theorem residual_add (X : Row → Column → ℝ) (y : Row → ℝ)
    (beta delta : Column → ℝ) (row : Row) :
    residual X y (fun j => beta j + delta j) row = residual X y beta row - predict X delta row := by
  unfold residual
  rw [prediction_add]
  ring

theorem normal_residual_orthogonal (X : Row → Column → ℝ) (y : Row → ℝ)
    (beta delta : Column → ℝ) (normal : normalEquations X y beta) :
    ∑ row, residual X y beta row * predict X delta row = 0 := by
  classical
  calc
    _ = ∑ row, ∑ j, (X row j * residual X y beta row) * delta j := by
      apply Finset.sum_congr rfl
      intro row _
      simp only [predict, Finset.mul_sum]
      apply Finset.sum_congr rfl
      intro j _
      ring
    _ = ∑ j, (∑ row, X row j * residual X y beta row) * delta j := by
      rw [Finset.sum_comm]
      simp only [Finset.sum_mul]
    _ = 0 := by simp [normalEquations] at normal; simp [normal]

theorem ols_pythagorean (X : Row → Column → ℝ) (y : Row → ℝ)
    (beta delta : Column → ℝ) (normal : normalEquations X y beta) :
    sse X y (fun j => beta j + delta j) = sse X y beta + ∑ row, predict X delta row ^ 2 := by
  have orthogonal := normal_residual_orthogonal X y beta delta normal
  calc
    _ = ∑ row, (residual X y beta row ^ 2 + predict X delta row ^ 2 -
          2 * (residual X y beta row * predict X delta row)) := by
      unfold sse
      apply Finset.sum_congr rfl
      intro row _
      rw [residual_add]
      ring
    _ = sse X y beta + (∑ row, predict X delta row ^ 2) -
        2 * (∑ row, residual X y beta row * predict X delta row) := by
      simp only [sse, Finset.sum_sub_distrib, Finset.sum_add_distrib, Finset.mul_sum]
    _ = _ := by rw [orthogonal]; ring

theorem normal_equations_minimize_sse (X : Row → Column → ℝ) (y : Row → ℝ)
    (beta : Column → ℝ) (normal : normalEquations X y beta) :
    ∀ other, sse X y beta ≤ sse X y other := by
  intro other
  have identity := ols_pythagorean X y beta (fun j => other j - beta j) normal
  have same : (fun j => beta j + (other j - beta j)) = other := by funext j; ring
  rw [same] at identity
  have nonnegative : 0 ≤ ∑ row, predict X (fun j => other j - beta j) row ^ 2 :=
    Finset.sum_nonneg (fun _ _ => sq_nonneg _)
  linarith

end GoDSAT.LeastSquares
