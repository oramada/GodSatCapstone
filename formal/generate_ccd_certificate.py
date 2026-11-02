"""Generate an exact integer left-inverse certificate; Lean checks the result.

Sympy is only an untrusted certificate producer. No floating rank estimate or
Python success status substitutes for the Lean certificate theorem.
"""
import itertools
from pathlib import Path
import sympy as sp


def vector(values):
    return '![' + ', '.join(str(v) for v in values) + ']'


def generate():
    points = list(itertools.product([-1,1],repeat=3))
    points += [tuple(sign if j==i else 0 for j in range(3)) for i in range(3) for sign in [-1,1]]
    points += [(0,0,0)]
    design=sp.Matrix([[1,a,b,c,a*a,b*b,c*c,a*b,a*c,b*c] for a,b,c in points])
    left=(design.T*design).inv()*design.T
    scale=sp.ilcm(*(value.q for value in left))
    integer=left*scale
    point_text=vector(vector(row) for row in points)
    left_text=vector(vector([integer[i,j] for j in range(15)]) for i in range(10))
    text=f'''import Mathlib.Data.Fin.VecNotation
import Mathlib.Data.Matrix.Mul

/-! Generated exact certificate. The theorem is checked by Lean's kernel. -/
namespace GoDSAT.CCD
open scoped BigOperators
set_option maxRecDepth 100000
set_option maxHeartbeats 16000000

def point : Fin 15 → Fin 3 → ℤ := {point_text}

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

def scaledLeftInverse : Fin 10 → Fin 15 → ℤ := {left_text}

theorem left_inverse_certificate : ∀ i j : Fin 10,
    ∑ r : Fin 15, scaledLeftInverse i r * feature r j =
      if i = j then {scale} else 0 := by decide

theorem distinct_design_points : ∀ i j : Fin 15,
    (∀ k : Fin 3, point i k = point j k) → i = j := by decide

end GoDSAT.CCD
'''
    target=Path(__file__).parent/'GoDSAT/CCDCertificate.lean'
    target.write_text(text)
    print('Generated integer certificate with scale',scale)


if __name__=='__main__':generate()
