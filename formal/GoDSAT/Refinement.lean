import Mathlib.Data.Rat.Defs
import Mathlib.Tactic.Linarith

/-! Explicitly scoped controller invariants and conditional trace refinement.
The final theorem is NOT an original/Python equivalence certificate: its step
relation must be proved against the actual implementations before use.
-/
namespace GoDSAT.Refinement

def chooseHigher {Position Value : Type*} [LinearOrder Value]
    (value : Position → Value) (current candidate : Position) : Position :=
  if value current < value candidate then candidate else current

theorem neighbor_never_decreases {Position Value : Type*} [LinearOrder Value]
    (value : Position → Value) (current candidate : Position) :
    value current ≤ value (chooseHigher value current candidate) := by
  unfold chooseHigher
  split
  · exact le_of_lt (by assumption)
  · exact le_rfl

theorem ties_retain_first {Position Value : Type*} [LinearOrder Value]
    (value : Position → Value) (current candidate : Position)
    (equal : value current = value candidate) : chooseHigher value current candidate = current := by
  simp [chooseHigher, equal]

theorem neighbor_scan_never_decreases {Position Value : Type*} [LinearOrder Value]
    (value : Position → Value)
    (current : Position) (neighbors : List Position) :
    value current ≤ value (neighbors.foldl (chooseHigher value) current) := by
  induction neighbors generalizing current with
  | nil => exact le_rfl
  | cons candidate rest ih =>
    exact le_trans (neighbor_never_decreases value current candidate) (ih _)

abbrev ClaimMap (Bin Satellite : Type*) := Bin → Option Satellite

def refreshClaim {Bin Satellite : Type*} [DecidableEq Bin] [DecidableEq Satellite]
    (old : ClaimMap Bin Satellite) (satellite : Satellite) (newBin : Bin) : ClaimMap Bin Satellite :=
  fun bin => if bin = newBin then some satellite
             else if old bin = some satellite then none else old bin

theorem refreshed_bin_owned {Bin Satellite : Type*} [DecidableEq Bin] [DecidableEq Satellite]
    (old : ClaimMap Bin Satellite) (satellite : Satellite) (newBin : Bin) :
    refreshClaim old satellite newBin newBin = some satellite := by
  simp [refreshClaim]

theorem old_claims_released {Bin Satellite : Type*} [DecidableEq Bin] [DecidableEq Satellite]
    (old : ClaimMap Bin Satellite) (satellite : Satellite) (newBin bin : Bin)
    (different : bin ≠ newBin) (owned : old bin = some satellite) :
    refreshClaim old satellite newBin bin = none := by
  simp [refreshClaim, different, owned]

theorem other_claims_unchanged {Bin Satellite : Type*} [DecidableEq Bin] [DecidableEq Satellite]
    (old : ClaimMap Bin Satellite) (satellite : Satellite) (newBin bin : Bin)
    (different : bin ≠ newBin) (other : old bin ≠ some satellite) :
    refreshClaim old satellite newBin bin = old bin := by
  simp [refreshClaim, different, other]

theorem at_most_one_owner_per_bin {Bin Satellite : Type*} (claims : ClaimMap Bin Satellite)
    (bin : Bin) (first second : Satellite)
    (hfirst : claims bin = some first) (hsecond : claims bin = some second) : first = second :=
  Option.some.inj (hfirst.symm.trans hsecond)

-- A single owner per BIN is weaker than unique tracking per PHYSICAL TARGET.
-- This is a specification countermodel, not a claim of a reachable MATLAB trace.
theorem bin_exclusivity_does_not_imply_unique_target_tracking :
    ∃ claims : ClaimMap (Fin 2) (Fin 2), ∃ locks : Fin 2 → Option Unit,
      (∀ bin first second, claims bin = some first → claims bin = some second → first = second) ∧
      locks 0 = some () ∧ locks 1 = some () ∧ (0 : Fin 2) ≠ 1 := by
  refine ⟨fun bin => some bin, fun _ => some (), ?_, rfl, rfl, by decide⟩
  intro bin first second hfirst hsecond
  exact Option.some.inj (hfirst.symm.trans hsecond)

def run {State Input Output : Type*} (step : State → Input → State × Output)
    (initial : State) (inputs : List Input) : State × List Output :=
  match inputs with
  | [] => (initial, [])
  | input :: remaining =>
    let next := step initial input
    let tail := run step next.1 remaining
    (tail.1, next.2 :: tail.2)

theorem conditional_trace_refinement {Source Target Input Output : Type*}
    (sourceStep : Source → Input → Source × Output)
    (targetStep : Target → Input → Target × Output)
    (related : Source → Target → Prop)
    (stepProof : ∀ s t i, related s t →
      related (sourceStep s i).1 (targetStep t i).1 ∧ (sourceStep s i).2 = (targetStep t i).2)
    (s : Source) (t : Target) (initialProof : related s t) (inputs : List Input) :
    related (run sourceStep s inputs).1 (run targetStep t inputs).1 ∧
      (run sourceStep s inputs).2 = (run targetStep t inputs).2 := by
  induction inputs generalizing s t with
  | nil => exact ⟨initialProof, rfl⟩
  | cons input remaining ih =>
    have one := stepProof s t input initialProof
    have tail := ih (sourceStep s input).1 (targetStep t input).1 one.1
    exact ⟨tail.1, congrArg₂ List.cons one.2 tail.2⟩

end GoDSAT.Refinement
