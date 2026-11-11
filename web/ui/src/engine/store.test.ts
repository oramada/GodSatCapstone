import { describe, expect, it, vi } from "vitest";

import { Store } from "./store";

describe("Store", () => {
  it("replaces the value and tells every listener once", () => {
    const store = new Store({ a: 1 });
    const listener = vi.fn();
    store.subscribe(listener);
    const next = { a: 2 };
    store.replace(next);
    expect(store.get()).toBe(next);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("ignores a replace with the same value", () => {
    const value = { a: 1 };
    const store = new Store(value);
    const listener = vi.fn();
    store.subscribe(listener);
    store.replace(value);
    expect(listener).not.toHaveBeenCalled();
  });

  it("merges a patch into a new object and keeps the other fields", () => {
    const store = new Store({ a: 1, b: "x" });
    const before = store.get();
    store.set({ a: 2 });
    expect(store.get()).toEqual({ a: 2, b: "x" });
    expect(store.get()).not.toBe(before);
  });

  it("tells no one about a patch that changes nothing", () => {
    const shared = [1];
    const store = new Store({ a: 1, list: shared });
    const listener = vi.fn();
    store.subscribe(listener);
    store.set({ a: 1, list: shared });
    expect(listener).not.toHaveBeenCalled();
    store.set({ list: [1] });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("stops telling a listener after it unsubscribes, even mid-notify", () => {
    const store = new Store(0);
    const late = vi.fn();
    let unsubscribeLate = () => {};
    store.subscribe(() => unsubscribeLate());
    unsubscribeLate = store.subscribe(late);
    store.replace(1);
    // The snapshot taken before notifying still includes it this once.
    expect(late).toHaveBeenCalledTimes(1);
    store.replace(2);
    expect(late).toHaveBeenCalledTimes(1);
  });
});
