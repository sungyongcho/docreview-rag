import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useRuntimeHealth } from "./use-runtime-health";
import type { ReviewEngineState } from "./types";

const READY = {
  status: "ready",
  mode: "runtime",
  admin_mode: "live",
  policy_revision: "2026-09-01",
  models: {},
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  corpus: {
    availability: "ready",
    database_connected: true,
    schema_status: "compatible",
    schema_message: "compatible",
    documents: 1,
    chunks: 1,
    embedded_chunks: 1,
    pending_embeddings: 0,
    bm25_ready: true,
    writable: true,
  },
};

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("useRuntimeHealth", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("starts paused without reads and ignores refresh and browser events until resumed", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async (input: RequestInfo | URL) => response(String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health") ? { status: "ok" } : READY));
    vi.stubGlobal("fetch", fetch);
    const { result, rerender } = renderHook(({ active }) => useRuntimeHealth({ active }), { initialProps: { active: false } });
    await act(async () => {
      await result.current.check(true);
      result.current.refreshLocal({ enabled: true, model: "hidden" });
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("offline"));
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetch).not.toHaveBeenCalled();
    expect(result.current.checking).toBe(false);
    expect(result.current.modalVisible).toBe(false);
    rerender({ active: true });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.kind).toBe("healthy");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("retains paused health, aborts its pending request, and ignores a late response", async () => {
    vi.useFakeTimers();
    let release!: (response: Response) => void;
    let pendingSignal: AbortSignal | null | undefined;
    let readinessRequests = 0;
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health")) return response({ status: "ok" });
      readinessRequests += 1;
      if (readinessRequests === 2) { pendingSignal = init?.signal; return pending; }
      return response({ ...READY, corpus: { ...READY.corpus, documents: readinessRequests } });
    });
    vi.stubGlobal("fetch", fetch);
    const { result, rerender } = renderHook(({ active }) => useRuntimeHealth({ active }), { initialProps: { active: true } });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const retained = result.current.readiness;
    act(() => { void result.current.check(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(readinessRequests).toBe(2);
    expect(result.current.kind).toBe("healthy");
    expect(result.current.checking).toBe(true);
    rerender({ active: false });
    expect(pendingSignal?.aborted).toBe(true);
    await act(async () => {
      release(response({ ...READY, status: "degraded" }));
      await result.current.check(true);
      window.dispatchEvent(new Event("offline"));
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(result.current.readiness).toBe(retained);
    expect(result.current.kind).toBe("healthy");
    expect(result.current.checking).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(4);
    rerender({ active: true });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.readiness?.corpus.documents).toBe(3);
    expect(fetch).toHaveBeenCalledTimes(6);
  });

  it("does not chain a readiness read after a paused health request resolves late", async () => {
    let release!: (response: Response) => void;
    const fetch = vi.fn(() => new Promise<Response>((resolve) => { release = resolve; }));
    vi.stubGlobal("fetch", fetch);
    const { rerender } = renderHook(({ active }) => useRuntimeHealth({ active }), { initialProps: { active: true } });
    rerender({ active: false });
    await act(async () => release(response({ status: "ok" })));
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("separates healthy, DB-degraded, and dismissed warning state", async () => {
    let degraded = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health")) return response({ status: "ok", mode: "runtime" });
      const payload = degraded
        ? { ...READY, status: "degraded", corpus: { ...READY.corpus, availability: "degraded", schema_status: "drifted" } }
        : READY;
      return response(payload, degraded ? 503 : 200);
    }));
    const { result } = renderHook(() => useRuntimeHealth());

    await waitFor(() => expect(result.current.kind).toBe("healthy"));
    degraded = true;
    await act(async () => result.current.check());
    expect(result.current.kind).toBe("db_degraded");
    expect(result.current.modalVisible).toBe(true);
    act(() => result.current.dismissWarning());
    expect(result.current.modalVisible).toBe(false);
    await act(async () => result.current.check());
    expect(result.current.modalVisible).toBe(false);
  });

  it("retains healthy state during a transient failure and clears waiting on recovery", async () => {
    vi.useFakeTimers();
    let failing = false;
    vi.stubGlobal("fetch", vi.fn(async input => {
      if (failing) throw new TypeError("temporary network failure");
      return response(String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health") ? { status: "ok" } : READY);
    }));
    const { result } = renderHook(() => useRuntimeHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    failing = true;
    await act(async () => { await result.current.check(); });
    expect(result.current.kind).toBe("healthy");
    expect(result.current.modalVisible).toBe(false);
    expect(result.current.waiting).toBe(true);
    failing = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(result.current.waiting).toBe(false);
    expect(result.current.kind).toBe("healthy");
  });

  it("uses cheap probes when readiness is slow and does not declare a live API down", async () => {
    vi.useFakeTimers();
    let readyCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async input => {
      if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health")) return response({ status: "ok" });
      readyCalls++;
      throw new Error("readiness delayed");
    }));
    const { result } = renderHook(() => useRuntimeHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
    expect(readyCalls).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(24_000); });
    expect(result.current.kind).not.toBe("api_down");
    expect(result.current.waiting).toBe(true);
    expect(readyCalls).toBeLessThan(5);
    await act(async () => { window.dispatchEvent(new Event("offline")); await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.kind).not.toBe("api_down");
    expect(result.current.waiting).toBe(true);
  });

  it("treats an unreachable API as a non-dismissible modal issue", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const { result } = renderHook(() => useRuntimeHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.modalVisible).toBe(false);
    expect(result.current.waiting).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(21_000); });
    expect(result.current.kind).toBe("api_down");
    expect(result.current.modalVisible).toBe(true);
    act(() => result.current.dismissWarning());
    expect(result.current.modalVisible).toBe(true);
  });

  it("rechecks when the browser returns online", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => (
      String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health")
        ? response({ status: "ok", mode: "runtime" })
        : response(READY)
    ));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.kind).toBe("healthy"));
    const calls = fetch.mock.calls.length;

    window.dispatchEvent(new Event("online"));

    await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(calls));
  });
});

