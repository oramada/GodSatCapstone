import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useWidth } from "./useWidth";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A ResizeObserver the test drives: `resize(width)` reports a new width to every live observer. */
const observers = new Set<{ cb: ResizeObserverCallback; nodes: Set<Element> }>();
class FakeObserver {
  entry: { cb: ResizeObserverCallback; nodes: Set<Element> };
  constructor(cb: ResizeObserverCallback) {
    this.entry = { cb, nodes: new Set() };
    observers.add(this.entry);
  }
  observe(node: Element) {
    this.entry.nodes.add(node);
  }
  disconnect() {
    observers.delete(this.entry);
  }
}
const resize = (width: number) =>
  act(() => {
    for (const o of observers)
      for (const target of o.nodes)
        o.cb([{ target, contentRect: { width } } as unknown as ResizeObserverEntry], o as unknown as ResizeObserver);
  });

let container: HTMLDivElement;
let root: Root;
let seen: number[] = [];
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", FakeObserver);
  observers.clear();
  seen = [];
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

function Chart({ drawn }: { drawn: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>(720);
  seen.push(width);
  return drawn ? createElement("div", { ref }) : null;
}

it("starts at the fallback, then follows the element's width", () => {
  act(() => root.render(createElement(Chart, { drawn: true })));
  expect(seen.at(-1)).toBe(720);
  resize(343.6);
  expect(seen.at(-1)).toBe(344);
});

it("measures an element that mounts after the hook", () => {
  act(() => root.render(createElement(Chart, { drawn: false })));
  expect(observers.size).toBe(0);
  act(() => root.render(createElement(Chart, { drawn: true })));
  expect(observers.size).toBe(1);
  resize(390);
  expect(seen.at(-1)).toBe(390);
});

it("keeps the last width while hidden (0) and stops observing once gone", () => {
  act(() => root.render(createElement(Chart, { drawn: true })));
  resize(500);
  resize(0);
  expect(seen.at(-1)).toBe(500);
  act(() => root.render(createElement(Chart, { drawn: false })));
  expect(observers.size).toBe(0);
});

it("does nothing without ResizeObserver", () => {
  vi.stubGlobal("ResizeObserver", undefined);
  function Probe() {
    const [ref, width] = useWidth<HTMLDivElement>(560);
    const [, rerender] = useState(0);
    seen.push(width);
    return createElement("div", { ref, onClick: () => rerender((n) => n + 1) });
  }
  act(() => root.render(createElement(Probe)));
  expect(seen.at(-1)).toBe(560);
});
