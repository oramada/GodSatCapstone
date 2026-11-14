// The studio engine: the scene, the clock, playback, the render loop and the renderer.
// Ported from the vanilla window (web/studio/app.js) with its behaviour kept: windowed
// sequences seek and prefetch, stale requests are dropped by serial, links are recomputed
// for the focused object and station, the catalog is re-read every 15 s while visible.
//
// React never drives a frame. It reads two stores: `state` (changes on an action: a scene,
// the focus, a layer) and `readout` (the clock's words and numbers, at most every 100 ms).

import { download, getJson, getScene, isAbort, messageOf } from "./api";
import {
  CesiumObservatory,
  computeBackend,
  computeFrame,
  initializeCompute,
  prepareScene,
  sceneCandidate,
  trackState,
  trackStates,
  WindowSequence,
  type Observatory,
  type RendererLayers,
} from "./legacy";
import { readGlobePalette } from "./palette";
import { Store } from "./store";
import type { Artifact, Catalog, GroundLinks, LinkResult, LinkRow, Scene, SceneObject, TrackState, TrackStateName } from "./types";

export type Mode = "single" | "system";
export type CameraMode = "orbit" | "free";
export type Framing = "earth" | "all";
export type Quality = "high" | "balanced";
export type Speed = "0.1" | "0.35" | "1" | "3";
export type CloudCover = RendererLayers["clouds"];

export interface SourceOption {
  value: string;
  label: string;
  title?: string;
}

export interface LinkState {
  config: GroundLinks | null;
  stationId: string;
  result: LinkResult | null;
  message: string;
}

export interface StudioState {
  started: boolean;
  scene: Scene | null;
  /** The source on screen. */
  activeSource: string;
  /** The source picked in the menu: the active one, or one being opened. */
  sourceValue: string;
  sourceOptions: SourceOption[];
  /** The globe's overlay line while something loads; null when the globe is showing. */
  loading: string | null;
  rendererError: string | null;
  playing: boolean;
  speed: Speed;
  mode: Mode;
  layers: RendererLayers;
  framing: Framing;
  cameraMode: CameraMode;
  tracking: boolean;
  boxSelection: boolean;
  selectedIds: string[];
  quality: Quality;
  focusId: string;
  focusQuery: string;
  /** Every object a person can focus on (no stations or sensors). */
  focusObjects: SceneObject[];
  /** Whether the person picked the focus (on the globe or in Inspect): the selection chip shows. */
  selectedByUser: boolean;
  computeBackend: string;
  framePerformance: string;
  artifacts: Artifact[];
  catalogTruncated: boolean;
  /** Bumped on every catalog read, so views that read an artifact read it again. */
  catalogSerial: number;
  /** Why the last catalog read failed, or null once one succeeds. Discovery has ended either way. */
  catalogError: string | null;
  inventoryStatus: string;
  /** One state per saved epoch for the focused object, or null for a windowed sequence. */
  marks: TrackStateName[] | null;
  scrubMax: number;
  sequenceStatus: string;
  provenance: string;
  link: LinkState;
}

export interface Readout {
  /** The local step inside the current window (fractional). */
  time: number;
  /** The step across the whole sequence. */
  global: number;
  elapsed: string;
  utc: string;
  duration: string;
  stepNumber: string;
  index: number;
  track: TrackState;
  object: SceneObject | null;
  custody: number | null;
  targets: number;
  stepTitle: string;
  stepBody: string;
  stateCaption: string;
  linkRow: LinkRow | null;
  attitudeCaption: string;
  environmentNote: string;
}

const LAYERS_DEFAULT: RendererLayers = {
  atmosphere: true,
  ionosphere: false,
  celestial: true,
  trails: false,
  ghosts: false,
  clouds: "clear",
  environment: "none",
};

const DEMO: SourceOption = { value: "demo", label: "Illustrative demonstration" };
const GLOBE_LOADING = "Loading globe textures and engine assets…";
/** How long focus must rest on an object before its ground links are asked for. */
export const LINK_DEBOUNCE_MS = 250;

