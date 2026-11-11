// A chart draws in CSS pixels: its viewBox is as wide as the element, so a label set in a
// type token reads at that token's size at every panel width, instead of shrinking with a
// fixed viewBox on a phone. Until the first measurement it uses `fallback`. The ref is a
// callback, so an element that mounts later (a chart that had nothing to draw) is measured too.

import { useCallback, useEffect, useState } from "react";

export function useWidth<T extends Element>(fallback: number) {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry?.contentRect.width ?? 0);
      // A hidden panel measures 0: keep the last real width rather than drawing nothing.
      if (next > 0) setWidth(next);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  const ref = useCallback((next: T | null) => setNode(next), []);
  return [ref, width] as const;
}
