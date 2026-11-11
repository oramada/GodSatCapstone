// WGS84 sub-satellite points of the focused object at saved epochs, on a plate carrée twice as
// wide as it is tall: x = (longitude + 180) / 360 × width, y = (90 − latitude) / 180 × height.
// Gaps and dateline crossings are separate polylines. Drawn in CSS pixels (see useWidth), so
// the labels keep their type size on a phone.

import type { Geodetic } from "../engine/legacy";
import { useWidth } from "./useWidth";

export function GroundTrack({ segments, current }: { segments: Geodetic[][]; current: Geodetic | null }) {
  const [ref, w] = useWidth<SVGSVGElement>(720);
  const h = w / 2;
  const x = (g: Geodetic) => ((g.longitude + 180) / 360) * w;
  const y = (g: Geodetic) => ((90 - g.latitude) / 180) * h;
  const grid = [
    `M0 0H${w}V${h}H0Z`,
    ...[1, 2, 3].map((q) => `M0 ${(q * h) / 4}H${w}`),
    ...[1, 2, 3].map((q) => `M${(q * w) / 4} 0V${h}`),
  ].join(" ");
  return (
    <svg ref={ref} viewBox={`0 0 ${w} ${h}`} role="img" aria-labelledby="ground-track-title" className="w-full rounded-row bg-fill">
      <title id="ground-track-title">Longitude and latitude of the focused object at saved epochs</title>
      <path d={grid} className="fill-none stroke-border" strokeWidth={1} />
      <g className="fill-muted-foreground text-xs">
        <text x={8} y={18}>
          90° N
        </text>
        <text x={8} y={h / 2 - 4}>
          0°
        </text>
        <text x={8} y={h - 8}>
          90° S
        </text>
        <text x={w / 2 + 6} y={h - 8}>
          0° longitude
        </text>
      </g>
      <g className="fill-none stroke-success" strokeWidth={1.5} strokeLinejoin="round">
        {segments.map((points, i) => (
          <polyline key={i} points={points.map((g) => `${x(g)},${y(g)}`).join(" ")} />
        ))}
      </g>
      {current ? <circle cx={x(current)} cy={y(current)} r={5} className="fill-warning stroke-background" strokeWidth={1.5} /> : null}
    </svg>
  );
}
