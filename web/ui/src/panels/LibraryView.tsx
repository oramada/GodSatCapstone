// The data library: saved collections, every indexed artifact, and an inspector that reads
// one (an image or PDF, a table with its preview plot, or the text and data as saved).

import {
  Alert,
  AlertDescription,
  AnimatedNumber,
  Badge,
  Button,
  Card,
  CardTitle,
  Chip,
  ChoiceSelect,
  CodeBlock,
  Disclosure,
  EmptyState,
  Field,
  Input,
  ListRow,
  LoadingState,
  ScrollArea,
  SectionHeader,
  Stagger,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Text,
} from "@sam/design-system";
import {
  ArrowRightIcon,
  FileSearchIcon,
  FileWarningIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderSearchIcon,
  LibraryIcon,
  ListFilterIcon,
  RotateCwIcon,
  SearchIcon,
  ShieldAlertIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { TablePlot } from "../charts/TablePlot";
import { Fine } from "../components/Panel";
import { FormatIcon } from "../components/icons";
import { getJson, messageOf } from "../engine/api";
import { useEngine, useStudio } from "../engine/context";
import { kilobytes, shortDate } from "../engine/format";
import { artifactCategory, sceneCandidate, type ArtifactCategory, type Collection } from "../engine/legacy";
import type { Artifact, Inspection } from "../engine/types";

const CATEGORIES: { value: "all" | ArtifactCategory; label: string }[] = [
  { value: "all", label: "All artifacts" },
  { value: "inputs", label: "Inputs and configurations" },
  { value: "tables", label: "Tables" },
  { value: "figures", label: "Figures and PDFs" },
  { value: "reports", label: "Reports and text" },
  { value: "spatial", label: "Spatial candidates" },
  { value: "other", label: "Other products" },
];

/** Formats the service can open as a scene. */
const OPENABLE = new Set(["json", "csv", "npz", "parquet"]);
const LISTED = 500;

/** Media the inspector embeds: only the service's own artifact route, never another origin or scheme. */
export function safeMedia(url: string | undefined): string | null {
  if (!url || !url.startsWith("/api/studio/artifact?")) return null;
  const parsed = new URL(url, window.location.origin);
  return parsed.origin === window.location.origin && parsed.pathname === "/api/studio/artifact" ? parsed.pathname + parsed.search : null;
}

type Reading = { id: string; status: "loading" } | { id: string; status: "ready"; data: Inspection } | { id: string; status: "error"; message: string };

export function LibraryView({ groups, onOpenScene }: { groups: Collection[]; onOpenScene: (id: string) => void }) {
  const artifacts = useStudio((s) => s.artifacts);
  const engine = useEngine();
  const catalogSerial = useStudio((s) => s.catalogSerial);
  const catalogError = useStudio((s) => s.catalogError);
  const discovering = catalogSerial === 0 && catalogError === null;
  const [retrying, setRetrying] = useState(false);
  const retry = async () => {
    setRetrying(true);
    try {
      await engine.refresh();
    } finally {
      setRetrying(false);
    }
  };
  const [scopeId, setScopeId] = useState<string | null>(null);
  const [category, setCategory] = useState<"all" | ArtifactCategory>("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [reading, setReading] = useState<Reading | null>(null);
  const request = useRef(0);
  const libraryHeading = useRef<HTMLHeadingElement>(null);

  const scope = useMemo(() => (scopeId ? (groups.find((g) => g.id === scopeId) ?? null) : null), [groups, scopeId]);

  const list = useMemo(() => {
    const ids = scope ? new Set(scope.artifacts.map((a) => a.id)) : null;
    const needle = search.toLowerCase();
    return artifacts.filter(
      (a) =>
        (!ids || ids.has(a.id)) &&
        (category === "all" || artifactCategory(a) === category) &&
        `${a.path} ${a.kind}`.toLowerCase().includes(needle),
    );
  }, [artifacts, scope, category, search]);

  const inspect = useCallback(async (id: string) => {
    const serial = ++request.current;
    setSelected(id);
    setReading((current) => (current?.id === id && current.status === "ready" ? current : { id, status: "loading" }));
    try {
      const data = await getJson<Inspection>(`/api/studio/inspect?id=${encodeURIComponent(id)}`);
      if (serial === request.current) setReading({ id, status: "ready", data });
    } catch (error) {
      if (serial === request.current) setReading({ id, status: "error", message: messageOf(error) });
    }
  }, []);

  // A selection the view no longer lists is dropped; one still listed is read again after a catalog refresh.
  useEffect(() => {
    if (selected && !list.some((a) => a.id === selected)) {
      ++request.current;
      setSelected(null);
      setReading(null);
    }
  }, [list, selected]);
  // A selected artifact is read again only when the catalog says its file changed, not on every
  // 15-second refresh (a large file is a full read on the service each time).
  const selectedModified = selected ? artifacts.find((a) => a.id === selected)?.modified : undefined;
  const lastModified = useRef(selectedModified);
  useEffect(() => {
    const before = lastModified.current;
    lastModified.current = selectedModified;
    if (selected && selectedModified !== undefined && before !== undefined && selectedModified !== before) void inspect(selected);
  }, [selected, selectedModified, inspect]);

  const openCollection = (group: Collection) => {
    setScopeId(group.id);
    setCategory("all");
    setSearch("");
    // The list below now shows the collection: take the reader to its heading.
    libraryHeading.current?.focus();
  };

  const artifact = selected ? artifacts.find((a) => a.id === selected) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <Collections groups={groups} onInspect={openCollection} onOpenScene={onOpenScene} />
      <section aria-labelledby="library-title" className="flex flex-col gap-3">
        <SectionHeader
          inset={false}
          icon={scope ? <FolderIcon /> : <LibraryIcon />}
          title={scope ? scope.name : "Data library"}
          headingProps={{ id: "library-title", ref: libraryHeading, tabIndex: -1, className: "outline-none" }}
          description={
            scope
              ? `${scope.path} · ${scope.artifacts.length.toLocaleString()} artifacts`
              : "Inputs, saved outputs, reports and source products across the workspace."
          }
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            aria-label="Search artifacts"
            type="search"
            size="sm"
            placeholder="Search files, formats, runs…"
            leading={<SearchIcon />}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <ChoiceSelect label="Artifact type" value={category} options={CATEGORIES} onChange={setCategory} className="sm:w-full" />
        </div>
        {scope || category !== "all" || search ? (
          <div role="group" aria-label="Filters in force" className="flex flex-wrap gap-1.5">
            {scope ? (
              <Chip icon={<FolderIcon />} onRemove={() => setScopeId(null)} removeLabel="Show the whole workspace" className="motion-enter">
                {scope.name}
              </Chip>
            ) : null}
            {category !== "all" ? (
              <Chip icon={<ListFilterIcon />} onRemove={() => setCategory("all")} removeLabel="Show every artifact type" className="motion-enter">
                {CATEGORIES.find((c) => c.value === category)?.label}
              </Chip>
            ) : null}
            {search ? (
              <Chip icon={<SearchIcon />} onRemove={() => setSearch("")} removeLabel="Clear the search" className="motion-enter">
                {search}
              </Chip>
            ) : null}
          </div>
        ) : null}
        <Fine>
          <AnimatedNumber value={Math.min(list.length, LISTED)} /> of <AnimatedNumber value={list.length} /> matching artifacts
        </Fine>
        <div className="grid gap-3 lg:grid-cols-2">
          <Card variant="outline" radius="row" padding="none" className="h-80 overflow-hidden">
            {list.length ? (
              <ScrollArea scrollFade>
                <Stagger as="ul" aria-label="Artifacts" className="flex flex-col p-1">
                  {list.slice(0, LISTED).map((a) => (
                    <li key={a.id}>
                      <ArtifactRow artifact={a} selected={a.id === selected} onSelect={() => void inspect(a.id)} />
                    </li>
                  ))}
                </Stagger>
              </ScrollArea>
            ) : discovering ? (
              <LoadingState variant="rows" label="Discovering artifacts" />
            ) : catalogError !== null && artifacts.length === 0 ? (
              <EmptyState
                size="compact"
                icon={<FileWarningIcon />}
                title="Couldn’t read local artifacts"
                description={catalogError}
                action={
                  <Button size="sm" loading={retrying} disabled={retrying} onClick={() => void retry()}>
                    <RotateCwIcon />
                    Try again
                  </Button>
                }
                className="h-full"
              />
            ) : artifacts.length === 0 ? (
              <EmptyState
                size="compact"
                icon={<FolderOpenIcon />}
                title="No artifacts yet"
                description="Studio lists the inputs, outputs and reports it finds in this workspace. Run an experiment to add one."
                className="h-full"
              />
            ) : (
              <EmptyState
                size="compact"
                title="No artifacts match this view"
                description="Change the filter or search to explore more files."
                className="h-full"
              />
            )}
          </Card>
          <Inspector artifact={artifact} reading={reading} onOpenScene={onOpenScene} onRetry={(id) => void inspect(id)} />
        </div>
      </section>
    </div>
  );
}

function ArtifactRow({ artifact, selected, onSelect }: { artifact: Artifact; selected: boolean; onSelect: () => void }) {
  return (
    <ListRow
      variant="item"
      selected={selected}
      onSelect={onSelect}
      media={<FormatIcon artifact={artifact} />}
      title={artifact.name}
      description={`${artifact.format.toUpperCase()} · ${kilobytes(artifact.bytes)}${artifact.local ? "" : " · Cloud placeholder"} · ${artifact.path}`}
    />
  );
}

function Inspector({
  artifact,
  reading,
  onOpenScene,
  onRetry,
}: {
  artifact: Artifact | undefined;
  reading: Reading | null;
  onOpenScene: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  const openable = artifact && OPENABLE.has(artifact.format);
  // No live region over the whole card: a loaded table or file would be read out in full.
  // LoadingState speaks for itself; the rest is there when the person moves to it.
  return (
    <Card variant="outline" radius="row" padding="sm" className="flex min-w-0 flex-col gap-3">
      {artifact ? (
        <SectionHeader
          inset={false}
          as="h3"
          icon={<FormatIcon artifact={artifact} />}
          title={
            <span className="truncate" title={artifact.name}>
              {artifact.name}
            </span>
          }
          action={
            openable ? (
              <Button variant="outline" size="sm" onClick={() => onOpenScene(artifact.id)}>
                Open as scene
                <ArrowRightIcon />
              </Button>
            ) : null
          }
        />
      ) : null}
      {!artifact || !reading ? (
        <EmptyState
          size="compact"
          icon={<FileSearchIcon />}
          title="Select an artifact"
          description="Inspect run summaries, response tables, trajectory arrays, attitude telemetry, source products and validation evidence. Unsupported spatial formats stay in their original representation."
        />
      ) : reading.status === "loading" ? (
        <LoadingState variant="lines" label="Reading artifact" />
      ) : reading.status === "error" ? (
        <EmptyState
          size="compact"
          icon={<FileWarningIcon />}
          title="Couldn't read this artifact"
          description={reading.message}
          action={
            <Button size="sm" onClick={() => onRetry(reading.id)}>
              <RotateCwIcon />
              Try again
            </Button>
          }
        />
      ) : (
        <div key={reading.id} className="motion-enter">
          <InspectionBody data={reading.data} />
        </div>
      )}
    </Card>
  );
}

function InspectionBody({ data }: { data: Inspection }) {
  const media = safeMedia(data.media);
  const columns = useMemo(() => data.columns ?? Object.keys(data.rows?.[0] ?? {}), [data]);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {data.media ? (
        media ? (
          data.name.toLowerCase().endsWith(".pdf") ? (
            <iframe src={media} title={data.name} className="h-96 w-full rounded-row bg-fill" />
          ) : (
            <img src={media} alt={data.name} className="w-full rounded-row bg-fill" />
          )
        ) : (
          <Alert variant="note" role="note">
            <ShieldAlertIcon />
            <AlertDescription>This preview points outside Studio, so it isn’t shown.</AlertDescription>
          </Alert>
        )
      ) : data.rows ? (
        <>
          <TablePlot rows={data.rows} columns={columns} />
          <Table height="md" size="compact" label={`${data.name} preview`}>
            <TableHeader>
              <TableRow>
                {columns.map((key) => (
                  <TableHead key={key}>{key}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((row, i) => (
                <TableRow key={i}>
                  {columns.map((key) => {
                    const value = row[key];
                    return (
                      <TableCell key={key} numeric={typeof value === "number"}>
                        {value !== null && typeof value === "object" ? JSON.stringify(value) : String(value ?? "")}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      ) : (
        <CodeBlock text={data.text || JSON.stringify(data.data ?? data, null, 2)} label={data.name} height="md" copy />
      )}
      {data.note ? <Fine>{data.note}</Fine> : null}
    </div>
  );
}

function Collections({
  groups,
  onInspect,
  onOpenScene,
}: {
  groups: Collection[];
  onInspect: (group: Collection) => void;
  onOpenScene: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return groups.filter((g) => `${g.name} ${g.path}`.toLowerCase().includes(needle));
  }, [groups, query]);
  return (
    <Disclosure icon={<FolderOpenIcon />} title="Saved collections" meta={`${shown.length.toLocaleString()} collections`}>
      <div className="flex flex-col gap-3">
        <Field label="Find collection" htmlFor="collection-search">
          <Input
            id="collection-search"
            type="search"
            size="sm"
            placeholder="Name or path"
            leading={<SearchIcon />}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </Field>
        {shown.length ? (
          <Stagger as="ul" className="grid gap-2 sm:grid-cols-2">
            {shown.map((group) => (
              <li key={group.id}>
                <CollectionCard group={group} onInspect={onInspect} onOpenScene={onOpenScene} />
              </li>
            ))}
          </Stagger>
        ) : (
          <Fine>No matching collections.</Fine>
        )}
      </div>
    </Disclosure>
  );
}

function CollectionCard({
  group,
  onInspect,
  onOpenScene,
}: {
  group: Collection;
  onInspect: (group: Collection) => void;
  onOpenScene: (id: string) => void;
}) {
  const priority = (a: Artifact) => (/^(scene-sequence|scene|replay)\.json$/.test(a.name) ? 0 : 1);
  const spatial = group.artifacts
    .filter((a) => a.local && sceneCandidate(a))
    .sort((a, b) => priority(a) - priority(b) || b.modified - a.modified)[0];
  const tables = group.artifacts.filter((a) => artifactCategory(a) === "tables").length;
  const figures = group.artifacts.filter((a) => artifactCategory(a) === "figures").length;
  return (
    <Card as="article" variant="outline" radius="row" padding="sm" className="flex h-full flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Badge variant="secondary">{group.kind}</Badge>
        <Text as="span" size="2xs" tone="muted" numeric>
          {shortDate(group.modified)}
        </Text>
      </div>
      <div className="min-w-0">
        <CardTitle className="truncate" title={group.name}>
          {group.name}
        </CardTitle>
        <Text size="xs" tone="muted" truncate title={group.path}>
          {group.path}
        </Text>
      </div>
      <Text size="xs" tone="muted" numeric>
        {group.artifacts.length.toLocaleString()} artifacts · {tables} tables · {figures} figures
      </Text>
      <div className="mt-auto flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => onInspect(group)}>
          <FolderSearchIcon />
          Inspect collection
        </Button>
        {spatial ? (
          <Button variant="ghost" size="sm" onClick={() => onOpenScene(spatial.id)}>
            Open visualization
            <ArrowRightIcon />
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