export const STATE_COPY: Record<TrackStateName, { name: string; title: string; body: string }> = {
  observed: {
    name: "Observed now",
    title: "A fresh observation",
    body: "The sensor sees this object. Its track has just been updated.",
  },
  stale: {
    name: "Last sighting",
    title: "No new sighting",
    body: "The object keeps moving. The amber marker stays at the last observed position while the track ages.",
  },
  lost: {
    name: "Track lost",
    title: "The track expires",
    body: "The object is still in space, but its last sighting is older than the custody window. The tracker no longer has a current track.",
  },
  unknown: {
    name: "Status unknown",
    title: "Geometry without observation history",
    body: "This source contains positions but no observation record at this step. We can’t tell whether the tracker sees the object.",
  },
  unavailable: {
    name: "Position unavailable",
    title: "No position at this step",
    body: "The source has no valid position for this object. We leave the gap visible rather than inventing a trajectory.",
  },
};

const PROVENANCE_DISPLAY =
  "Earth texture and cloud pattern are static visual assets, not observations at the scene epoch. Ionosphere is qualitative. Cesium converts source frames for display. Spacecraft sizes are exaggerated. No antenna or propagation physics is inferred.";

const pad = (value: number) => String(Math.max(0, Math.floor(value))).padStart(2, "0");

function sourceLabel(artifact: Artifact): string {
  return artifact.path.split("/").slice(-2).join(" / ");
}

export function sourceKindLabel(kind: string | undefined): string {
  if (!kind) return "";
  return kind === "illustrative" ? "Illustrative" : kind === "modeled" ? "Modeled" : "Saved data";
}

/** The objects listed for a query: up to 200 matches, and the focused one even past them. */
export function focusMatches(objects: SceneObject[], query: string, focusId: string) {
  const needle = query.trim().toLowerCase();
  const matches = needle ? objects.filter((o) => `${o.name} ${o.id}`.toLowerCase().includes(needle)) : objects;
  const listed = matches.slice(0, 200);
  const current = objects.find((o) => o.id === focusId);
  if (current && !listed.includes(current)) listed.unshift(current);
  return { count: matches.length, listed };
}

export class StudioEngine {
  readonly state: Store<StudioState>;
  readonly readout: Store<Readout | null>;
  /** Something went wrong that the person should read (a toast). */
  onNotice: (message: string) => void = () => {};

  private view: Observatory | null = null;
  private globe: HTMLElement | null = null;
  private time = 0;
  private previous = 0;
  private sequence: WindowSequence | null = null;
  private sceneRequest = 0;
  private windowRequest = 0;
  private sceneLoading = false;
  private windowLoading = false;
  /** The scene download in flight; null once it lands or fails. */
  private sceneController: AbortController | null = null;
  /** The open artifact's modified time when it was installed (null for the demonstration). */
  private currentModified: number | null = null;
  /** Catalog reads in flight, so the timer doesn't stack them. */
  private refreshing = 0;
  /** Failed catalog reads in a row; only the first of a streak raises a toast. */
  private catalogFailures = 0;
  /** The renderer reported a failure (an asset, a model): stop waiting for it to be ready. */
  private rendererFailed = false;
  private linkSerial = 0;
  private linkController: AbortController | null = null;
  private linkTimer = 0;
  private frame = 0;
  private refreshTimer = 0;
  private lastPaint = 0;
  private lastReadout = 0;
  private performanceStart = 0;
  private performanceDraws = 0;
  private frameDurations: number[] = [];
  private run = 0;
  private readonly listeners: [string, EventListener][] = [];

  constructor() {
    this.state = new Store<StudioState>({
      started: false,
      scene: null,
      activeSource: "demo",
      sourceValue: "demo",
      sourceOptions: [DEMO],
      loading: "Preparing scene…",
      rendererError: null,
      playing: false,
      speed: "0.35",
      mode: "system",
      layers: LAYERS_DEFAULT,
      framing: "earth",
      cameraMode: "orbit",
      tracking: false,
      boxSelection: false,
      selectedIds: [],
      quality: "high",
      focusId: "",
      focusQuery: "",
      focusObjects: [],
      selectedByUser: false,
      computeBackend: "Loading compute core",
      framePerformance: "",
      artifacts: [],
      catalogTruncated: false,
      catalogSerial: 0,
      catalogError: null,
      inventoryStatus: "Discovering artifacts…",
      marks: null,
      scrubMax: 0,
      sequenceStatus: "",
      provenance: "",
      link: { config: null, stationId: "", result: null, message: "" },
    });
    this.readout = new Store<Readout | null>(null);
  }

