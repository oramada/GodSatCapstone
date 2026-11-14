import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { download } from "./api";
import { computeFrame, trackState, trackStates } from "./legacy";
import { focusMatches, LINK_DEBOUNCE_MS, sourceKindLabel, StudioEngine } from "./studio";
import type { Artifact, Scene, SceneObject } from "./types";

// The engine runs against fakes: the renderer (no WebGL in jsdom), the compute core (spied, so
// a test can see what ran before the readout) and fetch (each request is held until a test answers).
const fakes = vi.hoisted(() => {
  class FakeView {
    static last: FakeView | null = null;
    mode = "system";
    framing = "earth";
    selectedByUser = false;
    station: string | null = null;
    readyToDisplay = true;
    environmentMessage = "";
    detail = { caption: "" };
    setScene = vi.fn();
    setFocus = vi.fn();
    setQuality = vi.fn();
    setCameraMode = vi.fn();
    lookAtSun = vi.fn();
    setSelection = vi.fn();
    setBoxSelection = vi.fn();
    followSatellite = vi.fn(() => true);
    zoomSatellite = vi.fn();
    stopFollowing = vi.fn();
    reset = vi.fn();
    update = vi.fn();
    destroy = vi.fn();
    constructor() {
      FakeView.last = this;
    }
  }
  return { FakeView };
});

vi.mock("./legacy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./legacy")>();
  return {
    ...actual,
    CesiumObservatory: fakes.FakeView,
    initializeCompute: vi.fn(async () => false),
    prepareScene: vi.fn(() => false),
    computeFrame: vi.fn(() => null),
    trackState: vi.fn(actual.trackState),
    trackStates: vi.fn(actual.trackStates),
  };
});
vi.mock("./palette", () => ({ readGlobePalette: () => ({}) }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<typeof import("./api")>()), download: vi.fn() }));

const object = (id: string, name: string) => ({ id, name }) as SceneObject;
const many = Array.from({ length: 250 }, (_, i) => object(String(1000 + i), `IRIDIUM ${i}`));

describe("focusMatches", () => {
  it("lists every object for an empty query, capped at 200", () => {
    const { count, listed } = focusMatches(many, "  ", "");
    expect(count).toBe(250);
    expect(listed).toHaveLength(200);
  });

  it("matches name or id, ignoring case and spaces around the query", () => {
    const objects = [object("41917", "IRIDIUM 106"), object("25544", "ISS (ZARYA)")];
    expect(focusMatches(objects, " iridium ", "").listed.map((o) => o.id)).toEqual(["41917"]);
    expect(focusMatches(objects, "2554", "").listed.map((o) => o.id)).toEqual(["25544"]);
    expect(focusMatches(objects, "nothing", "").count).toBe(0);
  });

  it("keeps the focused object listed even past the cap or outside the query", () => {
    const focused = many[240]!;
    const past = focusMatches(many, "", focused.id);
    expect(past.listed[0]).toBe(focused);
    expect(past.listed).toHaveLength(201);
    expect(past.count).toBe(250);
    const outside = focusMatches(many, "IRIDIUM 1", "1240");
    expect(outside.listed).toContain(focused);
  });

  it("doesn't list a focus id that isn't in the scene", () => {
    expect(focusMatches([object("1", "A")], "", "missing").listed).toHaveLength(1);
  });
});

describe("sourceKindLabel", () => {
  it("names each kind of scene source", () => {
    expect(sourceKindLabel("illustrative")).toBe("Illustrative");
    expect(sourceKindLabel("modeled")).toBe("Modeled");
    expect(sourceKindLabel("replay")).toBe("Saved data");
    expect(sourceKindLabel(undefined)).toBe("");
  });
});

// --- The engine -------------------------------------------------------------------------------

interface Call {
  url: string;
  signal: AbortSignal | undefined;
  aborted: boolean;
  answer(body: unknown, status?: number): void;
  fail(error: unknown): void;
}

