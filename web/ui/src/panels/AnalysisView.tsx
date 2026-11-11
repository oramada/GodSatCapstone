// The orbital analysis workbench, for the focused object in the current window: telemetry,
// time navigation, the ground track, a watchlist kept in this browser, and closest sampled
// approaches screened in a worker. Ported from web/studio/analysis-panel.js.

import {
  Button,
  EmptyState,
  Field,
  IconButton,
  Input,
  ListGroup,
  ListRow,
  ProgressMeter,
  SectionHeader,
  Stagger,
  StatTile,
  StatusLine,
  type StatusLineTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@sam/design-system";
import {
  ActivityIcon,
  ArrowRightIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  CrosshairIcon,
  DownloadIcon,
  EyeIcon,
  MapIcon,
  OrbitIcon,
  RadarIcon,
  SquareIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GroundTrack } from "../charts/GroundTrack";
import { Fine } from "../components/Panel";
import { download, messageOf } from "../engine/api";
import { useEngine, useStudio } from "../engine/context";
import { fixed } from "../engine/format";
import { csvRows, groundTrack, telemetry, timeStep, type ScreenResult } from "../engine/legacy";
import type { Scene } from "../engine/types";

const WATCH_LIMIT = 12;

export function watchKey(scene: Scene): string {
  return `godsat.watch.v1:${String(scene.sequence?.id || scene.source.artifact_id || scene.title)}`;
}

export function readWatch(key: string): string[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(saved) ? saved.filter((x): x is string => typeof x === "string").slice(0, WATCH_LIMIT) : [];
  } catch {
    return [];
  }
}

/** The clock's local step, at most twice a second (telemetry needn't follow every frame). */
function useSlowTime(interval = 500): [number, () => void] {
  const engine = useEngine();
  const [time, setTime] = useState(() => engine.readout.get()?.time ?? 0);
  const last = useRef(0);
  const sync = useCallback(() => {
    last.current = performance.now();
    setTime(engine.readout.get()?.time ?? 0);
  }, [engine]);
  useEffect(
    () =>
      engine.readout.subscribe(() => {
        if (performance.now() - last.current >= interval) sync();
      }),
    [engine, interval, sync],
  );
  return [time, sync];
}

interface Screened extends ScreenResult {
  threshold: number;
  focusId: string;
  scene: Scene;
}

