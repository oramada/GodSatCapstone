import Mathlib.Data.Real.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring

/-! Conditional invariants of the documented model, not hardware calibration.
All positivity/bound assumptions remain visible in theorem statements.
-/
namespace GoDSAT.SensorAssumptions

noncomputable def slewEnergy (inertia speed efficiency drivePower duration : ℝ) : ℝ :=
  inertia * speed ^ 2 / (2 * efficiency) + drivePower * duration

theorem energy_nonnegative (I w eta P t : ℝ)
    (hI : 0 ≤ I) (heta : 0 < eta) (hP : 0 ≤ P) (ht : 0 ≤ t) :
    0 ≤ slewEnergy I w eta P t := by
  unfold slewEnergy
  positivity

theorem no_motion_energy (I eta P : ℝ) : slewEnergy I 0 eta P 0 = 0 := by
  simp [slewEnergy]

theorem acceleration_work (I torque peak eta : ℝ)
    (hI : 0 < I) (htorque : 0 < torque) (heta : 0 < eta) :
    torque * ((1 / 2 : ℝ) * (torque / I) * (I * peak / torque) ^ 2) / eta =
      I * peak ^ 2 / (2 * eta) := by
  field_simp [ne_of_gt hI, ne_of_gt htorque, ne_of_gt heta]

theorem feasible_slew_energy_bound (I peak cap eta P duration slot : ℝ)
    (hI : 0 ≤ I) (heta : 0 < eta) (hP : 0 ≤ P)
    (hpeak : 0 ≤ peak) (hcap : peak ≤ cap) (htime : duration ≤ slot) :
    slewEnergy I peak eta P duration ≤ slewEnergy I cap eta P slot := by
  have hsquare : peak ^ 2 ≤ cap ^ 2 := by
    have hproduct := mul_nonneg (sub_nonneg.mpr hcap) (show 0 ≤ cap + peak by linarith)
    nlinarith
  have hwork := mul_le_mul_of_nonneg_left hsquare hI
  have hdivide : I * peak ^ 2 / (2 * eta) ≤ I * cap ^ 2 / (2 * eta) :=
    (div_le_div_iff_of_pos_right (by positivity)).2 hwork
  exact add_le_add hdivide (mul_le_mul_of_nonneg_left htime hP)

structure TrackState where
  trueSeen : Option Nat
  reportedSeen : Option Nat
  deriving DecidableEq

def falseReturn (s : TrackState) (time : Nat) : TrackState :=
  { s with reportedSeen := some time }

def trueReturn (s : TrackState) (time : Nat) : TrackState :=
  { trueSeen := some time, reportedSeen := some time }

def trueCustody (s : TrackState) (now lifetime : Nat) : Prop :=
  ∃ last, s.trueSeen = some last ∧ last ≤ now ∧ now - last ≤ lifetime

theorem false_return_preserves_truth (s : TrackState) (time now lifetime : Nat) :
    trueCustody (falseReturn s time) now lifetime ↔ trueCustody s now lifetime := Iff.rfl

theorem no_prior_true_detection_has_no_true_custody (reported : Option Nat) (now lifetime : Nat) :
    ¬ trueCustody ⟨none, reported⟩ now lifetime := by
  simp [trueCustody]

theorem false_slots_are_subset {Track : Type*} [DecidableEq Track]
    (reported flagged : Finset Track) : (reported ∩ flagged).card ≤ reported.card :=
  Finset.card_le_card Finset.inter_subset_left

def falseTrackRate (falseSlots reportedSlots : Nat) : ℚ :=
  if reportedSlots = 0 then 0 else (falseSlots : ℚ) / reportedSlots

theorem false_track_rate_bounds (n d : Nat) (h : n ≤ d) :
    0 ≤ falseTrackRate n d ∧ falseTrackRate n d ≤ 1 := by
  by_cases hd : d = 0
  · simp [falseTrackRate, hd]
  · have positive : (0 : ℚ) < d := by exact_mod_cast Nat.pos_of_ne_zero hd
    have hcast : (n : ℚ) ≤ d := by exact_mod_cast h
    simp only [falseTrackRate, if_neg hd]
    exact ⟨div_nonneg (by positivity) (le_of_lt positive),
      (div_le_one₀ positive).2 hcast⟩

-- Explicit countermodels: a design does not logically imply empirical gains.
theorem no_design_only_custody_gain :
    ∃ baseline optimized : ℚ, 0 < baseline ∧ 0 < optimized ∧
      optimized / baseline - 1 < 11 / 100 := by
  exact ⟨1, 1, by norm_num, by norm_num, by norm_num⟩

theorem no_design_only_energy_reduction :
    ∃ baseline optimized : ℚ, 0 < baseline ∧ 0 < optimized ∧
      ¬ (optimized ≤ (91 / 100 : ℚ) * baseline) := by
  exact ⟨1, 1, by norm_num, by norm_num, by norm_num⟩

end GoDSAT.SensorAssumptions
