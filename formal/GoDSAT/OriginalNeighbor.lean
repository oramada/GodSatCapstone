import GoDSAT.Refinement
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

def qtableValues : Array ℤ := #[Int.ofNat 387062, Int.ofNat 430119, Int.ofNat 478131, Int.ofNat 531380, Int.ofNat 590470, Int.ofNat 656053, Int.ofNat 590432, Int.ofNat 531367, Int.ofNat 478143, Int.ofNat 430165, Int.ofNat 387037, Int.ofNat 430297, Int.ofNat 478000, Int.ofNat 531341, Int.ofNat 590449, Int.ofNat 656092, Int.ofNat 728977, Int.ofNat 656077, Int.ofNat 590451, Int.ofNat 531348, Int.ofNat 478141, Int.ofNat 430211, Int.ofNat 478205, Int.ofNat 531347, Int.ofNat 590461, Int.ofNat 656079, Int.ofNat 728995, Int.ofNat 809991, Int.ofNat 728996, Int.ofNat 656091, Int.ofNat 590455, Int.ofNat 531358, Int.ofNat 478132, Int.ofNat 531395, Int.ofNat 590470, Int.ofNat 656093, Int.ofNat 728996, Int.ofNat 809999, Int.ofNat 900000, Int.ofNat 809998, Int.ofNat 728996, Int.ofNat 656088, Int.ofNat 590462, Int.ofNat 531352, Int.ofNat 590461, Int.ofNat 656090, Int.ofNat 728995, Int.ofNat 809999, Int.ofNat 900000, Int.ofNat 1000000, Int.ofNat 900000, Int.ofNat 809999, Int.ofNat 728996, Int.ofNat 656095, Int.ofNat 590462, Int.ofNat 656055, Int.ofNat 728981, Int.ofNat 809993, Int.ofNat 900000, Int.ofNat 1000000, Int.ofNat 1100000, Int.ofNat 1000000, Int.ofNat 900000, Int.ofNat 809999, Int.ofNat 728998, Int.ofNat 656092, Int.ofNat 590407, Int.ofNat 656057, Int.ofNat 728981, Int.ofNat 809997, Int.ofNat 900000, Int.ofNat 1000000, Int.ofNat 900000, Int.ofNat 810000, Int.ofNat 728998, Int.ofNat 656090, Int.ofNat 590463, Int.ofNat 531294, Int.ofNat 590418, Int.ofNat 656073, Int.ofNat 728993, Int.ofNat 809998, Int.ofNat 900000, Int.ofNat 810000, Int.ofNat 728999, Int.ofNat 656095, Int.ofNat 590472, Int.ofNat 531391, Int.ofNat 478107, Int.ofNat 531187, Int.ofNat 590436, Int.ofNat 656082, Int.ofNat 728994, Int.ofNat 809997, Int.ofNat 728997, Int.ofNat 656093, Int.ofNat 590469, Int.ofNat 531358, Int.ofNat 478198, Int.ofNat 430147, Int.ofNat 478047, Int.ofNat 531309, Int.ofNat 590436, Int.ofNat 656081, Int.ofNat 728993, Int.ofNat 656083, Int.ofNat 590456, Int.ofNat 531398, Int.ofNat 478153, Int.ofNat 430311, Int.ofNat 386921, Int.ofNat 429977, Int.ofNat 478076, Int.ofNat 531309, Int.ofNat 590448, Int.ofNat 656087, Int.ofNat 590458, Int.ofNat 531367, Int.ofNat 478201, Int.ofNat 430234, Int.ofNat 387072]
def expectedIndices : Array Nat := #[11, 2, 3, 4, 15, 16, 17, 18, 7, 8, 21, 22, 23, 24, 15, 26, 27, 28, 29, 30, 31, 20, 33, 34, 35, 36, 37, 38, 39, 40, 29, 42, 31, 34, 35, 36, 47, 48, 49, 50, 51, 52, 53, 54, 45, 46, 47, 58, 59, 60, 61, 62, 63, 64, 53, 56, 57, 58, 59, 60, 60, 60, 61, 62, 63, 64, 67, 56, 69, 58, 59, 60, 61, 62, 73, 64, 65, 78, 79, 80, 81, 70, 71, 72, 73, 84, 85, 86, 77, 90, 91, 92, 81, 82, 83, 84, 85, 86, 87, 88, 101, 90, 91, 92, 93, 94, 95, 96, 107, 98, 99, 112, 101, 114, 115, 104, 115, 116, 107, 118, 109]
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

def sourceNumerator : Fin 3 → ℤ := ![Int.ofNat 1, Int.ofNat 0, Int.ofNat 0]
def sourceDenominator : Fin 3 → ℕ := ![1, 1, 1]
def portNumerator : Fin 3 → ℤ := ![Int.ofNat 4996954135095479, Int.ofNat 3489949670250097, Int.ofNat 0]
def portDenominator : Fin 3 → ℕ := ![5000000000000000, 100000000000000000, 1]
def sourceObservation (i : Fin 3) : ℚ := (sourceNumerator i : ℚ) / sourceDenominator i
def portObservation (i : Fin 3) : ℚ := (portNumerator i : ℚ) / portDenominator i

theorem observed_port_second_coordinate_positive : 0 < portObservation 1 := by
  norm_num [portObservation, portNumerator, portDenominator]

theorem observed_headless_outputs_differ : sourceObservation ≠ portObservation := by
  intro equality
  have component := congrFun equality 1
  norm_num [sourceObservation, portObservation, sourceNumerator, sourceDenominator, portNumerator, portDenominator] at component

end GoDSAT.OriginalNeighbor
