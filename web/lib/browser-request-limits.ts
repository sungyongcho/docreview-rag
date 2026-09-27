import { persistentBrowserStorage, subscribeStorageRestored } from "./storage";
import type { ReleaseLimits } from "./types";

export const BROWSER_REQUESTS_KEY = "docreview:request-times:v1";
const CHANGED_EVENT = "docreview:request-times-changed";
const MINUTE_MS = 60_000;
const DAY_MS = 24 * 60 * MINUTE_MS;
const MAX_TIMESTAMPS = 50;
type RequestPolicy = Pick<ReleaseLimits, "per_minute" | "per_day">;
let policy: RequestPolicy | null | undefined;

export interface BrowserRequestAllowance {
  per_minute: number;
  per_day: number;
  remaining_minute: number;
  remaining_day: number;
  retry_after_seconds: number;
}

/** A local denial has its own code and never reaches the server. */
export class BrowserRateLimitError extends Error {
  readonly code = "browser_rate_limited";
  readonly failure: { code: string; retry_after_seconds: number };

  constructor(seconds: number) {
    super("This browser has reached its execution request limit.");
    this.failure = { code: this.code, retry_after_seconds: seconds };
  }
}

/** Select public policy from the existing /limits load; undefined exempts the admin surface. */
export function configureBrowserRequestLimits(value: RequestPolicy | null | undefined): void {
  if (value && (![value.per_minute, value.per_day].every(count => Number.isInteger(count) && count > 0) || value.per_day > MAX_TIMESTAMPS)) {
    throw new Error("Public request policy unavailable");
  }
  policy = value ? { per_minute: value.per_minute, per_day: value.per_day } : value;
  changed();
}

/** Notify subscribers in this tab; native storage events carry changes to other tabs. */
function changed(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGED_EVENT));
}

/** Retain only timestamps inside the rolling day, with no identity or request contents. */
function requestTimes(now: number): number[] {
  if (typeof window === "undefined") return [];
  const store = persistentBrowserStorage();
  const raw = store.getItem(BROWSER_REQUESTS_KEY);
  const parsed: unknown = JSON.parse(raw ?? "[]");
  const times = (Array.isArray(parsed) ? parsed : []).filter((time): time is number => typeof time === "number" && Number.isFinite(time) && time > now - DAY_MS).sort((a, b) => a - b).slice(-MAX_TIMESTAMPS);
  if (raw !== null && JSON.stringify(times) !== raw) store.setItem(BROWSER_REQUESTS_KEY, JSON.stringify(times));
  return times;
}

/** Calculate both windows from the same retained record without mixing server balances. */
function allowance(times: number[], now: number, limits: RequestPolicy): BrowserRequestAllowance {
  const minute = times.filter(time => time > now - MINUTE_MS);
  const minuteWait = minute.length >= limits.per_minute ? minute[minute.length - limits.per_minute] + MINUTE_MS - now : 0;
  const dayWait = times.length >= limits.per_day ? times[times.length - limits.per_day] + DAY_MS - now : 0;
  return { ...limits, remaining_minute: Math.max(0, limits.per_minute - minute.length), remaining_day: Math.max(0, limits.per_day - times.length), retry_after_seconds: Math.max(0, Math.ceil(Math.max(minuteWait, dayWait) / 1000)) };
}

/** Read the browser balance, pruning expired entries on access. */
export function getBrowserRequestAllowance(now = Date.now()): BrowserRequestAllowance | null {
  return policy ? allowance(requestTimes(now), now, policy) : null;
}

/** Check before changing a draft; transport rechecks immediately before recording and sending. */
export function assertBrowserRequestAllowed(): void {
  if (policy === null) throw new Error("Server execution limits could not be loaded. Browser defaults are not the applied policy.");
  const current = getBrowserRequestAllowance();
  if (current && current.retry_after_seconds > 0) throw new BrowserRateLimitError(current.retry_after_seconds);
}

/** Charge exactly once at dispatch, with no await between the check, storage write and fetch. */
export function recordBrowserRequest(signal?: AbortSignal | null): void {
  signal?.throwIfAborted();
  assertBrowserRequestAllowed();
  if (!policy) return;
  const now = Date.now();
  persistentBrowserStorage().setItem(BROWSER_REQUESTS_KEY, JSON.stringify([...requestTimes(now), now].slice(-MAX_TIMESTAMPS)));
  changed();
}

/** Observe same-tab dispatch, settings restore and another tab's writes or clearing. */
export function subscribeBrowserRequestLimits(listener: () => void): () => void {
  const stored = (event: StorageEvent) => { if (event.key === BROWSER_REQUESTS_KEY || event.key === null) listener(); };
  window.addEventListener(CHANGED_EVENT, listener);
  window.addEventListener("storage", stored);
  const restored = subscribeStorageRestored(listener);
  return () => { window.removeEventListener(CHANGED_EVENT, listener); window.removeEventListener("storage", stored); restored(); };
}
