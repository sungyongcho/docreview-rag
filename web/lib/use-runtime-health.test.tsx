import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useRuntimeHealth } from "./use-runtime-health";

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
  afterEach(() => vi.unstubAllGlobals());

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
