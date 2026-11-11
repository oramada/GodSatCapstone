// One icon per idea, used everywhere the idea appears: a panel's toolbar button, its title and
// the controls that open it all show the same mark, so a glance says where you are.

import {
  BracesIcon,
  DatabaseIcon,
  FileIcon,
  FileTextIcon,
  FlaskConicalIcon,
  ImageIcon,
  LayersIcon,
  type LucideIcon,
  OrbitIcon,
  SatelliteIcon,
  Table2Icon,
} from "lucide-react";

import type { Artifact } from "../engine/types";
import type { PanelId } from "./Panel";

export const PANEL_ICON: Record<PanelId, LucideIcon> = {
  experiment: FlaskConicalIcon,
  layers: LayersIcon,
  data: DatabaseIcon,
  inspect: SatelliteIcon,
};

const FORMAT_ICON: Record<string, LucideIcon> = {
  csv: Table2Icon,
  tsv: Table2Icon,
  parquet: Table2Icon,
  png: ImageIcon,
  jpg: ImageIcon,
  jpeg: ImageIcon,
  svg: ImageIcon,
  json: BracesIcon,
  npz: OrbitIcon,
  pdf: FileTextIcon,
  md: FileTextIcon,
  txt: FileTextIcon,
};

/** What kind of file an artifact is, at a glance: a table, a picture, data, a document. */
export function FormatIcon({ artifact }: { artifact: Pick<Artifact, "format"> }) {
  const Icon = FORMAT_ICON[artifact.format.toLowerCase()] ?? FileIcon;
  return <Icon aria-hidden />;
}