  private get s(): StudioState {
    return this.state.get();
  }

  private get scene(): Scene | null {
    return this.s.scene;
  }

  private globalTime(): number {
    return this.time + (this.scene?.sequence?.offset || 0);
  }

  private stale(run: number): boolean {
    return run !== this.run;
  }

  /** Mounts the renderer and opens the first scene. `stop` undoes it; `start` may run again. */
  async start(globe: HTMLElement, detail: HTMLCanvasElement, credits: HTMLElement): Promise<void> {
    this.stop();
    const run = this.run;
    this.state.set({ started: true, rendererError: null, tracking: false, boxSelection: false });
    this.globe = globe;
    this.rendererFailed = false;
    this.listen(globe, "renderererror", (event) => {
      this.rendererFailed = true;
      this.onNotice(String((event as CustomEvent).detail));
    });
    this.listen(globe, "objectselected", (event) => this.focus(String((event as CustomEvent).detail)));
    this.listen(globe, "satelliteselection", (event) => {
      const { ids, primary, zoom } = (event as CustomEvent<{ ids: string[]; primary?: string; zoom: boolean }>).detail;
      this.selectSatellites(ids, primary);
      if (zoom && primary) this.followSatellite();
    });
    await initializeCompute();
    if (this.stale(run)) return;
    await this.refresh();
    if (this.stale(run)) return;
    try {
      this.view = new CesiumObservatory(globe, detail, { credits, palette: readGlobePalette() });
      this.view.setQuality(this.s.quality);
      this.view.setCameraMode(this.s.cameraMode);
      this.view.framing = this.s.framing;
    } catch (error) {
      this.view = null;
      // The stage says this in place of the globe; a toast on top would say it twice.
      console.error("GoDSAT renderer unavailable:", error);
      this.state.set({ rendererError: "Check that WebGL is enabled, then reload Studio." });
    }
    const options = this.s.sourceOptions;
    const initial =
      options.find((o) => /scene-sequence\.json$/.test(o.label)) ?? options.find((o) => /(?:\/| \/ )(scene|replay)\.json$/.test(o.label));
    await this.loadScene(initial?.value ?? "demo");
    if (this.stale(run)) return;
    this.frame = requestAnimationFrame(this.render);
    this.refreshTimer = window.setInterval(() => {
      if (!document.hidden && this.refreshing === 0) void this.refresh(true);
    }, 15000);
  }

  /** Stops the loop and the timers, drops in-flight work and releases the renderer. */
  stop(): void {
    ++this.run;
    ++this.sceneRequest;
    ++this.windowRequest;
    ++this.linkSerial;
    cancelAnimationFrame(this.frame);
    clearInterval(this.refreshTimer);
    clearTimeout(this.linkTimer);
    this.sceneController?.abort();
    this.sceneController = null;
    this.linkController?.abort();
    this.sequence?.clear();
    this.sequence = null;
    for (const [type, listener] of this.listeners.splice(0)) this.globe?.removeEventListener(type, listener);
    this.view?.destroy();
    this.view = null;
    this.globe = null;
    this.sceneLoading = this.windowLoading = false;
    this.performanceStart = this.performanceDraws = 0;
    this.frameDurations = [];
    if (this.s.started) this.state.set({ started: false });
  }

  private listen(target: HTMLElement, type: string, listener: EventListener) {
    target.addEventListener(type, listener);
    this.listeners.push([type, listener]);
  }

  // --- Sources and scenes -------------------------------------------------------------------

  private loadSceneUrl(value: string): string {
    return value === "demo"
      ? `/api/studio/scene?demo=${encodeURIComponent(this.s.mode)}`
      : `/api/studio/scene?id=${encodeURIComponent(value)}`;
  }

