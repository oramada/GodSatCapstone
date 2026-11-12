import { decodePackedScene, PACKED_SCENE_MIME } from "../../../studio/packed-scene.js";
import type { Scene } from "./types";

// The service's JSON boundary. Every read skips the HTTP cache (the catalog changes on disk
// under a running studio); an error body's `error` is the message a person reads.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** What a person reads when the request never got an answer (the service stopped, the network dropped). */
export const UNREACHABLE = "Couldn't reach the Studio service. Check that it's running, then try again.";

async function read<T>(response: Response): Promise<T> {
  let body: unknown;
  let readable = true;
  try {
    body = await response.json();
  } catch (error) {
    if (isAbort(error)) throw error;
    readable = false;
  }
  if (!response.ok) {
    const message =
      body && typeof body === "object" && typeof (body as { error?: unknown }).error === "string"
        ? (body as { error: string }).error
        : `Couldn't reach the Studio service (${response.status}). Try again.`;
    throw new ApiError(message, response.status);
  }
  if (!readable) {
    throw new ApiError(`The studio service sent an unreadable reply (${response.status}). Reload Studio and try again.`, response.status);
  }
  return body as T;
}

/** fetch, with a network failure (fetch's TypeError) told as words; an abort stays an abort. */
async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    if (error instanceof TypeError) throw new ApiError(UNREACHABLE, 0);
    throw error;
  }
}

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  return read<T>(await send(url, { cache: "no-store", ...(signal ? { signal } : {}) }));
}

export async function getScene(url: string, signal?: AbortSignal): Promise<Scene> {
  const response = await send(url, { cache: "no-store", headers: { Accept: PACKED_SCENE_MIME }, ...(signal ? { signal } : {}) });
  if (!response.ok || response.headers.get("Content-Type") !== PACKED_SCENE_MIME) return read<Scene>(response);
  try {
    return decodePackedScene(await response.arrayBuffer()) as Scene;
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new ApiError("The Studio service sent an invalid packed scene. Reload Studio and try again.", response.status);
  }
}

export async function postJson<T>(url: string, payload: unknown, token: string): Promise<T> {
  const response = await send(url, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Studio-Token": token },
    body: JSON.stringify(payload),
  });
  return read<T>(response);
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Saves text as a file in the person's downloads. */
export function download(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
