import { afterEach, describe, expect, it } from "vitest";

import { numericColumns } from "../charts/TablePlot";
import type { Artifact, Scene } from "../engine/types";
import { readWatch, watchKey } from "./AnalysisView";
import { compareCandidates } from "./CompareView";
import { safeMedia } from "./LibraryView";

describe("safeMedia", () => {
  it("allows only the service's own artifact route", () => {
    expect(safeMedia("/api/studio/artifact?id=abc")).toBe("/api/studio/artifact?id=abc");
  });

  it.each([
    undefined,
    "",
    "https://evil.example/api/studio/artifact?id=1",
    "//evil.example/api/studio/artifact?id=1",
    "javascript:alert(1)",
    "data:image/png;base64,AAAA",
    "/api/studio/artifacts?id=1",
    "/api/studio/artifact/../scene?id=1",
    "/api/studio/scene?id=1",
    "/studio/app/index.html",
  ])("refuses %s", (url) => {
    expect(safeMedia(url)).toBeNull();
  });
});

const artifact = (path: string, extra: Partial<Artifact> = {}) =>
  ({
    id: path,
    path,
    name: path.split("/").pop()!,
    format: path.split(".").pop()!,
    local: true,
    modified: 0,
    size: 1,
    ...extra,
  }) as Artifact;

describe("compareCandidates", () => {
  it("keeps local JSON products only", () => {
    const list = [
      artifact("reports/a/notes.json"),
      artifact("reports/a/table.csv"),
      artifact("reports/a/remote.json", { local: false }),
      artifact("outputs/run/scene-window-00001.json"),
    ];
    expect(compareCandidates(list).map((a) => a.path)).toEqual(["reports/a/notes.json"]);
  });

  it("puts summaries and results first, then the newest", () => {
    const list = [
      artifact("r/old.json", { modified: 1 }),
      artifact("r/new.json", { modified: 9 }),
      artifact("r/summary.json", { modified: 0 }),
      artifact("r/result.json", { modified: 5 }),
    ];
    expect(compareCandidates(list).map((a) => a.name)).toEqual(["result.json", "summary.json", "new.json", "old.json"]);
  });
});

describe("watchlist storage", () => {
  afterEach(() => localStorage.clear());

  it("keys by sequence, then artifact, then title", () => {
    const base = { title: "Demo", source: { kind: "illustrative" } } as unknown as Scene;
    expect(watchKey(base)).toBe("godsat.watch.v1:Demo");
    expect(watchKey({ ...base, source: { kind: "replay", artifact_id: "abc" } } as Scene)).toBe("godsat.watch.v1:abc");
    expect(watchKey({ ...base, sequence: { id: "seq" } } as unknown as Scene)).toBe("godsat.watch.v1:seq");
  });

  it("reads saved ids, capped at 12", () => {
    const ids = Array.from({ length: 20 }, (_, i) => String(i));
    localStorage.setItem("k", JSON.stringify(ids));
    expect(readWatch("k")).toEqual(ids.slice(0, 12));
  });

  it("survives anything else in storage", () => {
    expect(readWatch("absent")).toEqual([]);
    localStorage.setItem("k", "{not json");
    expect(readWatch("k")).toEqual([]);
    localStorage.setItem("k", '{"a":1}');
    expect(readWatch("k")).toEqual([]);
    localStorage.setItem("k", '["1",2,null,{"x":1},"3"]');
    expect(readWatch("k")).toEqual(["1", "3"]);
  });
});

describe("numericColumns", () => {
  it("keeps columns whose every filled cell is a number", () => {
    const rows = [
      { step: "1", name: "a", gap: "", mixed: "1", empty: "" },
      { step: "2", name: "b", gap: "0.5", mixed: "x", empty: null },
    ];
    expect(numericColumns(rows, ["step", "name", "gap", "mixed", "empty"])).toEqual(["step", "gap"]);
  });

  it("refuses infinities and handles no rows", () => {
    expect(numericColumns([{ v: "Infinity" }], ["v"])).toEqual([]);
    expect(numericColumns([], ["v"])).toEqual([]);
  });
});
