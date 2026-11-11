// A small external store for React's useSyncExternalStore: a value, replaced or patched,
// and the listeners told after each change.

import { useSyncExternalStore } from "react";

export class Store<T> {
  private value: T;
  private readonly listeners = new Set<() => void>();

  constructor(initial: T) {
    this.value = initial;
  }

  get = (): T => this.value;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  replace(next: T): void {
    if (Object.is(next, this.value)) return;
    this.value = next;
    for (const listener of [...this.listeners]) listener();
  }

  /** Merges fields into an object value; a patch that changes nothing tells no one. */
  set(patch: Partial<T>): void {
    const current = this.value as Record<string, unknown>;
    if (Object.entries(patch).every(([key, value]) => Object.is(current[key], value))) return;
    this.replace({ ...this.value, ...patch });
  }
}

/** Reads one slice of a store; re-renders only when that slice changes (by Object.is). */
export function useStore<T, S>(store: Store<T>, select: (value: T) => S): S {
  return useSyncExternalStore(
    store.subscribe,
    () => select(store.get()),
    () => select(store.get()),
  );
}
