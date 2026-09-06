import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, cancelOperatorJob, getCorpusSnapshot, getOperatorJobs, getReadiness, REQUEST_TIMEOUT_MS, streamReview } from "./api";
import { DEFAULT_SESSION_PROFILE } from "./types";

function streamResponse(parts: string[]) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  }), { status: 200, headers: { "content-type": "text/event-stream" } });
}

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses fragmented SSE progress and one terminal report", async () => {
    const fetch = vi.fn().mockResolvedValue(streamResponse([
      "event: node\ndata: {\"node\":\"retr",
      "ieve\",\"evidence_count\":2,\"relevant_count\":0,\"step_count\":0}\n\n",
      "event: report\ndata: {\"status\":\"ok\",\"report\":{\"answer\":\"done\"}}\n\n",
      "event: done\ndata: {}\n\n",
    ]));
    vi.stubGlobal("fetch", fetch);
    const progress: string[] = [];

    const report = await streamReview(
      "question",
      DEFAULT_SESSION_PROFILE,
      null,
      [],
      (event) => progress.push(event.node),
    );

    expect(progress).toEqual(["retrieve"]);
    expect(report.status).toBe("ok");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("fails closed when a stream ends without done", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse([
      "event: report\ndata: {\"status\":\"ok\"}\n\n",
    ])));

    await expect(
      streamReview("question", DEFAULT_SESSION_PROFILE, null, [], () => undefined),
    ).rejects.toThrow("done event");
  });

  it("returns the typed degraded readiness body from HTTP 503", async () => {
    const payload = {
      status: "degraded",
      mode: "runtime",
      admin_mode: "live",
      policy_revision: "2026-09-01",
      models: {},
      review_enabled: false,
      active_review_model: null,
      corpus: { availability: "degraded" },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), {
      status: 503,
      headers: { "content-type": "application/json" },
    })));

    await expect(getReadiness()).resolves.toMatchObject(payload);
  });

  it("surfaces exact validation locations instead of a generic stream failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: "request_validation_failed",
        message: "Request validation failed.",
        details: [{
          location: ["body", "session_profile", "languages"],
          message: "Input should be a valid tuple",
          error_type: "tuple_type",
        }],
      },
    }), { status: 422, headers: { "content-type": "application/json" } })));

    await expect(
      streamReview("question", DEFAULT_SESSION_PROFILE, null, [], () => undefined),
    ).rejects.toThrow("body.session_profile.languages: Input should be a valid tuple");
  });
});


describe("review response body cancellation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([false, true])("cancels the response reader after headers or for an already aborted signal (preaborted=%s)", async (preaborted) => {
    const cancellation = vi.fn();
    const response = new Response(new ReadableStream({ cancel: cancellation }), { headers: { "content-type": "text/event-stream" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const controller = new AbortController();
    const added = vi.spyOn(controller.signal, "addEventListener");
    const removed = vi.spyOn(controller.signal, "removeEventListener");
    if (preaborted) controller.abort();
    const request = streamReview("question", DEFAULT_SESSION_PROFILE, null, [], () => undefined, controller.signal);
    const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
    if (!preaborted) {
      await vi.waitFor(() => expect(response.body?.locked).toBe(true));
      controller.abort();
    }
    await rejected;
    expect(cancellation).toHaveBeenCalledTimes(1);
    for (const [name, listener] of added.mock.calls) expect(removed.mock.calls.some(([removedName, removedListener]) => removedName === name && removedListener === listener)).toBe(true);
    expect(response.body?.locked).toBe(false);
  });

  it("removes the body listener after ordinary completion", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(['event: report\ndata: {"report":{"answer":"done"}}\n\nevent: done\ndata: {}\n\n'])));
    const controller = new AbortController();
    const added = vi.spyOn(controller.signal, "addEventListener");
    const removed = vi.spyOn(controller.signal, "removeEventListener");
    await streamReview("question", DEFAULT_SESSION_PROFILE, null, [], () => undefined, controller.signal);
    for (const [name, listener] of added.mock.calls) expect(removed.mock.calls.some(([removedName, removedListener]) => removedName === name && removedListener === listener)).toBe(true);
  });
});


it("sends no history when the policy is zero", async () => {
  const fetch = vi.fn().mockResolvedValue(streamResponse(['event: report\ndata: {"report":{"answer":"done"}}\n\nevent: done\ndata: {}\n\n']));
  vi.stubGlobal("fetch", fetch);
  try {
    await streamReview("Hi", { ...DEFAULT_SESSION_PROFILE, prompt_policy: { ...DEFAULT_SESSION_PROFILE.prompt_policy, history_turns: 0 } }, null, [{ role: "user", text: "Prior filing" }], () => {});
    expect(JSON.parse(fetch.mock.calls[0][1].body).conversation_history).toEqual([]);
  } finally { vi.unstubAllGlobals(); }
});

describe("request deadlines", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("times out idle GET reads with a request_timeout ApiError", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
    })));
    const outcome = getCorpusSnapshot().then(() => "resolved", (error: unknown) => error);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    const error = await outcome;
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 408, code: "request_timeout" });
  });

  it("does not time out mutations", async () => {
    vi.useFakeTimers();
    let release!: (response: Response) => void;
    let settled = false;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { release = resolve; })));
    const pending = cancelOperatorJob("job-1").then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS * 4);
    expect(settled).toBe(false);
    release(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    await pending;
    expect(settled).toBe(true);
  });

  it("keeps caller aborts as AbortError", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    const pending = getOperatorJobs(controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("reports a non-JSON body as invalid_response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>502 Bad Gateway</html>", { status: 502, headers: { "content-type": "text/html" } })));
    await expect(getCorpusSnapshot()).rejects.toMatchObject({ status: 502, code: "invalid_response" });
  });
});
