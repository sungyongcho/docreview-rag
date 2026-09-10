import { afterEach, expect, it, vi } from "vitest";
import { requestFetch } from "./http-request";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("preserves caller headers, bodies and streaming responses without preview policy", async () => {
  const response = new Response("event: done\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } });
  const fetch = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetch);
  const result = await requestFetch("/review/stream", { method: "POST", headers: { "X-Custom": "value" }, body: "{}" });
  expect(result).toBe(response);
  const init = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1];
  expect(init.method).toBe("POST");
  expect(init.body).toBe("{}");
  expect(new Headers(init.headers).get("X-Custom")).toBe("value");
  expect(new Headers(init.headers).has("X-DocReview-Public")).toBe(false);
});

it("enforces the deadline through stalled response body delivery", async () => {
  vi.useFakeTimers();
  const stalled = new Response(new ReadableStream({ start() {} }));
  vi.stubGlobal("fetch", vi.fn(async () => stalled));
  const result = requestFetch("/ready", { timeoutMs: 5_000 });
  const rejected = expect(result).rejects.toMatchObject({ name: "TimeoutError" });
  await vi.advanceTimersByTimeAsync(5_000);
  await rejected;
  expect(vi.getTimerCount()).toBe(0);
});

it("propagates a caller abort while fetching and removes the deadline", async () => {
  vi.useFakeTimers();
  const caller = new AbortController();
  vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal!.addEventListener("abort", () => reject(init.signal!.reason));
  })));
  const result = requestFetch("/admin/documents", { signal: caller.signal, timeoutMs: 5_000 });
  const rejected = expect(result).rejects.toMatchObject({ name: "AbortError" });
  caller.abort();
  await rejected;
  expect(vi.getTimerCount()).toBe(0);
});

it("retains bodyless responses and surfaces HTTP errors for the API caller", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response("limited", { status: 429, headers: { "Retry-After": "60" } })));
  expect((await requestFetch("/admin/jobs/1", { method: "DELETE", timeoutMs: 5_000 })).status).toBe(204);
  const limited = await requestFetch("/review", { method: "POST", timeoutMs: 5_000 });
  expect(limited.status).toBe(429);
  expect(limited.headers.get("Retry-After")).toBe("60");
  expect(await limited.text()).toBe("limited");
});
