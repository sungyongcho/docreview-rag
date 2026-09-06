import { afterEach, describe, expect, it, vi } from "vitest";

import { getReadiness, streamReview } from "./api";
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
