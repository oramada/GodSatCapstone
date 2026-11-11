import { Badge, Button, Card, ChoiceSelect, SegmentThumb, Swap } from "@sam/design-system";
import { OrbitIcon } from "lucide-react";
import { type RefObject, useMemo } from "react";

import { useEngine, useStudio } from "../engine/context";
import { sourceKindLabel } from "../engine/studio";
import { PANEL_ICON } from "./icons";
import type { PanelId } from "./Panel";

const PANELS: { id: PanelId; label: string; controls: string }[] = [
  { id: "experiment", label: "Experiment", controls: "experiment-panel" },
  { id: "layers", label: "Layers", controls: "layers-panel" },
  { id: "data", label: "Data", controls: "data-panel" },
  { id: "inspect", label: "Inspect", controls: "inspect-panel" },
];

export function TopBar({
  open,
  onToggle,
  triggers,
}: {
  open: PanelId | null;
  onToggle: (id: PanelId) => void;
  triggers: Record<PanelId, RefObject<HTMLButtonElement | null>>;
}) {
  const engine = useEngine();
  const sources = useStudio((s) => s.sourceOptions);
  // Paths run long: the list shows the whole one on hover.
  const options = useMemo(() => sources.map((o) => ({ ...o, title: o.label })), [sources]);
  const value = useStudio((s) => s.sourceValue);
  const kind = useStudio((s) => s.scene?.source.kind);
  return (
    <header className="pointer-events-none fixed inset-x-2 top-2 z-40 flex flex-wrap items-center gap-2 sm:inset-x-4 sm:top-4">
      <Card
        variant="glass"
        radius="capsule"
        padding="track"
        className="pointer-events-auto flex min-w-0 basis-full items-center gap-2 sm:basis-auto"
      >
        <Button variant="ghost" size="sm" shape="capsule" render={<a href="/" />} aria-label="GoDSAT home" className="shrink-0">
          <OrbitIcon aria-hidden />
          GoDSAT
        </Button>
        <ChoiceSelect
          label="Scene source"
          value={value}
          options={options}
          onChange={(next) => engine.setSource(next)}
          className="min-w-0 flex-1 sm:w-72 sm:flex-none"
        />
        {kind ? (
          <Badge variant="outline" className="shrink-0">
            <Swap value={kind}>{sourceKindLabel(kind)}</Swap>
          </Badge>
        ) : null}
      </Card>
      {/* On a phone the tabs span the screen, icon over label; from sm they sit in a row at the right. */}
      <nav aria-label="Workspace panels" className="pointer-events-auto ms-auto basis-full sm:basis-auto">
        {/* One pill slides to the open panel's button (rule 20); none when every panel is closed. */}
        <Card variant="glass" radius="capsule" padding="track" className="motion-segments flex items-center gap-0.5">
          {PANELS.map((panel) => {
            const Icon = PANEL_ICON[panel.id];
            return (
            <Button
              key={panel.id}
              ref={triggers[panel.id]}
              variant="tab"
              size="tabbar"
              shape="capsule"
              aria-controls={panel.controls}
              aria-expanded={open === panel.id}
              onClick={() => onToggle(panel.id)}
            >
              {open === panel.id ? <SegmentThumb group="workspace-panels" /> : null}
              <Icon aria-hidden />
              <span>{panel.label}</span>
            </Button>
            );
          })}
        </Card>
      </nav>
    </header>
  );
}
