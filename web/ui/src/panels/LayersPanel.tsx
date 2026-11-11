import {
  ChoiceSelect,
  Disclosure,
  IconButton,
  ListGroup,
  ListRow,
  SectionHeader,
  Segmented,
  Separator,
  StatusLabel,
  Swap,
  Switch,
} from "@sam/design-system";
import {
  CameraIcon,
  CloudIcon,
  CrosshairIcon,
  EarthIcon,
  GaugeIcon,
  MapPinnedIcon,
  OrbitIcon,
  RadioIcon,
  RotateCwIcon,
  RouteIcon,
  SlidersHorizontalIcon,
  SunMoonIcon,
  ThermometerIcon,
  WindIcon,
} from "lucide-react";
import { type ReactNode, type RefObject, useState } from "react";

import { Fine, Panel } from "../components/Panel";
import { PANEL_ICON } from "../components/icons";
import { useEngine, useReadout, useStudio } from "../engine/context";
import type { RendererLayers } from "../engine/legacy";
import type { CloudCover, Framing, Mode, Quality } from "../engine/studio";

const MODES: { value: Mode; label: string; icon: ReactNode }[] = [
  { value: "single", label: "Focused object", icon: <CrosshairIcon /> },
  { value: "system", label: "All objects", icon: <OrbitIcon /> },
];
const CLOUDS: { value: CloudCover; label: string }[] = [
  { value: "natural", label: "Texture" },
  { value: "clear", label: "Clear" },
  { value: "dense", label: "Overcast variant" },
];
const ENVIRONMENT = [
  { value: "none", label: "Off" },
  { value: "vertical_tec_tecu", label: "Ionosphere · TEC" },
  { value: "electron_density_m3", label: "Electron density" },
  { value: "magnetic", label: "Magnetic vectors" },
  { value: "cloud_fraction", label: "Weather · cloud fraction" },
  { value: "neutral_density_kg_m3", label: "Neutral atmosphere density" },
] as const;
const FRAMING: { value: Framing; label: string }[] = [
  { value: "earth", label: "Earth and nearby orbits" },
  { value: "all", label: "Entire catalog extent" },
];
const QUALITY: { value: Quality; label: string }[] = [
  { value: "high", label: "High definition" },
  { value: "balanced", label: "Balanced" },
];

type Toggle = "atmosphere" | "ionosphere" | "celestial" | "trails" | "ghosts";

export function LayersPanel(props: {
  open: boolean;
  onClose: () => void;
  headingRef: (node: HTMLHeadingElement | null) => void;
  trigger: RefObject<HTMLElement | null>;
}) {
  const engine = useEngine();
  const mode = useStudio((s) => s.mode);
  const layers = useStudio((s) => s.layers);
  const framing = useStudio((s) => s.framing);
  const quality = useStudio((s) => s.quality);
  const inventory = useStudio((s) => s.inventoryStatus);
  const note = useReadout((r) => r?.environmentNote ?? "Environmental layer off");
  const discovering = useStudio((s) => s.catalogSerial === 0 && s.catalogError === null);
  const failed = useStudio((s) => s.catalogError !== null);
  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    setRefreshing(true);
    try {
      await engine.refresh();
    } finally {
      setRefreshing(false);
    }
  };

  const toggle = (key: Toggle, icon: ReactNode, title: string, description?: string) => (
    <ListRow
      inline
      media={icon}
      title={title}
      {...(description ? { description } : {})}
      control={
        <Switch aria-label={title} checked={layers[key]} onCheckedChange={(checked) => engine.setLayer(key, checked)} />
      }
    />
  );

  return (
    <Panel id="layers-panel" icon={PANEL_ICON.layers} title="Layers and view" label="Layers and view controls" closeLabel="Close layers panel" side="left" {...props}>
      <Segmented label="Objects shown" value={mode} options={MODES} onChange={(next) => engine.setMode(next)} />
      <Disclosure icon={<SlidersHorizontalIcon />} title="Environment and display" defaultOpen>
        <div className="flex flex-col gap-3">
          <SectionHeader level="eyebrow" icon={<EarthIcon aria-hidden />} title="World layers" as="h3" />
          <ListGroup>
            {toggle("atmosphere", <WindIcon />, "Atmosphere")}
            {toggle("ionosphere", <RadioIcon />, "Ionosphere")}
            <ListRow
              inline
              media={<CloudIcon />}
              title="Cloud cover"
              control={
                <ChoiceSelect
                  label="Cloud cover"
                  value={layers.clouds}
                  options={CLOUDS}
                  onChange={(next) => engine.setLayer("clouds", next)}
                />
              }
            />
            <ListRow
              media={<ThermometerIcon />}
              title="Environmental data"
              description={<Swap value={note}>{note}</Swap>}
              control={
                <ChoiceSelect
                  label="Environmental data"
                  className="sm:w-full"
                  value={layers.environment as (typeof ENVIRONMENT)[number]["value"]}
                  options={ENVIRONMENT}
                  onChange={(next) => engine.setLayer("environment", next satisfies RendererLayers["environment"])}
                />
              }
            />
            {toggle("celestial", <SunMoonIcon />, "Sun and Moon", "CesiumJS built-in atmosphere, lighting, Sun and Moon")}
            {toggle("trails", <RouteIcon />, "Orbit trails")}
            {toggle("ghosts", <MapPinnedIcon />, "Last known position")}
          </ListGroup>
          <SectionHeader level="eyebrow" icon={<CameraIcon aria-hidden />} title="View" as="h3" />
          <ListGroup>
            <ListRow
              media={<CameraIcon />}
              title="Camera framing"
              control={
                <ChoiceSelect label="Camera framing" className="sm:w-full" value={framing} options={FRAMING} onChange={(next) => engine.setFraming(next)} />
              }
            />
            <ListRow
              inline
              media={<GaugeIcon />}
              title="Render quality"
              control={
                <ChoiceSelect label="Render quality" value={quality} options={QUALITY} onChange={(next) => engine.setQuality(next)} />
              }
            />
          </ListGroup>
          <Fine>
            The textured clouds and ionosphere shell are illustrative. Environmental data shows supplied samples valid at
            scene time. Above 500 objects, orbit trails show only the focused satellite. They don’t change the detector or
            simulate weather, plasma, or radio propagation.
          </Fine>
        </div>
      </Disclosure>
      <Separator />
      <div className="flex items-center gap-2">
        <StatusLabel tone={failed ? "danger" : discovering ? "live" : "success"} variant="caption" animate={discovering}>
          {inventory}
        </StatusLabel>
        <IconButton label="Refresh artifacts" className="ms-auto" loading={refreshing} disabled={refreshing} onClick={() => void refresh()}>
          <RotateCwIcon />
        </IconButton>
      </div>
    </Panel>
  );
}
