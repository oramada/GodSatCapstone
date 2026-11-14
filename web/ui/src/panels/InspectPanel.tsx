import {
  Badge,
  Button,
  Card,
  ChoiceSelect,
  CodeBlock,
  Disclosure,
  Field,
  Input,
  ListGroup,
  ListRow,
  Reveal,
  SectionHeader,
  Stagger,
  StatTile,
  StatusLabel,
  Swap,
  Text,
} from "@sam/design-system";
import { BracesIcon, RadioTowerIcon, ScrollTextIcon, SearchIcon, TargetIcon } from "lucide-react";
import { type Ref, type RefObject, useMemo, useState } from "react";

import { Fine, Panel } from "../components/Panel";
import { PANEL_ICON } from "../components/icons";
import { TONE } from "../components/tone";
import { useEngine, useReadout, useStudio } from "../engine/context";
import { MISSING, plain, sentence } from "../engine/format";
import { focusMatches, STATE_COPY } from "../engine/studio";
import type { LinkRow } from "../engine/types";

const LINK_FIELDS: { key: keyof Omit<LinkRow, "unavailable" | "inputs">; label: string; digits: number; suffix: string }[] = [
  { key: "elevation_deg", label: "Elevation", digits: 2, suffix: "°" },
  { key: "vacuum_time_ms", label: "Static-range travel time", digits: 3, suffix: " ms" },
  { key: "dry_slant_delay_m", label: "Dry atmospheric delay", digits: 3, suffix: " m" },
  { key: "ionosphere_group_delay_m", label: "Ionospheric group delay", digits: 3, suffix: " m" },
  { key: "uplink_faraday_deg", label: "Uplink Faraday rotation", digits: 3, suffix: "°" },
  { key: "cloud_fraction", label: "Cloud area fraction", digits: 2, suffix: "" },
];

export function InspectPanel({
  detailRef,
  ...props
}: {
  open: boolean;
  onClose: () => void;
  headingRef: (node: HTMLHeadingElement | null) => void;
  trigger: RefObject<HTMLElement | null>;
  detailRef: Ref<HTMLCanvasElement>;
}) {
  return (
    <Panel id="inspect-panel" icon={PANEL_ICON.inspect} title="Inspect satellite" label="Satellite inspection" closeLabel="Close inspection panel" side="right" {...props}>
      <FocusPicker />
      <ObjectCard detailRef={detailRef} />
      <GroundLinks />
      <Provenance />
      <Narrative />
    </Panel>
  );
}

function FocusPicker() {
  const engine = useEngine();
  const objects = useStudio((s) => s.focusObjects);
  const selectedIds = useStudio((s) => s.selectedIds);
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const [selectionOnly, setSelectionOnly] = useState(false);
  const scoped = useMemo(() => selectionOnly && selected.size ? objects.filter((o) => selected.has(o.id)) : objects,
    [selectionOnly, selected, objects]);
  const query = useStudio((s) => s.focusQuery);
  const focusId = useStudio((s) => s.focusId);
  const { count, listed } = useMemo(() => focusMatches(scoped, query, focusId), [scoped, query, focusId]);
  const options = useMemo(() => listed.map((o) => ({ value: o.id, label: o.name })), [listed]);
  return (
    <div className="flex flex-col gap-3">
      {selectedIds.length > 1 ? (
        <Button variant="ghost" size="sm" aria-pressed={selectionOnly} onClick={() => setSelectionOnly(!selectionOnly)}>
          {selectionOnly ? "Search all satellites" : `Search ${selectedIds.length.toLocaleString()} selected satellites`}
        </Button>
      ) : null}
      <Field label="Find satellite" htmlFor="focus-search">
        <Input
          id="focus-search"
          type="search"
          size="sm"
          placeholder="Name or NORAD ID"
          leading={<SearchIcon />}
          value={query}
          onChange={(event) => engine.setFocusQuery(event.target.value)}
        />
      </Field>
      <Field label="Focus object" htmlFor="focus-object" hint={`${count.toLocaleString()} matches · ${listed.length} listed`}>
        <ChoiceSelect
          id="focus-object"
          value={focusId}
          options={options}
          disabled={!options.length}
          onChange={(id) => engine.focus(id)}
          className="sm:w-full"
        />
      </Field>
      <Button variant="ghost" size="sm" disabled={!focusId} onClick={() => engine.followSatellite()}>
        <TargetIcon />
        Zoom to satellite
      </Button>
    </div>
  );
}

