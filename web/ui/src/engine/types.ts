// The shapes the studio service sends (godsat/studio). Only the fields the window reads.

export type Vec3 = [number, number, number];

export interface SceneObject {
  id: string;
  name: string;
  kind: string;
  positions_km: (Vec3 | null)[];
  attitude?: unknown;
}

export interface SequenceWindow {
  offset: number;
}

export interface SequenceMeta {
  id: string;
  index: number;
  total_frames: number;
  windows: SequenceWindow[];
  offset: number;
  start?: string;
  end?: string;
}

export interface GroundStation {
  id: string;
  name: string;
  latitude_deg: number;
  longitude_deg: number;
  altitude_km: number;
}

export interface GroundLinks {
  stations: GroundStation[];
  frequency_hz: number;
  minimum_elevation_deg?: number;
}

export interface Scene {
  title: string;
  frame: string;
  units?: unknown;
  times: string[];
  objects: SceneObject[];
  observations?: ({ cause?: string } | null)[];
  custody_seconds?: number;
  warnings?: unknown;
  environment?: { sources?: unknown[] };
  ground_links?: GroundLinks;
  sequence?: SequenceMeta;
  source: { kind: string; artifact_id?: string; sha256?: string; [key: string]: unknown };
}

export interface Artifact {
  id: string;
  name: string;
  path: string;
  format: string;
  kind: string;
  bytes: number;
  modified: number;
  local: boolean;
  root?: string;
}

export interface Catalog {
  artifacts: Artifact[];
  truncated?: boolean;
}

export interface LinkRow {
  elevation_deg?: number;
  vacuum_time_ms?: number;
  dry_slant_delay_m?: number;
  ionosphere_group_delay_m?: number;
  uplink_faraday_deg?: number;
  cloud_fraction?: number;
  unavailable: Record<string, string>;
  inputs?: unknown;
}

export interface LinkResult {
  scene_sha256: string;
  times: string[];
  rows: LinkRow[];
  station?: unknown;
  limits?: unknown;
}

export interface Inspection {
  name: string;
  media?: string;
  rows?: Record<string, unknown>[];
  columns?: string[];
  text?: string;
  data?: unknown;
  note?: string;
}

export type TrackStateName = "observed" | "stale" | "lost" | "unknown" | "unavailable";

export interface TrackState {
  state: TrackStateName;
  age: number | null;
  last: number;
}
