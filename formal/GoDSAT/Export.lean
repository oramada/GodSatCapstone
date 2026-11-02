import GoDSAT
import Lean

/-! Export the checked finite specification for comparison with actual CSVs.
This executable exports data; its output does not establish controller parity.
-/
open Lean

def main : IO Unit := do
  IO.eprintln "Exporting checked finite specifications"
  let screening := (List.finRange 16).map fun r =>
    (List.finRange 7).map fun j => GoDSAT.Design.code r j
  let ccd := (List.finRange 15).map fun r =>
    (List.finRange 10).map fun j => GoDSAT.CCD.feature r j
  let masks : List Nat := [0,23,43,60,77,90,102,113]
  -- Large integers are serialized as decimal strings, avoiding JSON numeric
  -- normalization costs and preserving exactness for >2^53 observations.
  let originalQ := (List.finRange 121).map fun p => toString (GoDSAT.OriginalNeighbor.qvalue p)
  -- The all-cells theorem proves `next p = expected p`; export that checked
  -- table instead of redundantly evaluating the interpreted scan again.
  let originalNeighbor := (List.finRange 121).map fun p => (GoDSAT.OriginalNeighbor.expected p).val
  let sourceObservation := (List.finRange 3).map fun i =>
    (toString (GoDSAT.OriginalNeighbor.sourceNumerator i), toString (GoDSAT.OriginalNeighbor.sourceDenominator i))
  let portObservation := (List.finRange 3).map fun i =>
    (toString (GoDSAT.OriginalNeighbor.portNumerator i), toString (GoDSAT.OriginalNeighbor.portDenominator i))
  let data := Json.mkObj [("screening", toJson screening),
    ("ccd", toJson ccd), ("defining_masks", toJson masks),
    ("original_qtable_scaled",toJson originalQ), ("original_neighbor_outputs",toJson originalNeighbor),
    ("source_observation",toJson sourceObservation), ("port_observation",toJson portObservation)]
  IO.println data.compress