let calls: Call[] = [];
/** Answers for requests a test doesn't hold: by URL prefix. */
let auto: [string, () => unknown][] = [];

function fetchFake(url: string, init: RequestInit = {}): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    const reply = (body: unknown, status = 200) =>
      resolve(new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
    const signal = init.signal ?? undefined;
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const call: Call = { url, signal, aborted: false, answer: reply, fail: reject };
    signal?.addEventListener("abort", () => {
      call.aborted = true;
      reject(new DOMException("Aborted", "AbortError"));
    });
    const automatic = auto.find(([prefix]) => url.startsWith(prefix));
    if (automatic) reply(automatic[1]());
    else calls.push(call);
  });
}

const flush = async () => {
  for (let i = 0; i < 6; i++) await new Promise<void>((resolve) => setImmediate(resolve));
};

const pending = (prefix: string) => calls.filter((c) => c.url.startsWith(prefix) && !c.aborted);
const take = (prefix: string): Call => {
  const index = calls.findIndex((c) => c.url.startsWith(prefix) && !c.aborted);
  if (index < 0) throw new Error(`No pending request for ${prefix}: ${calls.map((c) => c.url).join(", ")}`);
  return calls.splice(index, 1)[0]!;
};

const TIMES = Array.from({ length: 5 }, (_, i) => new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString());
const track = () => TIMES.map(() => [7000, 0, 0] as [number, number, number]);

function makeScene(id: string, extra: Partial<Scene> = {}): Scene {
  return {
    title: id,
    frame: "ITRS",
    times: TIMES,
    objects: [
      { id: "sat-1", name: "SAT 1", kind: "satellite", positions_km: track() },
      { id: "sat-2", name: "SAT 2", kind: "satellite", positions_km: track() },
      { id: "gs", name: "Ground", kind: "station", positions_km: track() },
      { id: "eye", name: "Sensor", kind: "sensor", positions_km: track() },
    ],
    observations: TIMES.map((_, i) => ({ detected: i % 2 ? ["sat-1"] : ["sat-2"] }) as { cause?: string }),
    custody_seconds: 90,
    ground_links: { stations: [{ id: "st", name: "St", latitude_deg: 0, longitude_deg: 0, altitude_km: 0 }], frequency_hz: 1e9 },
    source: { kind: "replay", artifact_id: id, sha256: `sha-${id}` },
    ...extra,
  };
}

const artifact = (id: string, modified: number): Artifact => ({
  id,
  name: "scene.json",
  path: `outputs/${id}/scene.json`,
  format: "json",
  kind: "scene",
  bytes: 10,
  modified,
  local: true,
});

let catalog: Artifact[] = [];
let engine: StudioEngine;
let globe: HTMLElement;
let notices: string[] = [];

async function boot(initial = "A") {
  auto = [["/api/studio/catalog", () => ({ artifacts: catalog })]];
  engine = new StudioEngine();
  notices = [];
  engine.onNotice = (message) => notices.push(message);
  globe = document.createElement("div");
  const started = engine.start(globe, document.createElement("canvas"), document.createElement("div"));
  await flush();
  take(`/api/studio/scene?id=${initial}`).answer(makeScene(initial));
  await started;
  await flush();
  expect(engine.state.get().activeSource).toBe(initial);
}

const render = (ts: number) => (engine as unknown as { render(ts: number): void }).render(ts);
const sceneRequests = (id: string) => calls.filter((c) => c.url === `/api/studio/scene?id=${id}`);