  async loadScene(value = "demo", preserve = false): Promise<void> {
    const before = this.globalTime();
    const request = ++this.sceneRequest;
    ++this.windowRequest;
    // A superseded download (up to 64 MB) stops here rather than finishing in the background.
    this.sceneController?.abort();
    const controller = new AbortController();
    this.sceneController = controller;
    this.windowLoading = false;
    this.sceneLoading = true;
    this.state.set({ loading: "Preparing scene…", sourceValue: value });
    let sequence: WindowSequence | null = null;
    try {
      const next = await getScene(this.loadSceneUrl(value), controller.signal);
      if (request !== this.sceneRequest) return;
      if (next.sequence) {
        const player = new WindowSequence(next, (id, index, signal) =>
          getScene(`/api/studio/window?id=${encodeURIComponent(id)}&index=${index}`, signal),
        );
        controller.signal.addEventListener("abort", () => player.clear(), { once: true });
        sequence = player;
      }
      const selected = sequence && preserve ? await sequence.seek(before) : { scene: next, local: preserve ? this.time : 0 };
      if (request !== this.sceneRequest) return;
      this.sceneController = null;
      this.sequence?.clear();
      this.sequence = sequence;
      this.installScene(selected.scene, value, preserve, false, selected.local);
    } catch (error) {
      if (request !== this.sceneRequest) return;
      this.sceneController = null;
      if (sequence !== this.sequence) sequence?.clear();
      this.sceneLoading = false;
      this.state.set({ loading: null, sourceValue: this.s.activeSource });
      if (!isAbort(error)) this.onNotice(messageOf(error));
    }
  }

  private installScene(next: Scene, value: string, preserve: boolean, keepCamera: boolean, local: number | null) {
    const old = this.s.focusId;
    const validIds = new Set(next.objects.filter((o) => o.kind !== "station" && o.kind !== "sensor").map((o) => o.id));
    const selectedIds = keepCamera ? this.s.selectedIds.filter((id) => validIds.has(id)) : [];
    if (this.view) this.view.selectedByUser = selectedIds.length > 0;
    prepareScene(next);
    let playing = this.s.playing;
    if (!preserve) {
      this.time = 0;
      playing = false;
    }
    if (local !== null) this.time = local;
    this.time = Math.min(this.time, next.times.length - 1);
    const focusObjects = next.objects.filter((o) => !["station", "sensor"].includes(o.kind));
    const focusId = focusObjects.some((o) => o.id === old)
      ? old
      : (focusMatches(focusObjects, this.s.focusQuery, "").listed[0]?.id ?? next.objects[0]?.id ?? "");
    const tracking = keepCamera && focusId === old && this.s.tracking;
    if (!tracking && this.s.tracking) this.view?.stopFollowing();
    this.view?.setSelection(selectedIds);
    this.view?.setScene(next, focusId, keepCamera);
    if (this.view) {
      this.view.mode = this.s.mode;
      if (!keepCamera) this.view.reset();
    }
    this.sceneLoading = false;
    this.state.set({
      scene: next,
      activeSource: value,
      sourceValue: value,
      sourceOptions: this.withOpened(this.s.sourceOptions, value),
      playing,
      selectedByUser: selectedIds.length > 0,
      selectedIds,
      tracking,
      computeBackend: computeBackend(),
      focusObjects,
      focusId,
      scrubMax: next.sequence ? next.sequence.total_frames - 1 : next.times.length - 1,
      sequenceStatus: next.sequence ? `Window ${next.sequence.index + 1} of ${next.sequence.windows.length}` : "",
      provenance: JSON.stringify(
        {
          source: next.source,
          frame: next.frame,
          units: next.units,
          custody_seconds: next.custody_seconds,
          warnings: next.warnings,
          environment: next.environment?.sources || [],
          celestial: "CesiumJS built-in celestial rendering at scene UTC",
          renderer: "CesiumJS",
          display: PROVENANCE_DISPLAY,
        },
        null,
        2,
      ),
      loading: this.view?.readyToDisplay === false && !this.rendererFailed ? GLOBE_LOADING : null,
      marks: this.marksFor(next, focusId),
    });
    this.currentModified = value === "demo" ? null : (this.s.artifacts.find((a) => a.id === value)?.modified ?? null);
    this.updateReadout();
    this.sequence?.prefetch(this.globalTime());
    this.refreshLinks();
  }

