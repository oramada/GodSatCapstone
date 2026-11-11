import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getJson, isAbort, messageOf, postJson, UNREACHABLE } from "./api";

const reply = (status: number, body: string) => new Response(body, { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("reads JSON and never uses the HTTP cache", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, '{"ok":true}'));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getJson("/api/studio/catalog")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith("/api/studio/catalog", { cache: "no-store" });
  });

  it("passes the abort signal through", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, "{}"));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    await getJson("/x", controller.signal);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ signal: controller.signal });
  });

  it("surfaces the service's own error message with the status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(404, '{"error":"Unknown studio asset"}')));
    const error = await getJson("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Unknown studio asset", status: 404 });
  });

  it("says the service couldn't be reached, with the status, when the error body has no message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(500, '{"error":42}')));
    await expect(getJson("/x")).rejects.toMatchObject({ message: "Couldn't reach the Studio service (500). Try again.", status: 500 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 502 })));
    await expect(getJson("/x")).rejects.toMatchObject({ message: "Couldn't reach the Studio service (502). Try again.", status: 502 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(postJson("/x", {}, "t")).rejects.toMatchObject({ message: "Couldn't reach the Studio service (503). Try again." });
  });

  it("says what to do when a successful reply isn't JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200 })));
    await expect(getJson("/x")).rejects.toMatchObject({
      message: "The studio service sent an unreadable reply (200). Reload Studio and try again.",
      status: 200,
    });
  });

  it("turns a network failure into words, for reads and posts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await getJson("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: UNREACHABLE, status: 0 });
    expect(UNREACHABLE).toBe("Couldn't reach the Studio service. Check that it's running, then try again.");
    await expect(postJson("/x", {}, "t")).rejects.toMatchObject({ message: UNREACHABLE });
  });

  it("keeps an abort an abort, before the reply and while reading it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("stop", "AbortError")));
    expect(isAbort(await getJson("/x").catch((e: unknown) => e))).toBe(true);
    const response = reply(200, "{}");
    vi.spyOn(response, "json").mockRejectedValue(new DOMException("stop", "AbortError"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    expect(isAbort(await getJson("/x").catch((e: unknown) => e))).toBe(true);
  });

  it("passes other fetch failures through unchanged", async () => {
    const odd = new RangeError("bad init");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(odd));
    await expect(getJson("/x")).rejects.toBe(odd);
  });

  it("posts JSON with the studio token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, '{"id":"job"}'));
    vi.stubGlobal("fetch", fetchMock);
    await expect(postJson("/api/studio/experiments/run", { a: 1 }, "tok")).resolves.toEqual({ id: "job" });
    expect(fetchMock).toHaveBeenCalledWith("/api/studio/experiments/run", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Studio-Token": "tok" },
      body: '{"a":1}',
    });
  });

  it("tells an abort apart from a failure", () => {
    expect(isAbort(new DOMException("stop", "AbortError"))).toBe(true);
    expect(isAbort(new Error("AbortError"))).toBe(false);
    expect(messageOf(new Error("boom"))).toBe("boom");
    expect(messageOf("plain")).toBe("plain");
  });
});
