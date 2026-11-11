// Two saved products side by side: every scalar numeric field of two bounded JSON objects,
// and B − A. Ported from web/studio/workspace-ui.js.

import {
  Button,
  ChoiceSelect,
  Field,
  SectionHeader,
  Stagger,
  StatusLine,
  type StatusLineTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@sam/design-system";
import { GitCompareArrowsIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { getJson, messageOf } from "../engine/api";
import { useStudio } from "../engine/context";
import { figure } from "../engine/format";
import { compareNumbers, sceneCandidate, type NumberComparison } from "../engine/legacy";
import type { Artifact, Inspection } from "../engine/types";

const PREFERRED = /summary|benchmark|result|response/i;

/** Local JSON products that aren't scenes or sequence windows, summaries and results first, newest next. */
export function compareCandidates(artifacts: Artifact[]): Artifact[] {
  return artifacts
    .filter((a) => a.local && a.format === "json" && !sceneCandidate(a) && !/-window-\d{5}\.json$/.test(a.path))
    .sort((a, b) => Number(!PREFERRED.test(a.name)) - Number(!PREFERRED.test(b.name)) || b.modified - a.modified);
}

const INITIAL = "Select products with comparable quantities and units. Tables, arrays and images can be inspected in the data library.";

export function CompareView() {
  const artifacts = useStudio((s) => s.artifacts);
  const candidates = useMemo(() => compareCandidates(artifacts), [artifacts]);
  const options = useMemo(() => candidates.map((a) => ({ value: a.id, label: a.path, title: a.path })), [candidates]);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [rows, setRows] = useState<NumberComparison[] | null>(null);
  const [status, setStatus] = useState<{ text: string; tone: StatusLineTone }>({ text: INITIAL, tone: "" });
  const [busy, setBusy] = useState(false);
  const serial = useRef(0);

  const reset = (text: string) => {
    serial.current += 1;
    setBusy(false);
    setRows(null);
    setStatus({ text, tone: "" });
  };

  // Keep each pick while the catalog still lists it; otherwise take the next candidate.
  useEffect(() => {
    const keep = (current: string, index: number) =>
      candidates.some((c) => c.id === current) ? current : (candidates[index]?.id ?? "");
    const nextA = keep(a, 0);
    const nextB = keep(b, 1);
    if ((a && nextA !== a) || (b && nextB !== b)) reset("Available products changed. Compare again to read the selected files.");
    setA(nextA);
    setB(nextB);
  }, [candidates]);

  const compare = async () => {
    if (busy || candidates.length < 2) return;
    const run = ++serial.current;
    setBusy(true);
    setRows(null);
    setStatus({ text: "Reading saved products…", tone: "" });
    try {
      const responses = await Promise.all(
        [a, b].map((id) => getJson<Inspection & { data?: { truncated?: boolean } }>(`/api/studio/inspect?id=${encodeURIComponent(id)}`)),
      );
      if (run !== serial.current) return;
      if (responses.some((r) => !r.data || typeof r.data !== "object" || Array.isArray(r.data) || r.data.truncated)) {
        throw new Error(
          "Choose two bounded JSON objects. Large arrays, raw tables and truncated previews remain available in the data library.",
        );
      }
      const result = compareNumbers(responses[0]?.data, responses[1]?.data);
      setRows(result);
      setStatus({
        text: result.length
          ? `${result.length} numeric fields, read at ${new Date().toLocaleTimeString()}. Arrays are excluded. Matching field names don’t establish matching units or experimental conditions.`
          : "No scalar numeric fields in these products. Inspect their tables or documents in the data library.",
        tone: result.length ? "ok" : "",
      });
    } catch (error) {
      if (run === serial.current) setStatus({ text: messageOf(error), tone: "error" });
    } finally {
      if (run === serial.current) setBusy(false);
    }
  };

  const pick = (set: (id: string) => void) => (id: string) => {
    set(id);
    reset("Selection changed. Compare products to read the selected files.");
  };

  return (
    <section aria-labelledby="compare-title" className="flex flex-col gap-3">
      <SectionHeader inset={false} as="h3" icon={<GitCompareArrowsIcon />} title={<span id="compare-title">Compare saved products</span>} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Product A" htmlFor="compare-a">
          <ChoiceSelect id="compare-a" value={a} options={options} disabled={!options.length} onChange={pick(setA)} className="sm:w-full" />
        </Field>
        <Field label="Product B" htmlFor="compare-b">
          <ChoiceSelect id="compare-b" value={b} options={options} disabled={!options.length} onChange={pick(setB)} className="sm:w-full" />
        </Field>
      </div>
      <div>
        <Button size="sm" loading={busy} disabled={busy || candidates.length < 2} onClick={() => void compare()}>
          <GitCompareArrowsIcon />
          Compare products
        </Button>
      </div>
      <StatusLine text={status.text} tone={status.tone} />
      {rows && rows.length ? (
        <Table height="lg" size="compact" label="Numeric field comparison" busy={busy}>
          <TableHeader>
            <TableRow>
              <TableHead>Field</TableHead>
              <TableHead numeric>A</TableHead>
              <TableHead numeric>B</TableHead>
              <TableHead numeric>B − A</TableHead>
            </TableRow>
          </TableHeader>
          <Stagger as={TableBody}>
            {rows.map((row) => (
              <TableRow key={row.field}>
                <TableCell code>{row.field}</TableCell>
                {([row.a, row.b, row.delta] as const).map((value, i) => (
                  <TableCell key={i} numeric title={value === null ? "Unavailable" : String(value)}>
                    {figure(value)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </Stagger>
        </Table>
      ) : null}
    </section>
  );
}