  /** Keeps a source that is open in the menu even when the catalog no longer lists it. */
  private withOpened(options: SourceOption[], value: string): SourceOption[] {
    if (options.some((o) => o.value === value)) return options;
    const artifact = this.s.artifacts.find((a) => a.id === value);
    return [...options, { value, label: artifact?.path ?? value }];
  }

  private async seekWindow(global: number): Promise<void> {
    const player = this.sequence;
    const scene = this.scene;
    if (!player || !scene?.sequence) return;
    const { index, local } = player.position(global);
    const request = ++this.windowRequest;
    if (scene.sequence.index === index) {
      player.current = index;
      this.time = local;
      // Back inside the window on screen: an earlier window load is moot (its own finally won't
      // run as the current request), but a scene still opening keeps its loading state.
      if (this.windowLoading) this.endWindowLoad();
      return;
    }
    this.windowLoading = true;
    this.sceneLoading = true;
    this.state.set({ loading: "Loading next time window…" });
    try {
      const result = await player.seek(global);
      if (request !== this.windowRequest || this.sequence !== player || this.sceneController) return;
      this.installScene(result.scene, this.s.activeSource, true, true, result.local);
    } catch (error) {
      if (request === this.windowRequest && !isAbort(error)) {
        this.state.set({ playing: false });
        this.onNotice(messageOf(error));
      }
    } finally {
      if (request === this.windowRequest) this.endWindowLoad();
    }
  }

  /** A window load is over; the loading state clears unless a scene is still opening. */
  private endWindowLoad(): void {
    this.windowLoading = false;
    if (this.sceneController) return;
    this.sceneLoading = false;
    this.state.set({ loading: null });
  }

  /**
   * Re-reads the catalog: the source menu, the library, and a changed open scene. `background`
   * is the 15 s timer: its failures toast once per streak, not on every tick.
   */
  async refresh(background = false): Promise<void> {
    const run = this.run;
    ++this.refreshing;
    try {
      const data = await getJson<Catalog>("/api/studio/catalog");
      if (this.stale(run)) return;
      this.catalogFailures = 0;
      const artifacts = data.artifacts;
      const active = this.s.activeSource;
      const candidates = artifacts.filter((a) => a.local && sceneCandidate(a));
      const opened = artifacts.find((a) => a.id === active);
      if (opened && !candidates.some((a) => a.id === opened.id)) candidates.unshift(opened);
      const options: SourceOption[] = [DEMO, ...candidates.map((a) => ({ value: a.id, label: sourceLabel(a), title: a.path }))];
      this.state.set({
        artifacts,
        catalogTruncated: !!data.truncated,
        catalogSerial: this.s.catalogSerial + 1,
        catalogError: null,
        inventoryStatus: `${artifacts.length.toLocaleString()} local artifacts${data.truncated ? " (limited)" : ""}`,
        sourceOptions: this.withOpened(options, active),
      });
      // currentModified belongs to the scene on screen (set when it was installed). While another
      // source is opening, the scene on screen is about to go: leave it be.
      if (this.s.sourceValue !== active) return;
      const chosen = artifacts.find((a) => a.id === active);
      if (chosen && this.currentModified !== null && chosen.modified !== this.currentModified) {
        this.currentModified = chosen.modified;
        await this.loadScene(active, true);
      } else {
        this.currentModified = active === "demo" ? null : (chosen?.modified ?? null);
      }
    } catch (error) {
      if (this.stale(run)) return;
      const message = messageOf(error);
      this.state.set({ catalogError: message, inventoryStatus: "Couldn't read local artifacts" });
      if (!background || this.catalogFailures === 0) this.onNotice(message);
      ++this.catalogFailures;
    } finally {
      --this.refreshing;
    }
  }

