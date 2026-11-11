import type { StatusTone } from "@sam/design-system";

import type { TrackStateName } from "../engine/types";

/** A track's custody as a kit status tone: the same colours the globe draws it in. */
export const TONE: Record<TrackStateName, StatusTone> = {
  observed: "success",
  stale: "attention",
  lost: "danger",
  unknown: "neutral",
  unavailable: "idle",
};
