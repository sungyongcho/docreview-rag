/** Presentation isolation only; authoritative permissions remain on the running server. */
export type PreviewMode = "normal" | "host" | "document";
interface PreviewState { mode: PreviewMode; pendingMutations: number; }
const SERVER_STATE: PreviewState = { mode: "normal", pendingMutations: 0 };
const previewDocument = typeof window !== "undefined" && window.name === "docreview-production-preview";
let state: PreviewState = previewDocument ? { mode: "document", pendingMutations: 0 } : SERVER_STATE;
const listeners = new Set<() => void>();
const requests = new Map<AbortController, boolean>();
const PREVIEW_PAUSE = Symbol("production-preview-pause");
const memory = new Map<string, string>();
if (previewDocument) {
  const locale = new URLSearchParams(window.location.search).get("locale");
  if (locale === "en" || locale === "ko") memory.set("docreview.locale", locale);
  const theme = new URLSearchParams(window.location.search).get("theme");
  if (theme === "light" || theme === "dark" || theme === "system") memory.set("docreview:theme", theme);
}
const memoryStorage: Storage = {
  get length() { return memory.size; },
  clear: () => memory.clear(),
  getItem: (key) => memory.get(key) ?? null,
  key: (index) => [...memory.keys()][index] ?? null,
  removeItem: (key) => { memory.delete(key); },
  setItem: (key, value) => { memory.set(String(key), String(value)); },
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

/** Never read or change the user's persistent session from a preview document. */
export function browserStorage(): Storage {
  return state.mode === "normal" ? window.localStorage : memoryStorage;
}

/** Suspend outstanding reads before the DEV tree is hidden; never cancel a write. */
export function enterProductionPreview(mode: "host" | "document" = "host"): boolean {
  if (state.pendingMutations) return false;
  if (state.mode === mode) return true;
  for (const [controller, mutation] of requests) if (!mutation) controller.abort(PREVIEW_PAUSE);
  memory.clear();
  update({ mode, pendingMutations: 0 });
  return true;
}

export function exitProductionPreview() {
  for (const controller of requests.keys()) controller.abort();
  memory.clear();
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

/** Bound every application request, including streaming and Local Operations callers. */
export async function presentationFetch(url: string, init: PresentationInit = {}, operator = false): Promise<Response> {
  const { timeoutMs, ...requestInit } = init;
  const method = (requestInit.method ?? "GET").toUpperCase();
  const mutation = method !== "GET" && method !== "HEAD";
  const pathname = new URL(url, typeof window === "undefined" ? "http://localhost" : window.location.origin).pathname;
  const path = pathname.replace(/^\/docreview-rag-agent\/api(?=\/|$)/, "").replace(/\/$/, "");
  const allowed = /^\/public\/documents(?:\/[^/]+)?$/.test(path)
    || /^\/snapshots(?:\/compare)?$/.test(path)
    || ["/health", "/capabilities", "/limits"].includes(path);
  if (state.mode === "host" || (state.mode === "document" && (operator || mutation || !allowed))) {
    throw new DOMException("Production preview permits public metadata reads only.", "AbortError");
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
    return await fetch(url, { ...requestInit, headers, signal: controller.signal });
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