  setSource(value: string): void {
    void this.loadScene(value);
  }

  /** Opens an artifact as the scene, adding it to the menu if the catalog didn't list it. */
  openScene(id: string): void {
    this.state.set({ sourceOptions: this.withOpened(this.s.sourceOptions, id) });
    void this.loadScene(id);
  }

  exportScene(): void {
    const scene = this.scene;
    if (!scene) return;
    // Everything the scene carries except the service's Sun/Moon ephemeris, unindented: a 64 MB
    // scene pretty-printed would hold the tab for seconds.
    const { celestial: _ephemeris, ...rest } = scene as Scene & { celestial?: unknown };
    download("godsat-scene.json", JSON.stringify(rest), "application/json");
  }

  // --- Playback -----------------------------------------------------------------------------

  togglePlay(): void {
    const scene = this.scene;
    if (!scene) return;
    const end = (this.sequence?.meta.total_frames || scene.times.length) - 1;
    if (this.globalTime() >= end) {
      if (this.sequence) void this.seekWindow(0);
      else this.time = 0;
    }
    this.state.set({ playing: !this.s.playing });
  }

  pause(): void {
    if (this.s.playing) this.state.set({ playing: false });
  }

  setSpeed(speed: Speed): void {
    this.state.set({ speed });
  }

  /** Moves the clock to a step across the whole sequence (the scrubber). */
  scrub(target: number): void {
    if (!this.scene) return;
    if (this.sequence) void this.seekWindow(target);
    else this.time = target;
    this.updateReadout();
  }

  /** Moves the clock to a step inside the current window (analysis: a sample, an epoch). */
  seekLocal(local: number): void {
    if (!this.scene) return;
    this.time = Math.max(0, Math.min(local, this.scene.times.length - 1));
    this.updateReadout();
  }

  // --- View ---------------------------------------------------------------------------------

  setMode(mode: Mode): void {
    if (mode === this.s.mode) return;
    this.state.set({ mode, tracking: false });
    if (this.view) {
      this.view.mode = mode;
      this.view.reset();
    }
    if (this.s.sourceValue === "demo") void this.loadScene();
  }

  setLayer<K extends keyof RendererLayers>(key: K, value: RendererLayers[K]): void {
    this.state.set({ layers: { ...this.s.layers, [key]: value } });
  }

  setFraming(framing: Framing): void {
    this.state.set({ framing, tracking: false });
    if (this.view) {
      this.view.framing = framing;
      this.view.reset();
    }
  }

  setQuality(quality: Quality): void {
    this.state.set({ quality });
    this.view?.setQuality(quality);
  }

  setCameraMode(cameraMode: CameraMode): void {
    this.view?.setCameraMode(cameraMode);
    this.state.set({ cameraMode, tracking: cameraMode === "orbit" && this.s.tracking });
  }

  lookAtSun(): void {
    if (!this.scene || !this.view) return;
    if (!this.s.layers.celestial) this.setLayer("celestial", true);
    this.view.lookAtSun();
    this.state.set({ tracking: false });
  }

  resetView(): void {
    this.view?.reset();
    this.state.set({ tracking: false });
  }

  followSatellite(): void {
    if (!this.view || !this.s.focusObjects.some((o) => o.id === this.s.focusId)) return;
    const previous = this.s.cameraMode;
    if (previous === "free") this.view.setCameraMode("orbit");
    if (this.view.followSatellite(this.s.focusId)) {
      this.state.set({ tracking: true, cameraMode: "orbit" });
    } else {
      if (previous === "free") this.view.setCameraMode(previous);
      this.onNotice("This satellite has no position at the current scene time.");
    }
  }

  zoomSatellite(factor: number): void {
    this.view?.zoomSatellite(factor);
  }

  setBoxSelection(boxSelection: boolean): void {
    this.view?.setBoxSelection(boxSelection);
    this.state.set({ boxSelection });
  }

  selectSatellites(selectedIds: string[], primary?: string): void {
    this.view?.setSelection(selectedIds);
    this.state.set({ selectedIds, selectedByUser: selectedIds.length > 0 });
    if (primary) this.focus(primary);
    else if (this.view) this.view.selectedByUser = false;
  }