it("refreshes a changed connection immediately and ignores an older in-flight readiness response", async () => {
  let resolveOld!: (value: Response) => void;
  const delayed = new Promise<Response>((resolve) => { resolveOld = resolve; });
  let readyRequests = 0;
  const fresh: ReviewEngineState = { enabled: true, model: "new-model", protocol: "ollama", models: [] };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health")) return response({ status: "ok" });
    readyRequests += 1;
    if (readyRequests === 2) return delayed;
    return response({ ...READY, review_engines: { local: readyRequests === 1 ? { enabled: false } : fresh } });
  });
  vi.stubGlobal("fetch", fetchMock);
  try {
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.kind).toBe("healthy"));
    act(() => { void result.current.check(); });
    await waitFor(() => expect(readyRequests).toBe(2));
    act(() => result.current.refreshLocal(fresh));
    expect(result.current.readiness?.review_engines?.local).toEqual(fresh);
    await waitFor(() => expect(readyRequests).toBe(3));
    await act(async () => { resolveOld(response({ ...READY, review_engines: { local: { enabled: true, model: "old-model" } } })); });
    expect(result.current.readiness?.review_engines?.local).toEqual(fresh);
    expect(result.current.kind).toBe("healthy");
  } finally { cleanup(); vi.unstubAllGlobals(); }
});

it("polls visible tabs every 30 seconds, pauses while hidden, and resumes on focus", async () => {
  vi.useFakeTimers();
  let visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility as DocumentVisibilityState);
  const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health") ? response({ status: "ok" }) : response(READY));
  vi.stubGlobal("fetch", fetch);
  try {
    const { unmount } = renderHook(() => useRuntimeHealth());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(fetch).toHaveBeenCalledTimes(4);
    visibility = "hidden";
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(4);
    visibility = "visible";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(fetch).toHaveBeenCalledTimes(6);
    unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetch).toHaveBeenCalledTimes(6);
  } finally {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});


it("classifies an empty compatible corpus as preparation needed and preserves real DB failures", async () => {
  let databaseConnected = true;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health") ? { status: "ok" } : { ...READY, status: "degraded", corpus: { ...READY.corpus, availability: "degraded", database_connected: databaseConnected, documents: 0, chunks: 0, embedded_chunks: 0, bm25_ready: false } }, String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health") ? 200 : 503)));
  const { result, unmount } = renderHook(() => useRuntimeHealth());
  await waitFor(() => expect(result.current.kind).toBe("preparation_needed"));
  expect(result.current.modalVisible).toBe(true);
  act(() => result.current.dismissWarning());
  expect(result.current.modalVisible).toBe(false);
  await act(async () => { await result.current.check(); });
  expect(result.current.kind).toBe("preparation_needed");
  expect(result.current.modalVisible).toBe(false);
  databaseConnected = false;
  await act(async () => { await result.current.check(); });
  expect(result.current.kind).toBe("db_degraded");
  expect(result.current.modalVisible).toBe(true);
  unmount(); vi.unstubAllGlobals();
});

it("refreshes measured model use while an older unloaded-model poll is pending", async () => {
  let resolveOld!: (value: Response) => void;
  let reads = 0;
  const model = { name: "answer", selectable: true, loaded: false, placement: null, cpu_performance: null, size_bytes: 100, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"] };
  const observed = { ...model, loaded: true, placement: "cpu", cpu_performance: { tokens_per_second: 18, measured_at: new Date().toISOString() } };
  const snapshot = (value: typeof model | typeof observed) => ({ ...READY, review_engines: { local: { enabled: true, protocol: "ollama", models: [value] } } });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).replace(/\/?(\?|$)/, "$1").endsWith("/health")) return response({ status: "ok" });
    reads += 1;
    if (reads === 2) return new Promise<Response>((resolve) => { resolveOld = resolve; });
    return response(snapshot(reads === 1 ? model : observed));
  }));
  try {
    const { result } = renderHook(() => useRuntimeHealth());
    await waitFor(() => expect(result.current.kind).toBe("healthy"));
    act(() => { void result.current.check(); });
    await waitFor(() => expect(reads).toBe(2));
    act(() => { void result.current.check(true); });
    await waitFor(() => expect(result.current.readiness?.review_engines?.local.models?.[0]).toEqual(observed));
    await act(async () => resolveOld(response(snapshot(model))));
    expect(result.current.readiness?.review_engines?.local.models?.[0]).toEqual(observed);
  } finally { cleanup(); vi.unstubAllGlobals(); }
});
