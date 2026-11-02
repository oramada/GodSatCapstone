import Mathlib.Data.Fin.VecNotation
import Mathlib.Data.Matrix.Mul

/-! Generated exact certificate. The theorem is checked by Lean's kernel. -/
namespace GoDSAT.CCD
open scoped BigOperators
set_option maxRecDepth 100000
set_option maxHeartbeats 16000000

def point : Fin 15 → Fin 3 → ℤ := ![![-1, -1, -1], ![-1, -1, 1], ![-1, 1, -1], ![-1, 1, 1], ![1, -1, -1], ![1, -1, 1], ![1, 1, -1], ![1, 1, 1], ![-1, 0, 0], ![1, 0, 0], ![0, -1, 0], ![0, 1, 0], ![0, 0, -1], ![0, 0, 1], ![0, 0, 0]]

def feature (r : Fin 15) (j : Fin 10) : ℤ :=
  match j.val with
  | 0 => 1
  | 1 => point r 0
  | 2 => point r 1
  | 3 => point r 2
  | 4 => point r 0 ^ 2
  | 5 => point r 1 ^ 2
  | 6 => point r 2 ^ 2
  | 7 => point r 0 * point r 1
  | 8 => point r 0 * point r 2
  | _ => point r 1 * point r 2

def scaledLeftInverse : Fin 10 → Fin 15 → ℤ := ![![-16, -16, -16, -16, -16, -16, -16, -16, 64, 64, 64, 64, 64, 64, 104], ![-36, -36, -36, -36, 36, 36, 36, 36, -36, 36, 0, 0, 0, 0, 0], ![-36, -36, 36, 36, -36, -36, 36, 36, 0, 0, -36, 36, 0, 0, 0], ![-36, 36, -36, 36, -36, 36, -36, 36, 0, 0, 0, 0, -36, 36, 0], ![20, 20, 20, 20, 20, 20, 20, 20, 100, 100, -80, -80, -80, -80, -40], ![20, 20, 20, 20, 20, 20, 20, 20, -80, -80, 100, 100, -80, -80, -40], ![20, 20, 20, 20, 20, 20, 20, 20, -80, -80, -80, -80, 100, 100, -40], ![45, 45, -45, -45, -45, -45, 45, 45, 0, 0, 0, 0, 0, 0, 0], ![45, -45, 45, -45, -45, 45, -45, 45, 0, 0, 0, 0, 0, 0, 0], ![45, -45, -45, 45, 45, -45, -45, 45, 0, 0, 0, 0, 0, 0, 0]]

theorem left_inverse_certificate : ∀ i j : Fin 10,
    ∑ r : Fin 15, scaledLeftInverse i r * feature r j =
      if i = j then 360 else 0 := by decide

theorem distinct_design_points : ∀ i j : Fin 15,
    (∀ k : Fin 3, point i k = point j k) → i = j := by decide

end GoDSAT.CCD