  // --- Focus --------------------------------------------------------------------------------

  setFocusQuery(focusQuery: string): void {
    this.state.set({ focusQuery });
  }

  /** Focuses an object, as a person's choice (the selection chip shows). Stations and sensors can't be focused. */
  focus(id: string): void {
    const scene = this.scene;
    if (!scene || !this.s.focusObjects.some((o) => o.id === id)) return;
    if (this.s.tracking && id !== this.s.focusId) {
      this.view?.stopFollowing();
      this.state.set({ tracking: false });
    }
    if (!this.s.selectedIds.includes(id)) {
      this.view?.setSelection([id]);
      this.state.set({ selectedIds: [id] });
    }
    if (this.view) this.view.selectedByUser = true;
    this.state.set({ focusId: id, selectedByUser: true, marks: this.marksFor(scene, id) });
    this.view?.setFocus(id);
    this.updateReadout();
    this.refreshLinks(LINK_DEBOUNCE_MS);
  }

  private marksFor(scene: Scene, focusId: string): TrackStateName[] | null {
    if (scene.sequence) return null;
    return trackStates(scene, focusId).map((track) => track.state);
  }

  // --- Ground links -------------------------------------------------------------------------

  setStation(stationId: string): void {
    this.state.set({ link: { ...this.s.link, stationId } });
    this.refreshLinks();
  }

  /**
   * Shows the focused object's link state and asks the service for its estimates. `delay` debounces
   * rapid focus changes: the service evaluates one request at a time, so clicking through
   * satellites asks only for the one focus rests on.
   */
  private refreshLinks(delay = 0): void {
    const serial = ++this.linkSerial;
    clearTimeout(this.linkTimer);
    this.linkController?.abort();
    this.linkController = null;
    const scene = this.scene;
    const config = scene?.ground_links ?? null;
    if (!scene || !config) {
      this.state.set({ link: { config: null, stationId: "", result: null, message: "" } });
      if (this.view) this.view.station = null;
      this.updateReadout();
      return;
    }
    const wanted = this.s.link.stationId;
    const stationId = config.stations.some((s) => s.id === wanted) ? wanted : (config.stations[0]?.id ?? "");
    if (this.view) this.view.station = stationId || null;
    const artifactId = scene.source.artifact_id;
    this.state.set({
      link: {
        config,
        stationId,
        result: null,
        message: artifactId
          ? "Calculating propagation estimates…"
          : "Save this scene to a local artifact to calculate propagation estimates.",
      },
    });
    this.updateReadout();
    if (!artifactId) return;
    if (delay > 0) this.linkTimer = window.setTimeout(() => void this.fetchLinks(serial, scene, artifactId, stationId), delay);
    else void this.fetchLinks(serial, scene, artifactId, stationId);
  }

  private async fetchLinks(serial: number, scene: Scene, artifactId: string, stationId: string): Promise<void> {
    if (serial !== this.linkSerial || this.scene !== scene) return;
    const controller = new AbortController();
    this.linkController = controller;
    try {
      const data = await getJson<LinkResult>(
        `/api/studio/links?id=${encodeURIComponent(artifactId)}&window=${scene.sequence?.index || 0}&object=${encodeURIComponent(this.s.focusId)}&station=${encodeURIComponent(stationId)}`,
        controller.signal,
      );
      if (serial !== this.linkSerial || this.scene !== scene) return;
      if (data.scene_sha256 !== scene.source.sha256) throw new Error("Scene changed during calculation. Reload the source.");
      this.state.set({ link: { ...this.s.link, result: data, message: "" } });
    } catch (error) {
      if (serial === this.linkSerial && !isAbort(error)) this.state.set({ link: { ...this.s.link, message: messageOf(error) } });
    }
    this.updateReadout();
  }

  // --- The clock's words --------------------------------------------------------------------

