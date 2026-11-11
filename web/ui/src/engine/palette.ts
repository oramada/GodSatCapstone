// The globe's colours, read from the kit's tokens. The globe is space, so it always takes the
// dark palette (Zephium's tokens are declared under any [data-theme="dark"] scope): a probe
// inside such a scope reads each token, and a 1x1 canvas turns whatever the browser computes
// (hex, a colour function, color-mix) into the red, green and blue bytes Cesium takes.

import type { RendererPalette } from "./legacy";

const TOKENS: Record<keyof RendererPalette, string> = {
  observed: "--color-success",
  stale: "--color-warning",
  lost: "--color-danger",
  unknown: "--color-tint-graphite",
  station: "--color-warning",
  trail: "--color-tint-teal",
  label: "--color-text",
  labelBackground: "--color-page",
  background: "--color-canvas",
  globe: "--color-surface",
  ionosphere: "--color-tint-teal",
  outline: "--color-canvas",
};

function bytes(context: CanvasRenderingContext2D, value: string): [number, number, number] {
  context.clearRect(0, 0, 1, 1);
  context.fillStyle = value;
  context.fillRect(0, 0, 1, 1);
  const [r = 0, g = 0, b = 0] = context.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}

export function readGlobePalette(): RendererPalette {
  const probe = document.createElement("span");
  probe.dataset.theme = "dark";
  probe.hidden = true;
  document.body.append(probe);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  try {
    if (!context) throw new Error("Canvas 2D is unavailable");
    const style = getComputedStyle(probe);
    const palette = {} as RendererPalette;
    for (const [key, token] of Object.entries(TOKENS) as [keyof RendererPalette, string][]) {
      const value = style.getPropertyValue(token).trim();
      if (!value) throw new Error(`Design token ${token} is not defined`);
      palette[key] = bytes(context, value);
    }
    return palette;
  } finally {
    probe.remove();
  }
}
