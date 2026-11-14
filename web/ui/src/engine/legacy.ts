// The studio's pure modules (web/studio/*.js), typed at the one place the window imports them.
// They stay JavaScript: tests/web runs them under node, and this bundle runs the same files.

import * as analytics from "../../../studio/analytics.js";
import * as compute from "../../../studio/compute.js";
import { CesiumObservatory as CesiumObservatoryJs } from "../../../studio/cesium-renderer.js";
import * as experimentConfig from "../../../studio/experiment-config.js";
import * as model from "../../../studio/model.js";
import { WindowSequence as WindowSequenceJs } from "../../../studio/sequence.js";
import * as workspace from "../../../studio/workspace.js";

import type { Artifact, Scene, SceneObject, TrackState, Vec3 } from "./types";

export const trackState = model.trackState as (scene: Scene, id: string, time: number) => TrackState;
/** trackState at every saved epoch, in one pass over the observations. */
export const trackStates = model.trackStates as (scene: Scene, id: string) => TrackState[];

export const initializeCompute = compute.initializeCompute as () => Promise<boolean>;
export const prepareScene = compute.prepareScene as (scene: Scene) => boolean;
export const computeFrame = compute.computeFrame as (scene: Scene, step: number) => unknown;
export const computeBackend = compute.computeBackend as () => string;

export interface Geodetic {
  latitude: number;
  longitude: number;
  altitude: number;
}
export interface Telemetry {
  position: Vec3;
  radius: number;
  geodetic: Geodetic | null;
  sampleSpeed: number | null;
}
export interface ScreenHit {
  objectIndex: number;
  distanceKm: number;
  index: number;
  validSamples: number;
}
export interface ScreenResult {
  rows: ScreenHit[];
  matchingObjects: number;
  comparisons: number;
  unavailableObjects: number;
}
export const telemetry = analytics.telemetry as (scene: Scene, object: SceneObject | undefined, time: number) => Telemetry | null;
export const groundTrack = analytics.groundTrack as (scene: Scene, object: SceneObject | undefined) => Geodetic[][];
export const timeStep = analytics.timeStep as (times: string[], instant: string | number) => number | null;
export const csvRows = analytics.csvRows as (rows: unknown[][]) => string;

export interface Collection {
  id: string;
  name: string;
  path: string;
  kind: string;
  artifacts: Artifact[];
  modified: number;
}
export type ArtifactCategory = "inputs" | "tables" | "figures" | "reports" | "spatial" | "other";
export interface NumberComparison {
  field: string;
  a: number | null;
  b: number | null;
  delta: number | null;
}
export const sceneCandidate = workspace.sceneCandidate as (artifact: Artifact) => boolean;
export const artifactCategory = workspace.artifactCategory as (artifact: Artifact) => ArtifactCategory;
export const collections = workspace.collections as (artifacts: Artifact[]) => Collection[];
export const compareNumbers = workspace.compareNumbers as (a: unknown, b: unknown) => NumberComparison[];

export interface ExperimentValues {
  epoch: string;
  duration: number;
  step: number;
  cadence: number;
  count: number;
  altitude: number;
  inclination: number;
  gravity: "point" | "j2" | "zonal" | "saved";
  drag: boolean;
  thirdBodies: boolean;
  srp: boolean;
  relativity: boolean;
  applyProperties: boolean;
  mass: number;
  dragArea: number;
  cd: number;
  radiationArea: number;
  cr: number;
}
export const buildExperiment = experimentConfig.buildExperiment as (values: ExperimentValues, template: unknown) => unknown;

export interface RendererLayers {
  atmosphere: boolean;
  ionosphere: boolean;
  celestial: boolean;
  trails: boolean;
  ghosts: boolean;
  clouds: "natural" | "clear" | "dense";
  environment: string;
}
export type Rgb = [number, number, number];
export type RendererPalette = Record<
  | "observed"
  | "stale"
  | "lost"
  | "unknown"
  | "station"
  | "trail"
  | "label"
  | "labelBackground"
  | "background"
  | "globe"
  | "ionosphere"
  | "outline",
  Rgb
>;
/** The Cesium globe and the Three detail view (web/studio/cesium-renderer.js). */
export interface Observatory {
  mode: "single" | "system";
  framing: "earth" | "all";
  selectedByUser: boolean;
  station: string | null;
  readonly readyToDisplay: boolean;
  readonly drawCount?: number;
  gpuReadout?(): string | undefined;
  environmentMessage: string;
  detail: { caption: string };
  setScene(scene: Scene, focus: string, keepCamera?: boolean): void;
  setFocus(id: string): void;
  setQuality(quality: "high" | "balanced"): void;
  setCameraMode(mode: "orbit" | "free"): void;
  lookAtSun(): void;
  setSelection(ids: readonly string[]): void;
  setBoxSelection(active: boolean): void;
  followSatellite(id: string): boolean;
  zoomSatellite(factor: number): void;
  stopFollowing(): void;
  reset(): void;
  update(step: number, layers: RendererLayers): void;
  destroy(): void;
}
export const CesiumObservatory = CesiumObservatoryJs as unknown as new (
  container: HTMLElement,
  detail: HTMLCanvasElement,
  options: { credits: HTMLElement; palette: RendererPalette },
) => Observatory;

export interface SequencePosition {
  index: number;
  local: number;
}
export interface WindowSequence {
  meta: Scene["sequence"] & {};
  cache: Map<number, Scene>;
  current: number;
  position(global: number): SequencePosition;
  seek(global: number): Promise<{ scene: Scene; local: number }>;
  prefetch(global: number): void;
  clear(): void;
}
export const WindowSequence = WindowSequenceJs as unknown as new (
  initial: Scene,
  loader: (id: string, index: number, signal: AbortSignal) => Promise<Scene>,
) => WindowSequence;