  private updateReadout(): void {
    const scene = this.scene;
    if (!scene) return;
    const time = this.time;
    // The compute core's frame for this instant (a no-op when the render loop already made it), so
    // custody below reads its states instead of walking every object's history in JavaScript.
    computeFrame(scene, time);
    const last = scene.times.length - 1;
    const i = Math.min(Math.floor(time), last);
    const next = Math.min(i + 1, last);
    const at = (k: number) => Date.parse(scene.times[k] ?? "");
    const instant = at(i) + (at(next) - at(i)) * (time - i);
    const start = Date.parse(scene.sequence?.start || scene.times[0] || "");
    const end = Date.parse(scene.sequence?.end || scene.times.at(-1) || "");
    const seconds = (instant - start) / 1000;
    const minutes = (end - start) / 60000;
    const { focusId, focusObjects, link } = this.s;
    const track = trackState(scene, focusId, time);
    const object = scene.objects.find((o) => o.id === focusId) ?? null;
    const copy = STATE_COPY[track.state];
    const global = this.globalTime();
    this.readout.replace({
      time,
      global,
      elapsed: `${pad(seconds / 60)}:${pad(seconds % 60)}`,
      utc: Number.isFinite(instant) ? new Date(instant).toISOString().replace("T", " ").replace("Z", " UTC") : "UTC",
      duration: Number.isFinite(minutes) ? `${minutes.toFixed(minutes % 1 ? 1 : 0)} minutes` : "",
      stepNumber: String(Math.floor(global) + 1).padStart(2, "0"),
      index: i,
      track,
      object,
      custody: scene.observations?.[i]
        ? focusObjects.filter((o) => ["observed", "stale"].includes(trackState(scene, o.id, time).state)).length
        : null,
      targets: focusObjects.length,
      stepTitle: copy.title,
      stepBody: scene.observations?.[i]?.cause || copy.body,
      stateCaption: copy.body,
      linkRow: link.result?.rows[i] ?? null,
      attitudeCaption: this.view?.detail.caption || "Spacecraft shape and Earth-pointing pose are generic illustrations, not measured geometry or attitude.",
      environmentNote: this.view?.environmentMessage || "Environmental layer off",
    });
  }

  private readonly render = (ts: number): void => {
    this.frame = requestAnimationFrame(this.render);
    if (ts - this.lastPaint < 16) return;
    this.lastPaint = ts;
    const frameStart = performance.now();
    const dt = Math.min((ts - this.previous) / 1000, 0.2);
    this.previous = ts;
    const scene = this.scene;
    if (!scene) return;
    if (this.s.playing && !this.windowLoading) {
      this.time += dt * Number(this.s.speed);
      if (this.time >= scene.times.length - 1) {
        const target = this.globalTime();
        this.time = scene.times.length - 1;
        if (this.sequence && target < this.sequence.meta.total_frames - 1) void this.seekWindow(target);
        else this.state.set({ playing: false });
      }
    }
    computeFrame(scene, this.time);
    this.view?.update(this.time, this.s.layers);
    if (!this.sceneLoading && this.view) {
      const loading = this.view.readyToDisplay || this.rendererFailed ? null : GLOBE_LOADING;
      if (loading !== this.s.loading) this.state.set({ loading });
    }
    if (ts - this.lastReadout >= 100) {
      this.updateReadout();
      this.lastReadout = ts;
    }
    this.frameDurations.push(performance.now() - frameStart);
    const draws = this.view?.drawCount ?? 0;
    if (!this.performanceStart) {
      this.performanceStart = ts;
      this.performanceDraws = draws;
    }
    if (ts - this.performanceStart >= 2000) {
      const sorted = [...this.frameDurations].sort((a, b) => a - b);
      const fps = (this.frameDurations.length * 1000) / (ts - this.performanceStart);
      const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? 0;
      const drawRate = (draws - this.performanceDraws) * 1000 / (ts - this.performanceStart);
      const gpu = this.view?.gpuReadout?.();
      this.state.set({ framePerformance: `${fps.toFixed(1)} updates/s · ${drawRate.toFixed(1)} draws/s · CPU p95 ${p95.toFixed(1)} ms${gpu ? ` · ${gpu}` : ""}` });
      this.performanceDraws = draws;
      this.performanceStart = ts;
      this.frameDurations = [];
    }
  };
}
