import { createContext, useContext, type ReactNode } from "react";

import { useStore } from "./store";
import type { Readout, StudioEngine, StudioState } from "./studio";

const EngineContext = createContext<StudioEngine | null>(null);

export function EngineProvider({ engine, children }: { engine: StudioEngine; children: ReactNode }) {
  return <EngineContext value={engine}>{children}</EngineContext>;
}

export function useEngine(): StudioEngine {
  const engine = useContext(EngineContext);
  if (!engine) throw new Error("useEngine needs an EngineProvider");
  return engine;
}

/** One field (or a stable slice) of the engine's state. */
export function useStudio<S>(select: (state: StudioState) => S): S {
  return useStore(useEngine().state, select);
}

/** One field of the clock's readout (null until a scene is on screen). */
export function useReadout<S>(select: (readout: Readout | null) => S): S {
  return useStore(useEngine().readout, select);
}
