"""Emit kernel-checkable certificates for hashed original-code observations."""
import csv
from fractions import Fraction
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=Path('/home/omarramadan/Desktop/GoDSat-MnS-Framework')


def vec(values):return '!['+', '.join(str(v) for v in values)+']'
def array(values):return '#['+', '.join(str(v) for v in values)+']'
def int_literal(value):
    value=int(value)
    return f'Int.ofNat {value}' if value>=0 else f'Int.negSucc {-value-1}'
def rational(value):
    x=Fraction(str(value))
    return f'({x.numerator} / {x.denominator} : ℚ)'


def generate():
    folder=ROOT/'outputs/faithful-reproduction-20261027/controller-probes'
    with (UPSTREAM/'q_table.csv').open() as f:values=[Fraction(v) for row in csv.reader(f) for v in row]
    assert len(values)==121
    scaled=[v*10000 for v in values];assert all(v.denominator==1 for v in scaled)
    results=json.loads((folder/'neighbor-results.json').read_text())[:121]
    expected=[(int(row['row'])-1)*11+int(row['col'])-1 for row in results]
    assert len(expected)==121 and all(0<=x<121 for x in expected)
    source=json.loads((folder/'source-headless-result.json').read_text())['after']
    port=json.loads((folder/'port-headless-result.json').read_text())['after']
    source_fractions=[Fraction(str(v)) for v in source]
    port_fractions=[Fraction(str(v)) for v in port]
    text=f'''import GoDSAT.Refinement
import Mathlib.Data.Fin.VecNotation
import Mathlib.Tactic.NormNum

/-! Concrete component/observation certificates, not whole-controller parity.
The source hashes and observed Octave results are in controller-probes/.
Q values use the exact decimal CSV scaled by 10,000; the numerical bridge
has been checked against the unchanged upstream helper on all 121 cells.
-/
namespace GoDSAT.OriginalNeighbor
set_option maxRecDepth 100000
set_option maxHeartbeats 16000000

def qtableValues : Array ℤ := {array(int_literal(v) for v in scaled)}
def expectedIndices : Array Nat := {array(expected)}
@[noinline] def qvalue (p : Fin 121) : ℤ := qtableValues[p.val]!
def expected (p : Fin 121) : Fin 121 :=
  ⟨expectedIndices[p.val]! % 121, Nat.mod_lt _ (by decide)⟩

theorem recorded_tables_well_formed : qtableValues.size = 121 ∧ expectedIndices.size = 121 ∧
    ∀ p : Fin 121, expectedIndices[p.val]! < 121 := by decide

def boundedIndex (r c : ℤ) : Option (Fin 121) :=
  if 0 ≤ r ∧ r < 11 ∧ 0 ≤ c ∧ c < 11 then
    some ⟨(r.toNat * 11 + c.toNat) % 121, Nat.mod_lt _ (by decide)⟩
  else none

def neighbors (p : Fin 121) : List (Fin 121) :=
  let r : ℤ := p.val / 11
  let c : ℤ := p.val % 11
  [(-1,0), (1,0), (0,-1), (0,1)].filterMap fun offset =>
    boundedIndex (r + offset.1) (c + offset.2)

@[noinline] def next (p : Fin 121) : Fin 121 :=
  (neighbors p).foldl (Refinement.chooseHigher qvalue) p

theorem original_qtable_neighbor_all_cells : ∀ p : Fin 121, next p = expected p := by decide

theorem original_qtable_neighbor_never_decreases (p : Fin 121) : qvalue p ≤ qvalue (next p) :=
  Refinement.neighbor_scan_never_decreases qvalue p (neighbors p)

def sourceNumerator : Fin 3 → ℤ := {vec(int_literal(v.numerator) for v in source_fractions)}
def sourceDenominator : Fin 3 → ℕ := {vec(v.denominator for v in source_fractions)}
def portNumerator : Fin 3 → ℤ := {vec(int_literal(v.numerator) for v in port_fractions)}
def portDenominator : Fin 3 → ℕ := {vec(v.denominator for v in port_fractions)}
def sourceObservation (i : Fin 3) : ℚ := (sourceNumerator i : ℚ) / sourceDenominator i
def portObservation (i : Fin 3) : ℚ := (portNumerator i : ℚ) / portDenominator i

theorem observed_port_second_coordinate_positive : 0 < portObservation 1 := by
  norm_num [portObservation, portNumerator, portDenominator]

theorem observed_headless_outputs_differ : sourceObservation ≠ portObservation := by
  intro equality
  have component := congrFun equality 1
  norm_num [sourceObservation, portObservation, sourceNumerator, sourceDenominator, portNumerator, portDenominator] at component

end GoDSAT.OriginalNeighbor
'''
    (ROOT/'formal/GoDSAT/OriginalNeighbor.lean').write_text(text)
    print('Generated original 121-cell neighbor and observed headless counterexample certificates')


if __name__=='__main__':generate()