describe("StudioEngine", () => {
  beforeEach(() => {
    calls = [];
    catalog = [artifact("A", 1), artifact("B", 5)];
    vi.stubGlobal("fetch", vi.fn(fetchFake));
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.mocked(computeFrame).mockClear();
    vi.mocked(trackState).mockClear();
    vi.mocked(trackStates).mockClear();
    vi.mocked(download).mockClear();
  });
  afterEach(() => {
    engine?.stop();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  describe("catalog refresh and the open scene (1)", () => {
    it("doesn't reload a scene just opened from another source", async () => {
      await boot("A");
      engine.setSource("B");
      take("/api/studio/scene?id=B").answer(makeScene("B"));
      await flush();
      expect(engine.state.get().activeSource).toBe("B");
      await engine.refresh();
      await flush();
      expect(sceneRequests("B")).toHaveLength(0);
      expect(engine.state.get().activeSource).toBe("B");
    });

    it("reloads the open scene, keeping its place, when its artifact changes on disk", async () => {
      await boot("A");
      catalog = [artifact("A", 2), artifact("B", 5)];
      const refreshed = engine.refresh();
      await flush();
      take("/api/studio/scene?id=A").answer(makeScene("A"));
      await refreshed;
      await engine.refresh();
      await flush();
      expect(sceneRequests("A")).toHaveLength(0);
    });

    it("leaves the scene alone while another source is opening", async () => {
      await boot("A");
      engine.setSource("B");
      catalog = [artifact("A", 9), artifact("B", 5)];
      await engine.refresh();
      expect(sceneRequests("A")).toHaveLength(0);
      take("/api/studio/scene?id=B").answer(makeScene("B"));
      await flush();
      expect(engine.state.get().activeSource).toBe("B");
    });

    it("never reloads the demonstration", async () => {
      catalog = [{ ...artifact("A", 1), name: "notes.json", path: "outputs/A/notes.txt", format: "txt" }];
      auto = [["/api/studio/catalog", () => ({ artifacts: catalog })]];
      engine = new StudioEngine();
      const started = engine.start(document.createElement("div"), document.createElement("canvas"), document.createElement("div"));
      await flush();
      take("/api/studio/scene?demo=system").answer(makeScene("demo"));
      await started;
      catalog = [{ ...catalog[0]!, modified: 7 }];
      await engine.refresh();
      await engine.refresh();
      expect(calls.filter((c) => c.url.startsWith("/api/studio/scene"))).toHaveLength(0);
      expect(engine.state.get().activeSource).toBe("demo");
    });
  });

  describe("scene downloads (2)", () => {
    it("aborts a superseded scene download without an error", async () => {
      await boot("A");
      engine.setSource("B");
      const first = calls.find((c) => c.url === "/api/studio/scene?id=B")!;
      engine.setSource("A");
      await flush();
      expect(first.aborted).toBe(true);
      expect(first.signal?.aborted).toBe(true);
      expect(engine.state.get().loading).toBe("Preparing scene…");
      take("/api/studio/scene?id=A").answer(makeScene("A"));
      await flush();
      expect(notices).toEqual([]);
      expect(engine.state.get()).toMatchObject({ activeSource: "A", sourceValue: "A", loading: null });
    });

    it("aborts the download when the engine stops", async () => {
      await boot("A");
      engine.setSource("B");
      const call = calls.find((c) => c.url === "/api/studio/scene?id=B")!;
      engine.stop();
      await flush();
      expect(call.aborted).toBe(true);
      expect(notices).toEqual([]);
    });

    it("still reports a real failure", async () => {
      await boot("A");
      engine.setSource("B");
      take("/api/studio/scene?id=B").answer({ error: "Scene is malformed" }, 400);
      await flush();
      expect(notices).toEqual(["Scene is malformed"]);
      expect(engine.state.get()).toMatchObject({ activeSource: "A", sourceValue: "A", loading: null });
    });
  });

  describe("the readout reads the compute core's frame (3)", () => {
    const frameBeforeStates = (time: number) => {
      const frame = vi.mocked(computeFrame).mock;
      const at = frame.calls.findIndex(([, step]) => step === time);
      expect(at).toBeGreaterThanOrEqual(0);
      const first = vi.mocked(trackState).mock.invocationCallOrder[0];
      expect(first).toBeDefined();
      expect(frame.invocationCallOrder[at]!).toBeLessThan(first!);
    };

    it("computes the frame for the new time before the readout, on scrub, seek, focus and links", async () => {
      await boot("A");
      const scene = engine.state.get().scene!;
      for (const act of [() => engine.scrub(2), () => engine.seekLocal(3.5), () => engine.focus("sat-2"), () => engine.setStation("st")]) {
        vi.mocked(computeFrame).mockClear();
        vi.mocked(trackState).mockClear();
        act();
        frameBeforeStates((engine.readout.get() as { time: number }).time);
        expect(vi.mocked(computeFrame).mock.calls.every(([s]) => s === scene)).toBe(true);
      }
      expect(engine.readout.get()?.time).toBe(3.5);
    });

    it("takes the timeline marks in one pass, not one history walk per epoch", async () => {
      await boot("A");
      vi.mocked(trackState).mockClear();
      vi.mocked(trackStates).mockClear();
      engine.focus("sat-1");
      expect(trackStates).toHaveBeenCalledTimes(1);
      expect(vi.mocked(trackStates).mock.calls[0]?.[1]).toBe("sat-1");
      // Only the readout's per-instant states (the focus and custody), never one per epoch.
      expect(vi.mocked(trackState).mock.calls.length).toBeGreaterThan(0);
      expect(vi.mocked(trackState).mock.calls.every(([, , time]) => time === 0)).toBe(true);
      expect(engine.state.get().marks).toEqual(TIMES.map((_, i) => (i % 2 ? "observed" : "stale")).map((s, i) => (i === 0 ? "lost" : s)));
    });
  });

  describe("ground links (4)", () => {
    it("asks once for the object focus rests on, and aborts the request in flight", async () => {
      await boot("A");
      const initial = take("/api/studio/links");
      expect(initial.url).toContain("object=sat-1");
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
      engine.focus("sat-2");
      expect(initial.aborted).toBe(true);
      expect(engine.state.get().link.message).toBe("Calculating propagation estimates…");
      engine.focus("sat-1");
      vi.advanceTimersByTime(LINK_DEBOUNCE_MS - 1);
      engine.focus("sat-2");
      vi.advanceTimersByTime(LINK_DEBOUNCE_MS - 1);
      expect(pending("/api/studio/links")).toHaveLength(0);
      vi.advanceTimersByTime(1);
      const links = pending("/api/studio/links");
      expect(links).toHaveLength(1);
      expect(links[0]!.url).toContain("object=sat-2");
      expect(links[0]!.url).toContain("station=st");
      links[0]!.answer({ scene_sha256: "sha-A", times: TIMES, rows: TIMES.map(() => ({ unavailable: {} })) });
      vi.useRealTimers();
      await flush();
      expect(engine.state.get().link).toMatchObject({ message: "", result: { scene_sha256: "sha-A" } });
    });

    it("drops a debounced request when the engine stops", async () => {
      await boot("A");
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
      engine.focus("sat-2");
      engine.stop();
      vi.advanceTimersByTime(LINK_DEBOUNCE_MS * 2);
      expect(pending("/api/studio/links").filter((c) => c.url.includes("object=sat-2"))).toHaveLength(0);
    });
  });

  describe("globe assets (5)", () => {
    it("stops saying the globe is loading once the renderer reports a failure", async () => {
      await boot("A");
      const view = fakes.FakeView.last!;
      view.readyToDisplay = false;
      render(1000);
      expect(engine.state.get().loading).toBe("Loading globe textures and engine assets…");
      globe.dispatchEvent(new CustomEvent("renderererror", { detail: "Failed to load earth-day.jpg" }));
      expect(notices).toEqual(["Failed to load earth-day.jpg"]);
      render(2000);
      expect(engine.state.get().loading).toBeNull();
      engine.setSource("B");
      take("/api/studio/scene?id=B").answer(makeScene("B"));
      await flush();
      expect(engine.state.get().loading).toBeNull();
    });
  });

  describe("catalog failures (6)", () => {
    it("shows the failure, toasts once per streak in the background, and recovers", async () => {
      await boot("A");
      const serial = engine.state.get().catalogSerial;
      expect(engine.state.get().catalogError).toBeNull();
      auto = [["/api/studio/catalog", () => "{}"]];
      vi.mocked(fetch).mockImplementation(async (url) =>
        String(url).startsWith("/api/studio/catalog") ? new Response("", { status: 500 }) : fetchFake(String(url)),
      );
      await engine.refresh(true);
      await engine.refresh(true);
      await engine.refresh(true);
      expect(notices).toEqual(["Couldn't reach the Studio service (500). Try again."]);
      expect(engine.state.get()).toMatchObject({
        catalogError: "Couldn't reach the Studio service (500). Try again.",
        inventoryStatus: "Couldn't read local artifacts",
        catalogSerial: serial,
      });
      expect(engine.state.get().artifacts).toHaveLength(2);
      // A person's own refresh always answers.
      await engine.refresh();
      expect(notices).toHaveLength(2);
      vi.mocked(fetch).mockImplementation(async () => {
        throw new TypeError("Failed to fetch");
      });
      await engine.refresh(true);
      expect(notices).toHaveLength(2);
      expect(engine.state.get().catalogError).toBe("Couldn't reach the Studio service. Check that it's running, then try again.");
      vi.mocked(fetch).mockImplementation(fetchFake as typeof fetch);
      auto = [["/api/studio/catalog", () => ({ artifacts: catalog })]];
      await engine.refresh(true);
      expect(engine.state.get()).toMatchObject({ catalogError: null, inventoryStatus: "2 local artifacts", catalogSerial: serial + 1 });
      vi.mocked(fetch).mockImplementation(async () => new Response("", { status: 503 }));
      await engine.refresh(true);
      expect(notices).toHaveLength(3);
    });

    it("ends discovery on a first failure", async () => {
      vi.mocked(fetch).mockImplementation(async (url) =>
        String(url).startsWith("/api/studio/catalog") ? Promise.reject(new TypeError("Failed to fetch")) : fetchFake(String(url)),
      );
      engine = new StudioEngine();
      notices = [];
      engine.onNotice = (message) => notices.push(message);
      const started = engine.start(document.createElement("div"), document.createElement("canvas"), document.createElement("div"));
      await flush();
      take("/api/studio/scene?demo=system").answer(makeScene("demo"));
      await started;
      expect(engine.state.get()).toMatchObject({ catalogSerial: 0, inventoryStatus: "Couldn't read local artifacts", activeSource: "demo" });
      expect(engine.state.get().catalogError).toMatch(/Couldn't reach the Studio service/);
      expect(notices).toHaveLength(1);
    });

    it("skips a timer tick while a catalog read is in flight", async () => {
      await boot("A");
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
      engine.stop();
      auto = [];
      // Restart under fake timers so the 15 s interval is a fake one.
      engine = new StudioEngine();
      engine.onNotice = (message) => notices.push(message);
      const started = engine.start(document.createElement("div"), document.createElement("canvas"), document.createElement("div"));
      await flush();
      take("/api/studio/catalog").answer({ artifacts: catalog });
      await flush();
      take("/api/studio/scene?id=A").answer(makeScene("A"));
      await started;
      await flush();
      vi.advanceTimersByTime(15000);
      expect(pending("/api/studio/catalog")).toHaveLength(1);
      vi.advanceTimersByTime(15000);
      vi.advanceTimersByTime(15000);
      expect(pending("/api/studio/catalog")).toHaveLength(1);
      take("/api/studio/catalog").answer({ artifacts: catalog });
      await flush();
      vi.advanceTimersByTime(15000);
      expect(pending("/api/studio/catalog")).toHaveLength(1);
    });
  });

  describe("windowed sequences while a scene opens (7)", () => {
    const sequenced = (id: string) =>
      makeScene(id, {
        sequence: { id: `seq-${id}`, index: 0, total_frames: 10, windows: [{ offset: 0 }, { offset: 5 }], offset: 0 },
        ground_links: undefined as never,
      });

    async function bootSequence() {
      auto = [["/api/studio/catalog", () => ({ artifacts: catalog })]];
      engine = new StudioEngine();
      notices = [];
      engine.onNotice = (message) => notices.push(message);
      globe = document.createElement("div");
      const started = engine.start(globe, document.createElement("canvas"), document.createElement("div"));
      await flush();
      take("/api/studio/scene?id=A").answer(sequenced("A"));
      await started;
      await flush();
    }

    it("a scrub inside the current window leaves a pending scene's loading state", async () => {
      await bootSequence();
      engine.setSource("B");
      expect(engine.state.get().loading).toBe("Preparing scene…");
      engine.scrub(2);
      await flush();
      expect(engine.readout.get()?.time).toBe(2);
      expect(engine.state.get().loading).toBe("Preparing scene…");
      fakes.FakeView.last!.readyToDisplay = true;
      render(1000);
      expect(engine.state.get().loading).toBe("Preparing scene…");
      take("/api/studio/scene?id=B").answer(makeScene("B"));
      await flush();
      expect(engine.state.get()).toMatchObject({ activeSource: "B", loading: null });
    });

    it("a scrub back into the current window ends a window load in flight", async () => {
      await bootSequence();
      engine.scrub(7);
      await flush();
      expect(engine.state.get().loading).toBe("Loading next time window…");
      const window = calls.find((c) => c.url.startsWith("/api/studio/window"));
      expect(window).toBeDefined();
      engine.scrub(1);
      expect(engine.state.get().loading).toBeNull();
      engine.togglePlay();
      render(1000);
      render(1100);
      expect(engine.readout.get()?.time ?? 0).toBeGreaterThanOrEqual(1);
      expect((engine as unknown as { time: number }).time).toBeGreaterThan(1);
    });
  });

  describe("export (8)", () => {
    it("saves the scene unindented, without the service's ephemeris", async () => {
      await boot("A");
      const scene = engine.state.get().scene! as Scene & { celestial?: unknown };
      scene.celestial = { sun: [[1, 2, 3]], source: "fixture" };
      engine.exportScene();
      expect(download).toHaveBeenCalledTimes(1);
      const [name, text, type] = vi.mocked(download).mock.calls[0]!;
      expect(name).toBe("godsat-scene.json");
      expect(type).toBe("application/json");
      expect(text).not.toContain("\n");
      const { celestial: _sky, ...rest } = scene;
      expect(JSON.parse(text)).toEqual(JSON.parse(JSON.stringify(rest)));
      expect(scene.celestial).toBeDefined();
    });
  });

  describe("focus (9)", () => {
    it("refuses stations, sensors and unknown ids, leaving focus unchanged", async () => {
      await boot("A");
      const view = fakes.FakeView.last!;
      const before = engine.state.get().focusId;
      for (const id of ["gs", "eye", "nope"]) {
        engine.focus(id);
        globe.dispatchEvent(new CustomEvent("objectselected", { detail: id }));
      }
      expect(engine.state.get()).toMatchObject({ focusId: before, selectedByUser: false });
      expect(view.setFocus).not.toHaveBeenCalled();
      expect(view.selectedByUser).toBe(false);
      globe.dispatchEvent(new CustomEvent("objectselected", { detail: "sat-2" }));
      expect(engine.state.get()).toMatchObject({ focusId: "sat-2", selectedByUser: true });
      expect(view.setFocus).toHaveBeenCalledWith("sat-2");
    });
  });
});
