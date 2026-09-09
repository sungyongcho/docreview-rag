/** Presentation isolation only; authoritative permissions remain on the running server. */
export type PreviewMode = "normal" | "host" | "document";
interface PreviewState { mode: PreviewMode; pendingMutations: number; }
const SERVER_STATE: PreviewState = { mode: "normal", pendingMutations: 0 };
const previewDocument = typeof window !== "undefined" && window.name === "docreview-production-preview";
let state: PreviewState = previewDocument ? { mode: "document", pendingMutations: 0 } : SERVER_STATE;
const listeners = new Set<() => void>();
const requests = new Map<AbortController, boolean>();
const PREVIEW_PAUSE = Symbol("production-preview-pause");
export const PREVIEW_STORAGE_PREFIX = "docreview:preview:";
/** Display preferences remain shared; all other preview records have their own persistent namespace. */
const SHARED_PREFERENCE_KEYS = new Set(["docreview.locale", "docreview:theme", "docreview:locale:v1", "docreview:theme:v1"]);
function previewKeys(): string[] {
  return Object.keys(window.localStorage).filter((key) => key.startsWith(PREVIEW_STORAGE_PREFIX));
}
function physicalKey(key: string): string { return SHARED_PREFERENCE_KEYS.has(key) ? key : PREVIEW_STORAGE_PREFIX + key; }
/** Legacy DEV and versioned PROD preferences address the same display preference. */
function sharedLegacyKey(key: string): string | null {
  return key === "docreview:theme:v1" ? "docreview:theme" : key === "docreview:locale:v1" ? "docreview.locale" : null;
}
const previewStorage: Storage = {
  get length() { return previewKeys().length; },
  clear: () => { for (const key of previewKeys()) window.localStorage.removeItem(key); },
  getItem: (key) => {
    const legacy = sharedLegacyKey(key);
    const value = legacy ? window.localStorage.getItem(legacy) : null;
    return value === null ? window.localStorage.getItem(physicalKey(key)) : JSON.stringify({ version: 1, value });
  },
  key: (index) => previewKeys()[index]?.slice(PREVIEW_STORAGE_PREFIX.length) ?? null,
  removeItem: (key) => window.localStorage.removeItem(physicalKey(key)),
  setItem: (key, value) => {
    window.localStorage.setItem(physicalKey(key), String(value));
    const legacy = sharedLegacyKey(key);
    if (legacy) {
      const payload: unknown = JSON.parse(value);
      if (payload && typeof payload === "object" && "value" in payload && typeof payload.value === "string") window.localStorage.setItem(legacy, payload.value);
    }
  },
};

function update(next: PreviewState) {
  state = next;
  for (const listener of listeners) listener();
}

export function previewState() { return state; }
export function serverPreviewState() { return SERVER_STATE; }
export function subscribePreview(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** A preview document never reads or changes the user's session; the DEV host keeps its real storage. */
export function browserStorage(): Storage {
  return state.mode === "document" ? previewStorage : window.localStorage;
}

/** Suspend outstanding reads before the DEV tree is hidden; never cancel a write. */
export function enterProductionPreview(mode: "host" | "document" = "host"): boolean {
  if (state.pendingMutations) return false;
  if (state.mode === mode) return true;
  for (const [controller, mutation] of requests) if (!mutation) controller.abort(PREVIEW_PAUSE);
  update({ mode, pendingMutations: 0 });
  return true;
}

export function exitProductionPreview() {
  for (const controller of requests.keys()) controller.abort();
  update({ mode: "normal", pendingMutations: state.pendingMutations });
}

/** Let a suspended finite DEV read resume without replacing its retained data with an error. */
function waitForDevelopment(signal?: AbortSignal | null): Promise<void> {
  return new Promise((resolve, reject) => {
    const cancel = () => { unsubscribe(); signal?.removeEventListener("abort", cancel); reject(new DOMException("Request aborted.", "AbortError")); };
    const changed = () => { if (state.mode === "normal") { unsubscribe(); signal?.removeEventListener("abort", cancel); resolve(); } };
    const unsubscribe = subscribePreview(changed);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
    else changed();
  });
}

/** `RequestInit` plus an optional per-attempt deadline in milliseconds; `0` or absent means no deadline. */
export type PresentationInit = RequestInit & { timeoutMs?: number };

/** Reject as soon as `signal` aborts, so a body read that ignores the abort cannot outlive its deadline. */
function rejectOnAbort(signal: AbortSignal): Promise<never> {
  return new Promise((_resolve, reject) => {
    if (signal.aborted) reject(signal.reason);
    else signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
}

/** Bound every application request, including streaming and Local Operations callers. */
export async function presentationFetch(url: string, init: PresentationInit = {}, operator = false): Promise<Response> {
  const { timeoutMs, ...requestInit } = init;
  const method = (requestInit.method ?? "GET").toUpperCase();
  const mutation = method !== "GET" && method !== "HEAD";
  const pathname = new URL(url, typeof window === "undefined" ? "http://localhost" : window.location.origin).pathname;
  const path = pathname.replace(/^\/docreview-rag-agent\/api(?=\/|$)/, "").replace(/\/$/, "");
  const publicRead = /^\/public\/(?:documents|snapshots)(?:\/[^/]+)*$/.test(path)
    || /^\/snapshots(?:\/compare)?$/.test(path)
    || ["/health", "/ready", "/release", "/capabilities", "/limits"].includes(path);
  const publicExecution = method === "POST" && ["/retrieve", "/review", "/review/stream"].includes(path);
  if (state.mode === "host" || state.mode === "document" && (operator || !(mutation ? publicExecution : publicRead))) {
    throw new DOMException("Production preview permits the public API only.", "AbortError");
  }
  const controller = new AbortController();
  const startedNormally = state.mode === "normal";
  const abort = () => controller.abort();
  if (requestInit.signal?.aborted) controller.abort();
  requestInit.signal?.addEventListener("abort", abort, { once: true });
  requests.set(controller, mutation);
  if (mutation) update({ ...state, pendingMutations: state.pendingMutations + 1 });
  let headers = requestInit.headers;
  if (state.mode === "document") {
    const publicHeaders = new Headers(headers);
    publicHeaders.set("X-DocReview-Public", "true");
    headers = publicHeaders;
  }
  // The deadline covers one attempt: a read resumed after a production preview starts a fresh clock.
  const deadline = timeoutMs
    ? setTimeout(() => controller.abort(new DOMException("Request timed out.", "TimeoutError")), timeoutMs)
    : null;
  try {
    const response = await fetch(url, { ...requestInit, headers, signal: controller.signal });
    if (deadline === null) return response;
    // A finite read stays under its deadline through body delivery: a server that sends the
    // headers and then stalls must surface as a timeout, not as a promise that never settles.
    const text = await Promise.race([response.text(), rejectOnAbort(controller.signal)]);
    const bodyless = response.status === 204 || response.status === 205 || response.status === 304;
    return new Response(bodyless ? null : text, { status: response.status, statusText: response.statusText, headers: response.headers });
  } catch (error) {
    if (startedNormally && !mutation && controller.signal.reason === PREVIEW_PAUSE && !requestInit.signal?.aborted) {
      if (deadline !== null) clearTimeout(deadline);
      await waitForDevelopment(requestInit.signal);
      return await presentationFetch(url, init, operator);
    }
    throw error;
  } finally {
    if (deadline !== null) clearTimeout(deadline);
    requestInit.signal?.removeEventListener("abort", abort);
    requests.delete(controller);
    if (mutation) update({ ...state, pendingMutations: Math.max(0, state.pendingMutations - 1) });
  }
}