function ObjectCard({ detailRef }: { detailRef: Ref<HTMLCanvasElement> }) {
  const object = useReadout((r) => r?.object ?? null);
  const state = useReadout((r) => r?.track.state ?? "unknown");
  const age = useReadout((r) => r?.track.age ?? null);
  const caption = useReadout((r) => r?.stateCaption ?? "Choose a scene to inspect its observation history.");
  const custody = useReadout((r) => r?.custody ?? null);
  const targets = useReadout((r) => r?.targets ?? null);
  const attitude = useReadout(
    (r) => r?.attitudeCaption ?? "Spacecraft shape and Earth-pointing pose are generic illustrations, not measured geometry or attitude.",
  );
  const loaded = useReadout((r) => r !== null);
  // A new satellite's name arrives, then its details settle in after it (rules 1 and 6). The
  // canvas stays put: the detail renderer draws into it.
  const key = object?.id ?? (loaded ? "none" : "loading");
  return (
    <Card variant="outline" className="flex flex-col gap-3">
      <SectionHeader
        key={`head:${key}`}
        as="h3"
        inset={false}
        title={object?.name ?? (loaded ? "No target" : "No object selected")}
        description={object ? `${sentence(object.kind)} · ${object.id}` : "Choose a spatial product"}
        className="motion-enter"
      />
      <div data-theme="dark" className="relative aspect-video overflow-hidden rounded-row bg-canvas">
        <canvas ref={detailRef} aria-label="Spacecraft orientation and last observed track" className="block size-full" />
        <Reveal open={state === "lost"} from="center" className="absolute inset-0 grid place-items-center">
          <div className="flex flex-col items-center gap-1">
            <Badge variant="error" size="lg">
              Track lost
            </Badge>
            <Badge variant="secondary">No current observation</Badge>
          </div>
        </Reveal>
      </div>
      <Stagger key={`body:${key}`} step="settle" className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <StatusLabel tone={TONE[state]}>{loaded ? STATE_COPY[state].name : "Loading"}</StatusLabel>
          <Text as="span" size="xs" tone="muted" numeric>
            {age === null ? "No known sighting" : age === 0 ? "Just now" : `${Math.round(age)}s ago`}
          </Text>
        </div>
        <Text pretty>{caption}</Text>
        <div className="grid grid-cols-2 gap-2">
          <StatTile variant="inset" size="sm" label="In custody" value={custody ?? MISSING} />
          <StatTile variant="inset" size="sm" label="Targets" value={targets ?? MISSING} />
        </div>
        <Fine>{attitude}</Fine>
      </Stagger>
    </Card>
  );
}

function GroundLinks() {
  const engine = useEngine();
  const link = useStudio((s) => s.link);
  const row = useReadout((r) => r?.linkRow ?? null);
  const index = useReadout((r) => r?.index ?? 0);
  const config = link.config;
  if (!config) return null;
  const stations = config.stations.map((s) => ({ value: s.id, label: s.name }));
  const status =
    link.message ||
    (row && link.result
      ? `Sample epoch ${link.result.times[index] ?? ""}. ${Object.values(row.unavailable).join(". ")}`
      : "No propagation estimate.");
  const inputs = JSON.stringify(
    row && link.result ? { inputs: row.inputs, station: link.result.station, limits: link.result.limits } : { status: link.message },
    null,
    2,
  );
  return (
    <section aria-labelledby="link-heading" className="flex flex-col gap-3">
      <SectionHeader
        id="link-heading"
        level="eyebrow"
        as="h3"
        icon={<RadioTowerIcon />}
        title="Ground radio path · snapshot estimates"
        action={
          <Text as="span" size="xs" tone="muted" numeric>
            {(config.frequency_hz / 1e9).toFixed(5)} GHz
          </Text>
        }
      />
      <Field label="Station" htmlFor="link-station">
        <ChoiceSelect
          id="link-station"
          value={link.stationId}
          options={stations}
          onChange={(id) => engine.setStation(id)}
          className="sm:w-full"
        />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        {LINK_FIELDS.map((field) => (
          <StatTile
            key={field.key}
            variant="inset"
            size="sm"
            label={field.label}
            value={plain(row?.[field.key], field.digits, field.suffix)}
          />
        ))}
      </div>
      <Fine>{status}</Fine>
      <Disclosure variant="quiet" icon={<BracesIcon />} title="Propagation inputs and model limits">
        <CodeBlock text={inputs} label="Propagation inputs and model limits" copy />
      </Disclosure>
    </section>
  );
}

function Provenance() {
  const provenance = useStudio((s) => s.provenance);
  if (!provenance) return null;
  return (
    <Disclosure variant="quiet" icon={<ScrollTextIcon />} title="Scene provenance and scientific limits">
      <CodeBlock text={provenance} label="Scene provenance and scientific limits" height="md" copy />
    </Disclosure>
  );
}

function Narrative() {
  const step = useReadout((r) => r?.stepNumber ?? "01");
  const title = useReadout((r) => r?.stepTitle ?? "Explore the selected product");
  const body = useReadout((r) => r?.stepBody ?? "Source-specific state appears here when a spatial product is loaded.");
  return (
    <ListGroup>
      <ListRow
        variant="item"
        inline
        titleAs="p"
        media={
          <Badge variant="secondary">
            <Swap value={step}>{step}</Swap>
          </Badge>
        }
        title={<Swap value={title}>{title}</Swap>}
        description={body}
      />
    </ListGroup>
  );
}
