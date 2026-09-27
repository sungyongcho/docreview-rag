import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, getReleaseLimits, retrieveEvidence, streamReview } from "./api";
import { BROWSER_REQUESTS_KEY, configureBrowserRequestLimits, getBrowserRequestAllowance } from "./browser-request-limits";
import { DEFAULT_SESSION_PROFILE } from "./types";
import { configureBrowserStorage, persistentBrowserStorage } from "./storage";
import { notificationErrorMessage } from "./notification-registry";
import { translate } from "./i18n";

beforeEach(() => { localStorage.clear(); configureBrowserStorage("prod"); configureBrowserRequestLimits({ per_minute: 10, per_day: 50 }); });
afterEach(() => { vi.unstubAllGlobals(); configureBrowserRequestLimits(undefined); configureBrowserStorage(undefined); localStorage.clear(); });

/** Supply a complete stream with several progress frames to verify per-request accounting. */
function streamResponse(): Response {
  return new Response('event: node\ndata: {"node":"retrieve"}\n\nevent: node\ndata: {"node":"report"}\n\nevent: report\ndata: {"status":"ok"}\n\nevent: done\ndata: {}\n\n', { headers: { "content-type": "text/event-stream" } });
}

it("charges public search and streaming at one shared dispatch boundary without transmitting timestamps", async () => {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => url.endsWith("/review/stream/") ? streamResponse() : new Response("{}"));
  vi.stubGlobal("fetch", fetchMock);
  for (let index = 0; index < 5; index++) {
    await retrieveEvidence("query", DEFAULT_SESSION_PROFILE);
    await streamReview("query", DEFAULT_SESSION_PROFILE, null, [], vi.fn());
  }
  expect(getBrowserRequestAllowance()).toMatchObject({ remaining_minute: 0, remaining_day: 40 });
  await expect(retrieveEvidence("blocked", DEFAULT_SESSION_PROFILE)).rejects.toMatchObject({ status: 429, code: "browser_rate_limited" });
  expect(fetchMock).toHaveBeenCalledTimes(10);
  for (const [, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
    expect(Object.keys(JSON.parse(String(init.body)))).not.toContain("request_times");
    expect(String(init.body)).not.toContain(BROWSER_REQUESTS_KEY);
    expect(new Headers(init.headers).has("X-Forwarded-For")).toBe(false);
  }
  await getReleaseLimits();
  expect(getBrowserRequestAllowance()?.remaining_day).toBe(40);
});

it("retains charges after network failure, validation failure and cancellation after dispatch without retry", async () => {
  const controller = new AbortController();
  const fetchMock = vi.fn()
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValueOnce(new Response('{"error":{"code":"request_validation_failed","message":"invalid"}}', { status: 422 }))
    .mockImplementationOnce(async () => { controller.abort(); throw new DOMException("Cancelled", "AbortError"); });
  vi.stubGlobal("fetch", fetchMock);
  await expect(retrieveEvidence("one", DEFAULT_SESSION_PROFILE)).rejects.toThrow("offline");
  await expect(retrieveEvidence("two", DEFAULT_SESSION_PROFILE)).rejects.toMatchObject({ status: 422 });
  await expect(streamReview("three", DEFAULT_SESSION_PROFILE, null, [], vi.fn(), controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(getBrowserRequestAllowance()?.remaining_day).toBe(47);
  await expect(streamReview("cancelled before sending", DEFAULT_SESSION_PROFILE, null, [], vi.fn(), controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(JSON.parse(persistentBrowserStorage().getItem(BROWSER_REQUESTS_KEY)!)).toHaveLength(3);
});

it.each(["", "Request body too large", "<html>too large</html>", '{"error":{"code":"other"}}'])("recognizes proxy 413 for JSON and streaming regardless of response body %j", async (body) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 413 })));
  for (const send of [() => retrieveEvidence("query", DEFAULT_SESSION_PROFILE), () => streamReview("query", DEFAULT_SESSION_PROFILE, null, [], vi.fn())]) {
    await expect(send()).rejects.toMatchObject({ status: 413, code: "request_too_large", message: "The execution request is too large. Shorten the question or conversation and try again." });
  }
});

it.each([
  ["browser_rate_limited", "This browser has reached its execution request limit.", "이 브라우저의 실행 요청 한도에 도달했습니다."],
  ["rate_limited", "The server request limit shared by multiple visitors is reached.", "여러 방문자가 공유하는 서버 요청 한도에 도달했습니다."],
  ["daily_cost_limit", "The global AI cost limit is reached.", "전체 AI 비용 한도에 도달했습니다."],
])("distinguishes %s guidance and retry timing in both locales", (code, en, ko) => {
  const message = notificationErrorMessage(new ApiError(429, code, "server text", undefined, { code, retry_after_seconds: 12 }));
  expect(message).toBe(`${en} Retry in 12 seconds.`);
  expect(translate("ko", message)).toBe(`${ko} 12초 후 다시 시도하세요.`);
});

it("preserves the server 429 code, details and Retry-After without replacing browser counters", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response('{"error":{"code":"rate_limited","message":"shared","retry_after_seconds":1}}', { status: 429, headers: { "Retry-After": "31" } })));
  await expect(retrieveEvidence("query", DEFAULT_SESSION_PROFILE)).rejects.toMatchObject({ code: "rate_limited", failure: { retry_after_seconds: 31 } });
  expect(getBrowserRequestAllowance()?.remaining_minute).toBe(9);
});