export function AnalysisView() {
  const engine = useEngine();
  const scene = useStudio((s) => s.scene);
  const focusId = useStudio((s) => s.focusId);
  const [time, syncTime] = useSlowTime();
  const objects = useMemo(() => new Map((scene?.objects ?? []).map((o) => [o.id, o])), [scene]);
  const focus = objects.get(focusId);

  // --- Watchlist ---
  const [watched, setWatched] = useState<string[]>([]);
  const [watchStatus, setWatchStatus] = useState("Up to 12 objects per scene source, saved in this browser.");
  const [watchTone, setWatchTone] = useState<StatusLineTone>("");
  const sayWatch = (text: string, tone: StatusLineTone = "") => {
    setWatchStatus(text);
    setWatchTone(tone);
  };
  const key = scene ? watchKey(scene) : null;
  useEffect(() => {
    setWatched(key ? readWatch(key) : []);
  }, [key]);
  const persist = (next: string[]) => {
    setWatched(next);
    if (!key) return;
    try {
      localStorage.setItem(key, JSON.stringify(next));
      sayWatch(`${next.length} watched objects, saved in this browser for this source.`, "ok");
    } catch {
      sayWatch("Watchlist is available this session. Browser storage is unavailable.", "error");
    }
  };
  const addWatch = () => {
    if (!focusId) return;
    if (watched.includes(focusId)) return sayWatch("This object is already watched.");
    if (watched.length >= WATCH_LIMIT) return sayWatch("Watchlist limit reached. Remove an object before adding another.", "error");
    persist([...watched, focusId]);
  };

  // --- Screening ---
  const [threshold, setThreshold] = useState("100");
  const [screenStatus, setScreenStatus] = useState("Choose a scene to start.");
  const [screenTone, setScreenTone] = useState<StatusLineTone>("");
  const [progress, setProgress] = useState(0);
  const sayScreen = useCallback((text: string, tone: StatusLineTone = "") => {
    setScreenStatus(text);
    setScreenTone(tone);
  }, []);
  const [busy, setBusy] = useState(false);
  // Screen catalog and Stop screening swap places; focus that went with the leaving one lands
  // on Screen catalog instead of the page.
  const screenButton = useRef<HTMLButtonElement>(null);
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy && document.activeElement === document.body) screenButton.current?.focus();
    wasBusy.current = busy;
  }, [busy]);
  const [result, setResult] = useState<Screened | null>(null);
  const worker = useRef<Worker | null>(null);
  const generation = useRef(0);
  const busyRef = useRef(false);

  const cancel = useCallback((announce = true) => {
    generation.current += 1;
    if (busyRef.current && announce) sayScreen("Screening stopped.");
    busyRef.current = false;
    setBusy(false);
    worker.current?.terminate();
    worker.current = null;
  }, [sayScreen]);
  useEffect(() => () => cancel(false), [cancel]);

  // --- Time navigation ---
  const [instant, setInstant] = useState("");
  const [timeStatus, setTimeStatus] = useState("");
  const [timeTone, setTimeTone] = useState<StatusLineTone>("");
  const sayTime = (text: string, tone: StatusLineTone = "") => {
    setTimeStatus(text);
    setTimeTone(tone);
  };

  // A new scene (or window) starts the workbench over; a new focus clears its screening.
  const lastScene = useRef<Scene | null>(null);
  useEffect(() => {
    if (!scene) return;
    cancel(false);
    setResult(null);
    if (lastScene.current !== scene) {
      lastScene.current = scene;
      sayScreen(`Ready: ${scene.objects.length.toLocaleString()} objects × ${scene.times.length} saved epochs. Current window only.`);
      setInstant("");
      setTimeStatus(`${scene.times[0] ?? ""} to ${scene.times.at(-1) ?? ""} · current window`);
      setTimeTone("");
    } else {
      sayScreen("Focus changed. Run screening for this object.");
    }
  }, [scene, focusId, cancel, sayScreen]);

  const seek = (local: number) => {
    engine.seekLocal(local);
    syncTime();
  };

  const screen = async () => {
    if (!scene) return;
    cancel(false);
    const limit = Number(threshold);
    if (threshold.trim() === "" || !Number.isFinite(limit) || limit < 0) return sayScreen("Enter a nonnegative separation in km.", "error");
    const focusIndex = scene.objects.findIndex((o) => o.id === focusId);
    if (focusIndex < 0) return;
    setResult(null);
    busyRef.current = true;
    setBusy(true);
    setProgress(0);
    engine.pause();
    sayScreen("Preparing position samples…");
    const run = generation.current;
    const frames = scene.times.length;
    const positions = new Float64Array(scene.objects.length * frames * 3).fill(Number.NaN);
    // Yield while packing large catalogs; a changed source or focus cancels obsolete work.
    for (let j = 0; j < scene.objects.length; j++) {
      const track = scene.objects[j]?.positions_km ?? [];
      for (let k = 0; k < frames; k++) {
        const p = track[k];
        if (p) positions.set(p, (j * frames + k) * 3);
      }
      if (j % 512 === 0) {
        await new Promise(requestAnimationFrame);
        if (run !== generation.current) return;
      }
    }
    const focusSamples = positions.slice(focusIndex * frames * 3, (focusIndex + 1) * frames * 3);
    try {
      const next = new Worker(new URL("../../../studio/screen-worker.js", import.meta.url), { type: "module" });
      worker.current = next;
      next.onerror = () => {
        if (run !== generation.current) return;
        cancel(false);
        sayScreen("Screening worker failed. Reload Studio and try again.", "error");
      };
      next.onmessage = ({ data }: MessageEvent<{ progress?: number; error?: string; result?: ScreenResult }>) => {
        if (run !== generation.current) return;
        // Progress moves the meter only; the spoken line changes when screening starts and ends.
        if (data.progress !== undefined) return setProgress(data.progress);
        cancel(false);
        if (data.error || !data.result) return sayScreen(data.error ?? "Screening returned no result. Try again.", "error");
        const screened = { ...data.result, threshold: limit, focusId, scene };
        setResult(screened);
        sayScreen(
          `${screened.matchingObjects} objects within ${fixed(limit)} km at a saved epoch. Showing ${screened.rows.length}. ${screened.comparisons.toLocaleString()} comparisons, ${screened.unavailableObjects} objects with no shared valid epoch.`,
          "ok",
        );
      };
      sayScreen("Screening saved epochs…");
      next.postMessage({ positions, focus: focusSamples, objects: scene.objects.length, frames, focusIndex, threshold: limit }, [
        positions.buffer,
        focusSamples.buffer,
      ]);
    } catch (error) {
      cancel(false);
      sayScreen(messageOf(error), "error");
    }
  };

  const exportScreen = () => {
    if (!result) return;
    const r = result;
    download(
      "sampled-approaches.csv",
      csvRows([
        ["focus_id", "other_id", "utc", "sampled_distance_km", "valid_epochs", "frame", "source_kind", "scope"],
        ...r.rows.map((h) => [
          r.focusId,
          r.scene.objects[h.objectIndex]?.id,
          r.scene.times[h.index],
          h.distanceKm,
          h.validSamples,
          r.scene.frame,
          r.scene.source.kind,
          "saved epochs only; current window; not collision prediction",
        ]),
      ]),
      "text/csv;charset=utf-8",
    );
  };

  const exportTelemetry = () => {
    if (!scene || !focus) return;
    download(
      "satellite-telemetry.csv",
      csvRows([
        ["object_id", "utc", "frame", "x_km", "y_km", "z_km", "wgs84_lat_deg", "wgs84_lon_deg", "wgs84_alt_km", "frame_speed_km_s", "source_kind"],
        ...scene.times.map((t, k) => {
          const v = telemetry(scene, focus, k);
          return [
            focus.id,
            t,
            scene.frame,
            ...(v?.position ?? ["", "", ""]),
            v?.geodetic?.latitude,
            v?.geodetic?.longitude,
            v?.geodetic?.altitude,
            v?.sampleSpeed,
            scene.source.kind,
          ];
        }),
      ]),
      "text/csv;charset=utf-8",
    );
  };

  const jump = () => {
    if (!scene) return;
    const raw = instant.trim();
    if (!/(Z|[+-]\d\d:\d\d)$/i.test(raw)) return sayTime("Include a UTC offset, for example 2026-11-08T18:56:00Z.", "error");
    const step = timeStep(scene.times, raw);
    if (step === null) return sayTime("Enter a valid instant inside the current window.", "error");
    engine.pause();
    seek(step);
    sayTime(`Jumped to ${new Date(Date.parse(raw)).toISOString()}`);
  };

  const stepBy = (direction: 1 | -1) => {
    if (!scene) return;
    engine.pause();
    const now = engine.readout.get()?.time ?? 0;
    seek(Math.max(0, Math.min(scene.times.length - 1, direction > 0 ? Math.floor(now) + 1 : Math.ceil(now) - 1)));
  };

  const t = scene && focus ? telemetry(scene, focus, time) : null;
  const geo = t?.geodetic ?? null;
  const segments = useMemo(() => (scene ? groundTrack(scene, focus) : []), [scene, focus]);

  if (!scene) return <EmptyState size="compact" icon={<OrbitIcon />} title="No scene open" description="Choose a scene to start." />;

  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="telemetry-title" className="flex flex-col gap-3">
        <SectionHeader inset={false} as="h3" icon={<ActivityIcon />} title={<span id="telemetry-title">Focused satellite telemetry</span>} />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <StatTile variant="inset" size="sm" label="Geocentric radius" value={fixed(t?.radius, 2, " km")} />
          <StatTile variant="inset" size="sm" label="WGS84 altitude" value={fixed(geo?.altitude, 2, " km")} />
          <StatTile variant="inset" size="sm" label="Latitude" value={fixed(geo?.latitude, 3, "°")} />
          <StatTile variant="inset" size="sm" label="Longitude" value={fixed(geo?.longitude, 3, "°")} />
          <StatTile variant="inset" size="sm" label="Sampled frame speed" value={fixed(t?.sampleSpeed, 4, " km/s")} />
        </div>
        <Fine>
          {scene.frame} · speed at preceding saved epoch, in this frame{scene.frame === "ITRS" ? " (Earth-fixed, not inertial)" : ""}.
          Geodetic values require ITRS.
        </Fine>
        <div>
          <Button variant="outline" size="sm" disabled={!focus} onClick={exportTelemetry}>
            <DownloadIcon />
            Export telemetry CSV
          </Button>
        </div>
      </section>

      <section aria-labelledby="time-title" className="flex flex-col gap-3">
        <SectionHeader inset={false} as="h3" icon={<ClockIcon />} title={<span id="time-title">Time navigation</span>} />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => stepBy(-1)}>
            <ChevronLeftIcon />
            Previous sample
          </Button>
          <Button variant="outline" size="sm" onClick={() => stepBy(1)}>
            Next sample
            <ChevronRightIcon />
          </Button>
        </div>
        <Field label="UTC instant, with offset" htmlFor="time-input">
          <div className="flex gap-2">
            <Input
              id="time-input"
              size="sm"
              font="mono"
              spellCheck={false}
              placeholder={scene.times[0] ?? "2026-11-08T18:56:00Z"}
              value={instant}
              onChange={(event) => setInstant(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  jump();
                }
              }}
            />
            <Button size="sm" onClick={jump}>
              <ClockIcon />
              Jump
            </Button>
          </div>
        </Field>
        <StatusLine text={timeStatus} tone={timeTone} />
      </section>

      <section aria-labelledby="track-title" className="flex flex-col gap-3">
        <SectionHeader inset={false} as="h3" icon={<MapIcon />} title={<span id="track-title">Ground track</span>} />
        <GroundTrack segments={segments} current={geo} />
        <Fine>
          {scene.frame === "ITRS"
            ? "WGS84 sub-satellite points at saved epochs. Gaps and dateline crossings are separated. Current window only."
            : "Ground track unavailable: this scene isn’t in ITRS."}
        </Fine>
      </section>

      <section aria-labelledby="watch-title" className="flex flex-col gap-3">
        <SectionHeader
          inset={false}
          as="h3"
          icon={<EyeIcon />}
          title={<span id="watch-title">Watchlist</span>}
          action={
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={!focusId} onClick={addWatch}>
                <EyeIcon />
                Watch selected
              </Button>
              <Button variant="ghost" size="sm" disabled={!watched.length} onClick={() => persist([])}>
                <Trash2Icon />
                Clear
              </Button>
            </div>
          }
        />
        <StatusLine text={watchStatus} tone={watchTone} />
        {watched.length ? (
          <Stagger as={ListGroup}>
            {watched.map((id) => {
              const object = objects.get(id);
              const other = object ? telemetry(scene, object, time) : null;
              const distance = t && other ? Math.hypot(...t.position.map((x, i) => x - (other.position[i] ?? Number.NaN))) : null;
              return (
                <ListRow
                  key={id}
                  variant="item"
                  title={object?.name ?? id}
                  description={object ? (distance === null ? "Position unavailable" : `${fixed(distance)} km from focus`) : "Not in this window"}
                  control={
                    <>
                      <Button variant="ghost" size="sm" disabled={!object} onClick={() => engine.focus(id)}>
                        <CrosshairIcon />
                        Focus
                      </Button>
                      <IconButton
                        label={`Remove ${object?.name ?? id} from watchlist`}
                        onClick={() => persist(watched.filter((x) => x !== id))}
                      >
                        <XIcon />
                      </IconButton>
                    </>
                  }
                />
              );
            })}
          </Stagger>
        ) : (
          <EmptyState size="compact" icon={<EyeIcon />} title="No watched objects yet" description="Add the focused satellite with Watch selected." />
        )}
      </section>

      <section aria-labelledby="screen-title" className="flex flex-col gap-3">
        <SectionHeader inset={false} as="h3" icon={<RadarIcon />} title={<span id="screen-title">Closest sampled approaches</span>} />
        <Fine>
          Compare the focused object with this window’s catalog at saved epochs. This is a discrete screening aid, not a
          continuous closest-approach calculation or collision probability.
        </Fine>
        <Field label="Maximum sampled separation (km)" htmlFor="screen-threshold">
          <Input
            id="screen-threshold"
            type="number"
            size="sm"
            min={0}
            step="any"
            value={threshold}
            onChange={(event) => {
              setThreshold(event.target.value);
              cancel(false);
              setResult(null);
              sayScreen("Threshold changed. Run screening to calculate new results.");
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void screen();
              }
            }}
          />
        </Field>
        <div className="flex flex-wrap gap-2">
          {busy ? (
            <Button variant="outline" size="sm" onClick={() => cancel()}>
              <SquareIcon />
              Stop screening
            </Button>
          ) : (
            <Button ref={screenButton} size="sm" onClick={() => void screen()}>
              <RadarIcon />
              Screen catalog
            </Button>
          )}
          <Button variant="outline" size="sm" disabled={!result} onClick={exportScreen}>
            <DownloadIcon />
            Export CSV
          </Button>
        </div>
        {busy ? (
          <ProgressMeter value={progress} max={1} label="Screening progress" valueText={`${Math.round(progress * 100)}%`} tone="primary" size="sm" className="motion-enter" />
        ) : null}
        <StatusLine text={screenStatus} tone={screenTone} />
        {result && result.rows.length ? (
          <Table height="md" size="compact" label="Closest sampled approaches">
            <TableHeader>
              <TableRow>
                <TableHead>Object</TableHead>
                <TableHead numeric>Minimum sampled separation</TableHead>
                <TableHead>UTC epoch</TableHead>
                <TableHead numeric>Valid epochs</TableHead>
                <TableHead>
                  <span className="sr-only">Go to epoch</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <Stagger as={TableBody} key={`${result.focusId}:${result.threshold}`}>
              {result.rows.map((hit) => (
                <TableRow key={`${hit.objectIndex}:${hit.index}`}>
                  <TableCell>{result.scene.objects[hit.objectIndex]?.name}</TableCell>
                  <TableCell numeric>{fixed(hit.distanceKm, 3, " km")}</TableCell>
                  <TableCell tabular>{result.scene.times[hit.index]}</TableCell>
                  <TableCell numeric>{hit.validSamples}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => seek(hit.index)}>
                      Go to epoch
                      <ArrowRightIcon />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </Stagger>
          </Table>
        ) : null}
      </section>
    </div>
  );
}
