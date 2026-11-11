// A preview plot of an inspected table: exactly the rows read, one dot per row, no
// aggregation or fitted model. Rows are grouped by colour when a column names a
// configuration, policy or regime. Ported from web/studio/charts.js; the colours are the
// kit's chart tokens.

import { ChoiceSelect, Field } from "@sam/design-system";
import { useMemo, useState } from "react";

import { Fine } from "../components/Panel";
import { useWidth } from "./useWidth";

const SERIES = ["fill-chart-1", "fill-chart-2", "fill-chart-3", "fill-chart-4", "fill-chart-5"] as const;
/** Drawn in CSS pixels (see useWidth): the height is fixed, the width is the element's. */
const H = 210;
const LEFT = 56;
const RIGHT = 20;

const blank = (value: unknown) => value === "" || value === null || value === undefined;

export function numericColumns(rows: Record<string, unknown>[], columns: string[]): string[] {
  return columns.filter(
    (key) =>
      rows.some((row) => !blank(row[key]) && Number.isFinite(Number(row[key]))) &&
      rows.every((row) => blank(row[key]) || Number.isFinite(Number(row[key]))),
  );
}

export function TablePlot({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  const numeric = useMemo(() => numericColumns(rows, columns), [rows, columns]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [svgRef, W] = useWidth<SVGSVGElement>(560);
  const column = chosen && numeric.includes(chosen) ? chosen : numeric.includes("custody_continuity") ? "custody_continuity" : numeric[0];
  const plot = useMemo(() => {
    if (!column || !rows.length) return null;
    const values = rows
      .map((row, i) => ({ i, v: blank(row[column]) ? Number.NaN : Number(row[column]), row }))
      .filter((point) => Number.isFinite(point.v));
    if (!values.length) return null;
    const lo = Math.min(...values.map((p) => p.v));
    const hi = Math.max(...values.map((p) => p.v));
    const range = hi - lo || Math.abs(lo) * 0.1 || 1;
    const y = (v: number) => 175 - ((v - lo) / range) * 140;
    const x = (i: number) => LEFT + (i / Math.max(1, rows.length - 1)) * (W - LEFT - RIGHT - 8);
    const groupKey = columns.find((k) => ["configuration", "policy", "regime"].includes(k));
    const groups = [...new Set(rows.map((row) => (groupKey ? row[groupKey] : undefined)))];
    const ticks = [0, 1, 2, 3].map((t) => lo + (range * t) / 3);
    return { values, x, y, groupKey, groups, ticks };
  }, [rows, columns, column, W]);
  if (!column || !plot) return null;
  return (
    <div className="flex flex-col gap-2">
      <Field label="Plot column" htmlFor="plot-column">
        <ChoiceSelect
          id="plot-column"
          value={column}
          options={numeric.map((k) => ({ value: k, label: k }))}
          onChange={setChosen}
          className="sm:w-full"
        />
      </Field>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Scatter plot of preview rows" className="w-full">
        {plot.ticks.map((v, t) => (
          <g key={t}>
            <line x1={LEFT} x2={W - RIGHT} y1={plot.y(v)} y2={plot.y(v)} className="stroke-border" strokeWidth={1} />
            <text x={LEFT - 8} y={plot.y(v) + 4} textAnchor="end" className="fill-muted-foreground text-xs tabular-nums">
              {v.toPrecision(3)}
            </text>
          </g>
        ))}
        <text x={LEFT} y={200} className="fill-muted-foreground text-xs tabular-nums">
          1
        </text>
        <text x={W - RIGHT} y={200} textAnchor="end" className="fill-muted-foreground text-xs tabular-nums">
          {rows.length}
        </text>
        {plot.values.map((point) => {
          const group = plot.groupKey ? point.row[plot.groupKey] : undefined;
          return (
            <circle
              key={point.i}
              cx={plot.x(point.i)}
              cy={plot.y(point.v)}
              r={3.3}
              opacity={0.9}
              className={SERIES[Math.max(0, plot.groups.indexOf(group)) % SERIES.length]}
            >
              <title>{`Row ${point.i + 1}${plot.groupKey ? ` · ${String(group)}` : ""}\n${column}: ${point.v}`}</title>
            </circle>
          );
        })}
      </svg>
      <Fine>Each dot is one preview row. Horizontal axis: row number. No aggregation. Up to 200 rows.</Fine>
    </div>
  );
}
