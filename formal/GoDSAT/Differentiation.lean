import GoDSAT.ResponseSurface
import Mathlib.Analysis.Calculus.Deriv.Pow
import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Analysis.Calculus.Deriv.Mul

namespace GoDSAT.Differentiation
open GoDSAT.ResponseSurface
open scoped BigOperators

theorem quadratic_directional_derivative (c : ℝ) (b : Vec) (B : Curvature) (x v : Vec)
    (symmetric : ∀ i j, B i j = B j i) :
    HasDerivAt (fun t : ℝ => quadratic c b B (fun i => x i + t * v i))
      (∑ i, (b i + 2 * ∑ j, B i j * x j) * v i) 0 := by
  let L : ℝ := ∑ i, (b i + 2 * ∑ j, B i j * x j) * v i
  let H : ℝ := homogeneous B v
  have shape : (fun t : ℝ => quadratic c b B (fun i => x i + t * v i)) =
      (fun t : ℝ => quadratic c b B x + t * L + t ^ 2 * H) := by
    funext t
    have change := quadratic_increment c b B x (fun i => t * v i) symmetric
    rw [homogeneous_scales] at change
    have scale : (∑ i, (b i + 2 * ∑ j, B i j * x j) * (t * v i)) = t * L := by
      dsimp [L]
      rw [Finset.mul_sum]
      apply Finset.sum_congr rfl
      intro i _
      ring
    rw [scale] at change
    dsimp [H]
    linarith
  rw [shape]
  have polynomial := ((hasDerivAt_const (0 : ℝ) (quadratic c b B x)).add
    ((hasDerivAt_id (0 : ℝ)).mul_const L)).add
    (((hasDerivAt_id (0 : ℝ)).pow 2).mul_const H)
  convert! polynomial using 1 <;> simp [L, Pi.add_apply]

theorem quadratic_partial_derivative (c : ℝ) (b : Vec) (B : Curvature) (x : Vec)
    (j : Fin 3) (symmetric : ∀ i j, B i j = B j i) :
    deriv (fun t : ℝ => quadratic c b B (fun i => x i + t * (if i = j then 1 else 0))) 0 =
      b j + 2 * ∑ k, B j k * x k := by
  have direction := quadratic_directional_derivative c b B x (fun i => if i = j then 1 else 0) symmetric
  simpa using direction.deriv

theorem stationarity_is_zero_partials (c : ℝ) (b : Vec) (B : Curvature) (x : Vec)
    (symmetric : ∀ i j, B i j = B j i) :
    stationary b B x ↔ ∀ j : Fin 3,
      deriv (fun t : ℝ => quadratic c b B (fun i => x i + t * (if i = j then 1 else 0))) 0 = 0 := by
  simp_rw [quadratic_partial_derivative c b B x _ symmetric]
  rfl

end GoDSAT.Differentiation
