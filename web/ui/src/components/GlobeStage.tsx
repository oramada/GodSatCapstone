// The globe fills the window behind every tool. It is space, so it stays dark in both
// appearances (a `data-theme="dark"` scope); the words over it sit on glass, which follows
// the person's appearance. While a scene loads, a capsule says so and leaves when it's done
// (Presence keeps the last words for its exit). The frame label stays in a corner at every
// width, above the playback bar until the window is wide enough to sit beside it. When the
// globe can't draw at all, the stage stands on the night sky instead of an empty black page.

import { Button, Card, EmptyState, GlassPanel, IconButton, Presence, Shimmer, Spinner, Text } from "@sam/design-system";
import { SkyBackdrop } from "@sam/design-system/backdrops";
import { MinusIcon, MonitorXIcon, PlusIcon, RotateCcwIcon, RotateCwIcon } from "lucide-react";
import { type Ref, useState } from "react";

import { useEngine, useStudio } from "../engine/context";

export function GlobeStage({ globeRef, creditsRef }: { globeRef: Ref<HTMLDivElement>; creditsRef: Ref<HTMLDivElement> }) {
  const engine = useEngine();
  const tracking = useStudio((s) => s.tracking);
  const boxSelection = useStudio((s) => s.boxSelection);
  const loading = useStudio((s) => s.loading);
  const error = useStudio((s) => s.rendererError);
  const freeFlight = useStudio((s) => s.cameraMode === "free");
  const frame = useStudio((s) => s.scene?.frame);
  const title = useStudio((s) => s.scene?.title ?? "Choose a saved scene");
  // The words the capsule last showed, so it can leave still saying them.
  const [said, setSaid] = useState(loading);
  if (loading && loading !== said) setSaid(loading);
  return (
    <main id="workspace-content" aria-label="Globe workspace" tabIndex={-1} className="fixed inset-0 outline-none">
      <h1 className="sr-only">{title}</h1>
      <div data-theme="dark" className="absolute inset-0 bg-canvas">
        <div
          ref={globeRef}
          role="region"
          aria-label="3D globe camera"
          aria-describedby={freeFlight ? "flight-controls" : undefined}
          tabIndex={freeFlight ? 0 : undefined}
          className={`absolute inset-0 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring ${boxSelection ? "cursor-crosshair" : ""}`}
        />
        <div ref={creditsRef} className="absolute right-3 bottom-32 w-48 opacity-60 sm:bottom-4" />
      </div>
      {error ? (
        <div className="absolute inset-0 isolate grid place-items-center overflow-hidden p-4">
          <SkyBackdrop placement="fill" scene="night" horizon={82} arrive />
          <GlassPanel className="w-full max-w-sm">
            <EmptyState
              size="compact"
              arrive
              icon={<MonitorXIcon />}
              title="3D rendering is unavailable"
              description={error}
              action={(
                <Button onClick={() => window.location.reload()}>
                  <RotateCwIcon />
                  Reload Studio
                </Button>
              )}
            />
          </GlassPanel>
        </div>
      ) : (
        <div className="pointer-events-none absolute inset-0 grid place-items-center p-4">
          <Presence open={!!loading} role="status" aria-live="polite">
            <Card variant="glass" radius="capsule" padding="capsule" className="flex items-center gap-2">
              <Spinner size="sm" tone="muted" />
              <Text as="span">
                <Shimmer text={said || "Loading"} active={!!loading} />
              </Text>
            </Card>
          </Presence>
        </div>
      )}
      {tracking || boxSelection ? (
        <Card variant="glass" radius="capsule" padding="track" className="absolute top-32 left-2 z-10 flex items-center gap-1 sm:top-16 sm:left-4">
          {tracking ? (
            <>
              <IconButton label="Zoom closer to satellite" onClick={() => engine.zoomSatellite(0.67)}><PlusIcon /></IconButton>
              <IconButton label="Zoom farther from satellite" onClick={() => engine.zoomSatellite(1.5)}><MinusIcon /></IconButton>
              <IconButton label="Return to Earth view" onClick={() => engine.resetView()}><RotateCcwIcon /></IconButton>
            </>
          ) : null}
          {boxSelection ? (
            <Button variant="ghost" size="sm" onClick={() => engine.setBoxSelection(false)}>Done selecting</Button>
          ) : null}
        </Card>
      ) : null}
      {frame ? (
        <Card
          variant="glass"
          radius="capsule"
          padding="capsule"
          className="pointer-events-none absolute bottom-44 left-2 right-2 flex w-fit items-center gap-3 sm:bottom-32 sm:left-4"
        >
          <Text as="span" size="2xs" weight="medium" className="shrink-0">
            {frame} · km
          </Text>
          {boxSelection ? (
            <Text as="span" size="2xs" tone="muted">Drag a box around satellites</Text>
          ) : freeFlight ? (
            <Text id="flight-controls" as="span" size="2xs" tone="muted" className="max-w-80">
              Click globe · Drag or arrows to look · Z/C to roll · WASD to fly · Q/E down/up · Shift to boost
            </Text>
          ) : tracking ? (
            <Text as="span" size="2xs" tone="muted">Scroll or use +/− to zoom · Drag to orbit satellite</Text>
          ) : (
            <Text as="span" size="2xs" tone="muted" className="hidden xl:inline">
              Drag to orbit · Scroll to zoom · Shift-drag to select
            </Text>
          )}
        </Card>
      ) : null}
    </main>
  );
}
