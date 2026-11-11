// The globe fills the window behind every tool. It is space, so it stays dark in both
// appearances (a `data-theme="dark"` scope); the words over it sit on glass, which follows
// the person's appearance. While a scene loads, a capsule says so and leaves when it's done
// (Presence keeps the last words for its exit). The frame label stays in a corner at every
// width, above the playback bar until the window is wide enough to sit beside it. When the
// globe can't draw at all, the stage stands on the night sky instead of an empty black page.

import { Button, Card, EmptyState, GlassPanel, Presence, Shimmer, Spinner, Text } from "@sam/design-system";
import { SkyBackdrop } from "@sam/design-system/backdrops";
import { MonitorXIcon, RotateCwIcon } from "lucide-react";
import { type Ref, useState } from "react";

import { useStudio } from "../engine/context";

export function GlobeStage({ globeRef, creditsRef }: { globeRef: Ref<HTMLDivElement>; creditsRef: Ref<HTMLDivElement> }) {
  const loading = useStudio((s) => s.loading);
  const error = useStudio((s) => s.rendererError);
  const frame = useStudio((s) => s.scene?.frame);
  const title = useStudio((s) => s.scene?.title ?? "Choose a saved scene");
  // The words the capsule last showed, so it can leave still saying them.
  const [said, setSaid] = useState(loading);
  if (loading && loading !== said) setSaid(loading);
  return (
    <main id="workspace-content" aria-label="Globe workspace" tabIndex={-1} className="fixed inset-0 outline-none">
      <h1 className="sr-only">{title}</h1>
      <div data-theme="dark" className="absolute inset-0 bg-canvas">
        <div ref={globeRef} aria-label="Cesium 3D Earth and satellite trajectories" className="absolute inset-0" />
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
      {frame ? (
        <Card
          variant="glass"
          radius="capsule"
          padding="capsule"
          className="pointer-events-none absolute bottom-32 left-2 flex items-center gap-3 sm:left-4 lg:bottom-6"
        >
          <Text as="span" size="2xs" weight="medium">
            {frame} · km
          </Text>
          <Text as="span" size="2xs" tone="muted" className="hidden xl:inline">
            Drag to orbit · Scroll to zoom
          </Text>
        </Card>
      ) : null}
    </main>
  );
}
