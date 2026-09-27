import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BROWSER_REQUESTS_KEY, configureBrowserRequestLimits, getBrowserRequestAllowance, recordBrowserRequest, subscribeBrowserRequestLimits } from "./browser-request-limits";
import { configureBrowserStorage, persistentBrowserStorage, subscribeStorageWarnings } from "./storage";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-27T12:00:00Z"));
  configureBrowserStorage("prod");
  localStorage.clear();
  configureBrowserRequestLimits({ per_minute: 10, per_day: 50 });
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); configureBrowserRequestLimits(undefined); configureBrowserStorage(undefined); localStorage.clear(); });

it("rejects the eleventh dispatch without extending the minute window and recovers exactly at 60 seconds", () => {
  for (let index = 0; index < 10; index++) recordBrowserRequest();
  const stored = localStorage.getItem(BROWSER_REQUESTS_KEY);
  vi.advanceTimersByTime(59_999);
  expect(() => recordBrowserRequest()).toThrow(expect.objectContaining({ code: "browser_rate_limited", failure: { code: "browser_rate_limited", retry_after_seconds: 1 } }));
  expect(localStorage.getItem(BROWSER_REQUESTS_KEY)).toBe(stored);
  vi.advanceTimersByTime(1);
  recordBrowserRequest();
  expect(getBrowserRequestAllowance()).toMatchObject({ remaining_minute: 9, remaining_day: 39 });
});

it("rejects the fifty-first request in a rolling day and retains no more than fifty timestamps", () => {
  for (let batch = 0; batch < 5; batch++) {
    for (let index = 0; index < 10; index++) recordBrowserRequest();
    vi.advanceTimersByTime(60_000);
  }
  expect(() => recordBrowserRequest()).toThrow(expect.objectContaining({ code: "browser_rate_limited" }));
  const timestamps = JSON.parse(persistentBrowserStorage().getItem(BROWSER_REQUESTS_KEY)!);
  expect(timestamps).toHaveLength(50);
  expect(timestamps.every((value: unknown) => typeof value === "number")).toBe(true);
  vi.setSystemTime(new Date("2026-09-28T11:59:59.999Z"));
  expect(getBrowserRequestAllowance()?.retry_after_seconds).toBe(1);
  vi.advanceTimersByTime(1);
  expect(getBrowserRequestAllowance()?.remaining_day).toBe(10);
  recordBrowserRequest();
  expect(JSON.parse(persistentBrowserStorage().getItem(BROWSER_REQUESTS_KEY)!)).toHaveLength(41);
});

it("rereads persisted timestamps after policy reload and observes another tab or storage clear", () => {
  recordBrowserRequest();
  configureBrowserRequestLimits(undefined);
  configureBrowserRequestLimits({ per_minute: 10, per_day: 50 });
  expect(getBrowserRequestAllowance()?.remaining_minute).toBe(9);
  const listener = vi.fn();
  const unsubscribe = subscribeBrowserRequestLimits(listener);
  persistentBrowserStorage().setItem(BROWSER_REQUESTS_KEY, JSON.stringify([Date.now(), Date.now()]));
  window.dispatchEvent(new StorageEvent("storage", { key: BROWSER_REQUESTS_KEY, newValue: localStorage.getItem(BROWSER_REQUESTS_KEY) }));
  expect(listener).toHaveBeenCalledOnce();
  expect(getBrowserRequestAllowance()?.remaining_minute).toBe(8);
  localStorage.clear();
  window.dispatchEvent(new StorageEvent("storage", { key: null }));
  expect(listener).toHaveBeenCalledTimes(2);
  expect(getBrowserRequestAllowance()?.remaining_minute).toBe(10);
  unsubscribe();
});

it.each(["prod", "dev"] as const)("uses the existing memory fallback and storage warning on %s public surfaces", (environment) => {
  configureBrowserStorage(environment);
  const warning = vi.fn();
  const unsubscribe = subscribeStorageWarnings(warning);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("No storage", "QuotaExceededError"); });
  for (let index = 0; index < 10; index++) recordBrowserRequest();
  expect(getBrowserRequestAllowance()?.remaining_minute).toBe(0);
  expect(() => recordBrowserRequest()).toThrow(expect.objectContaining({ code: "browser_rate_limited" }));
  expect(warning).toHaveBeenCalledWith(expect.objectContaining({ reason: "quota" }));
  unsubscribe();
});

it("does not charge a request cancelled before dispatch or invent policy while it is loading", () => {
  const aborted = new AbortController();
  aborted.abort();
  expect(() => recordBrowserRequest(aborted.signal)).toThrow(expect.objectContaining({ name: "AbortError" }));
  expect(localStorage.getItem(BROWSER_REQUESTS_KEY)).toBeNull();
  configureBrowserRequestLimits(null);
  expect(() => recordBrowserRequest()).toThrow("Server execution limits could not be loaded");
  expect(localStorage.getItem(BROWSER_REQUESTS_KEY)).toBeNull();
});
