import { Segmented, StatTile } from "@sam/design-system";
import { ChartLineIcon, GitCompareArrowsIcon, LibraryIcon } from "lucide-react";
import { type ReactNode, type RefObject, useMemo, useState } from "react";

import { Fine, Panel } from "../components/Panel";
import { PANEL_ICON } from "../components/icons";
import { useStudio } from "../engine/context";
import { MISSING } from "../engine/format";
import { artifactCategory, collections } from "../engine/legacy";
import { AnalysisView } from "./AnalysisView";
import { CompareView } from "./CompareView";
import { LibraryView } from "./LibraryView";

type Tab = "library" | "analysis" | "compare";
const TABS: { value: Tab; label: string; hint: string; icon: ReactNode }[] = [
  { value: "library", label: "Library", hint: "Inspect files, tables and source evidence", icon: <LibraryIcon /> },
  { value: "analysis", label: "Analysis", hint: "Telemetry, watchlist, ground track and sampled approaches", icon: <ChartLineIcon /> },
  { value: "compare", label: "Compare", hint: "Choose two products to compare numeric fields", icon: <GitCompareArrowsIcon /> },
];

export function DataPanel({
  onOpenScene,
  ...props
}: {
  open: boolean;
  onClose: () => void;
  headingRef: (node: HTMLHeadingElement | null) => void;
  trigger: RefObject<HTMLElement | null>;
  onOpenScene: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("library");
  const artifacts = useStudio((s) => s.artifacts);
  // Until the first catalog read, the counts are unknown, not zero.
  const known = useStudio((s) => s.catalogSerial > 0);
  const sequenceStatus = useStudio((s) => s.sequenceStatus);
  const groups = useMemo(() => collections(artifacts), [artifacts]);
  const counts = useMemo(() => {
    let tables = 0;
    let inputs = 0;
    for (const artifact of artifacts) {
      const category = artifactCategory(artifact);
      if (category === "tables") tables += 1;
      else if (category === "inputs") inputs += 1;
    }
    return { tables, inputs };
  }, [artifacts]);
  return (
    <Panel id="data-panel" icon={PANEL_ICON.data} title="Data and analysis" label="Data and analysis" closeLabel="Close data panel" side="wide" {...props}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile variant="inset" size="sm" countUp label="Saved collections" value={known ? groups.length : MISSING} />
        <StatTile variant="inset" size="sm" countUp label="Indexed artifacts" value={known ? artifacts.length : MISSING} />
        <StatTile variant="inset" size="sm" countUp label="Tables" value={known ? counts.tables : MISSING} />
        <StatTile variant="inset" size="sm" countUp label="Input files" value={known ? counts.inputs : MISSING} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Segmented label="Data view" value={tab} options={TABS} onChange={setTab} />
        <Fine>{TABS.find((t) => t.value === tab)?.hint}</Fine>
      </div>
      {/* Each view stays mounted (a running screening, a chosen artifact); shown again, it rises in (rule 1). */}
      <div hidden={tab !== "library"} className="motion-enter">
        <LibraryView groups={groups} onOpenScene={onOpenScene} />
      </div>
      <div hidden={tab !== "analysis"} className="motion-enter">
        <AnalysisView />
      </div>
      <div hidden={tab !== "compare"} className="motion-enter">
        <CompareView />
      </div>
      {sequenceStatus ? <Fine>{sequenceStatus}</Fine> : null}
    </Panel>
  );
}
