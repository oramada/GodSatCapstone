// Experiment Studio's window: the globe behind everything, the toolbar and the clock over it,
// and one tool panel at a time (Experiment, Layers, Data, Inspect). Escape closes the open
// panel and returns focus to the button that opened it; Space plays and pauses the clock
// when the focus isn't on a control.

import { Button, toastManager } from "@sam/design-system";
import { ChevronRightIcon, SatelliteIcon, TargetIcon, XIcon } from "lucide-react";
import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { GlobeStage } from "./components/GlobeStage";
import { type PanelId } from "./components/Panel";
import { PlaybackBar } from "./components/PlaybackBar";
import { TopBar } from "./components/TopBar";
import { EngineProvider, useEngine, useStudio } from "./engine/context";
import { StudioEngine } from "./engine/studio";
import { DataPanel } from "./panels/DataPanel";
import { ExperimentPanel } from "./panels/ExperimentPanel";
import { InspectPanel } from "./panels/InspectPanel";
import { LayersPanel } from "./panels/LayersPanel";

export function App() {
  const [engine] = useState(() => new StudioEngine());
  const [open, setOpen] = useState<PanelId | null>(null);
  const globe = useRef<HTMLDivElement>(null);
  const credits = useRef<HTMLDivElement>(null);
  const detail = useRef<HTMLCanvasElement>(null);
  // One stable ref per toolbar button: focus goes back to it, and its panel grows from it.
  const [triggers] = useState<Record<PanelId, RefObject<HTMLButtonElement | null>>>(() => ({
    experiment: { current: null },
    layers: { current: null },
    data: { current: null },
    inspect: { current: null },
  }));
  const headings = useRef(new Map<PanelId, HTMLHeadingElement>());
  const focusHeading = useRef(false);

  useEffect(() => {
    engine.onNotice = (message) => toastManager.add({ type: "error", title: message, timeout: 6500 });
    if (globe.current && detail.current && credits.current) void engine.start(globe.current, detail.current, credits.current);
    return () => engine.stop();
  }, [engine]);

  const show = useCallback((id: PanelId | null, moveFocus = true) => {
    focusHeading.current = moveFocus && id !== null;
    setOpen(id);
  }, []);

  const close = useCallback(() => {
    if (open) triggers[open].current?.focus();
    setOpen(null);
  }, [open, triggers]);

  useEffect(() => {
    if (open && focusHeading.current) headings.current.get(open)?.focus({ preventScroll: true });
    focusHeading.current = false;
  }, [open]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // A key pressed in a dialog is the dialog's (its Escape closes it, not the panel under it).
      if (event.defaultPrevented || inDialog(event.target)) return;
      if (event.key === "Escape" && open) {
        event.preventDefault();
        close();
        return;
      }
      if (event.key === " " && !event.repeat && !event.metaKey && !event.ctrlKey && !event.altKey && !onControl(event.target)) {
        event.preventDefault();
        engine.togglePlay();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close, engine]);

  // A panel that opens a scene closes so the scene is in view, and focus goes to the globe
  // (the pressed button is leaving with its panel).
  const toGlobe = useCallback(() => {
    show(null, false);
    document.getElementById("workspace-content")?.focus({ preventScroll: true });
  }, [show]);

  const openScene = useCallback(
    (id: string) => {
      toGlobe();
      engine.openScene(id);
    },
    [engine, toGlobe],
  );

  const panel = (id: PanelId) => ({
    open: open === id,
    onClose: close,
    trigger: triggers[id],
    headingRef: (node: HTMLHeadingElement | null) => {
      if (node) headings.current.set(id, node);
      else headings.current.delete(id);
    },
  });

  return (
    <EngineProvider engine={engine}>
      <Button
        variant="glass"
        size="sm"
        shape="capsule"
        render={<a href="#workspace-content" />}
        className="sr-only z-50 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to workspace content
      </Button>
      <GlobeStage globeRef={globe} creditsRef={credits} />
      <TopBar
        open={open}
        onToggle={(id) => (open === id ? close() : show(id))}
        triggers={triggers}
      />
      <PlaybackBar />
      <SelectionChip hidden={open === "inspect"} onInspect={() => show("inspect")} />
      <ExperimentPanel
        {...panel("experiment")}
        onOpenResult={(id) => {
          toGlobe();
          void engine.refresh().then(() => engine.openScene(id));
        }}
      />
      <LayersPanel {...panel("layers")} />
      <DataPanel {...panel("data")} onOpenScene={openScene} />
      <InspectPanel {...panel("inspect")} detailRef={detail} />
    </EngineProvider>
  );
}

/** Where Space would act on a control instead of the clock: fields, buttons, sliders, lists, menus. */
function onControl(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    !!target.closest('input, textarea, select, button, a[href], [contenteditable="true"], [role="slider"], [role="combobox"], [role="listbox"], [role="menu"], [role="option"]')
  );
}

function inDialog(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest('[role="dialog"], [role="alertdialog"]');
}

/** A satellite picked on the globe: one press opens it in Inspect. Arrives with the pick (rule 1). */
function SelectionChip({ hidden, onInspect }: { hidden: boolean; onInspect: () => void }) {
  const engine = useEngine();
  const count = useStudio((s) => s.selectedIds.length);
  const tracking = useStudio((s) => s.tracking);
  const shown = useStudio((s) => s.selectedByUser);
  const focusId = useStudio((s) => s.focusId);
  const name = useStudio((s) => s.scene?.objects.find((o) => o.id === s.focusId)?.name ?? "Selected satellite");
  if (!shown || hidden) return null;
  return (
    <div key={focusId} className="motion-enter fixed bottom-32 left-1/2 z-20 flex w-max max-w-[calc(100%-1rem)] -translate-x-1/2 gap-1 sm:bottom-36">
      <Button variant="glass" size="sm" shape="capsule" onClick={onInspect}>
        <SatelliteIcon />
        <span className="truncate">{count > 1 ? `${count.toLocaleString()} satellites selected` : `Inspect ${name}`}</span>
        <ChevronRightIcon />
      </Button>
      <Button variant="glass" size="sm" shape="capsule" aria-label={tracking ? "Recenter on satellite" : "Zoom to satellite"}
        onClick={() => engine.followSatellite()}>
        <TargetIcon />
      </Button>
      <Button variant="glass" size="sm" shape="capsule" aria-label="Clear satellite selection" onClick={() => engine.selectSatellites([])}>
        <XIcon />
      </Button>
    </div>
  );
}
