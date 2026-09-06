import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useRuntimeHealth } from "./use-runtime-health";
import * as api from "./api";
import type { Readiness, ReviewEngineState } from "./types";

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
    const fetch = vi.fn(async (input: RequestInfo | URL) => response(String(input).endsWith("/health") ? { status: "ok" } : READY));
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
      if (String(input).endsWith("/health")) return response({ status: "ok" });
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

  it("uses only the explicit public preview adapter after liveness succeeds", async () => {
    const preview = { ...READY, environment: "prod", admin_mode: "readonly", corpus: { ...READY.corpus, documents: 0, chunks: null, embedded_chunks: null } } as Readiness;
    const readPreview = vi.spyOn(api, "getProductionPreviewReadiness").mockResolvedValue(preview);
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toMatch(/\/health$/);
      return response({ status: "ok" });
    });
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useRuntimeHealth({ publicPreview: true }));
    await waitFor(() => expect(result.current.readiness).toBe(preview));
    expect(readPreview).toHaveBeenCalledTimes(1);
    expect(readPreview.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
    expect(fetch).toHaveBeenCalledTimes(1);
    act(() => result.current.refreshLocal({ enabled: true, model: "private-dev-model" }));
    expect(result.current.readiness).toBe(preview);
    expect(readPreview).toHaveBeenCalledTimes(1);
  });

  it("separates healthy, DB-degraded, and dismissed warning state", async () => {
    let degraded = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/health")) return response({ status: "ok", mode: "runtime" });
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

  it("treats an unreachable API as a non-dismissible modal issue", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const { result } = renderHook(() => useRuntimeHealth());

    await waitFor(() => expect(result.current.kind).toBe("api_down"));
    expect(result.current.modalVisible).toBe(true);
    act(() => result.current.dismissWarning());
    expect(result.current.modalVisible).toBe(true);
  });

  it("rechecks when the browser returns online", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) => (
      String(input).endsWith("/health")
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
    if (String(input).endsWith("/health")) return response({ status: "ok" });
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
  const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/health") ? response({ status: "ok" }) : response(READY));
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
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).endsWith("/health") ? { status: "ok" } : { ...READY, status: "degraded", corpus: { ...READY.corpus, availability: "degraded", database_connected: databaseConnected, documents: 0, chunks: 0, embedded_chunks: 0, bm25_ready: false } }, String(input).endsWith("/health") ? 200 : 503)));
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
