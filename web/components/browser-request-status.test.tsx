import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BROWSER_REQUESTS_KEY, configureBrowserRequestLimits, recordBrowserRequest } from "@/lib/browser-request-limits";
import { configureBrowserStorage, newConversation } from "@/lib/storage";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { BrowserRequestStatus } from "./browser-request-status";
import { Playground } from "./playground";
import { useReviewRequests } from "./use-review-requests";

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-09-27T12:00:00Z")); localStorage.clear(); configureBrowserStorage("prod"); configureBrowserRequestLimits({ per_minute: 10, per_day: 50 }); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); configureBrowserRequestLimits(undefined); configureBrowserStorage(undefined); localStorage.clear(); });

it("updates browser counts across tabs, displays a countdown and permits sending when the minute expires", async () => {
  render(<Playground live={false} profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={vi.fn()} />);
  const question = screen.getByRole("textbox", { name: "Playground question" });
  fireEvent.change(question, { target: { value: "Preserve my next question" } });
  act(() => {
    localStorage.setItem(BROWSER_REQUESTS_KEY, JSON.stringify({ version: 1, value: JSON.stringify(Array(10).fill(Date.now())) }));
    window.dispatchEvent(new StorageEvent("storage", { key: BROWSER_REQUESTS_KEY }));
  });
  expect(screen.getByRole("button", { name: "Preview retrieval" })).toBeDisabled();
  expect(screen.getByText(/Retry in 60 seconds/)).toBeVisible();
  expect(question).toHaveValue("Preserve my next question");
  await act(async () => { await vi.advanceTimersByTimeAsync(59_000); });
  expect(screen.getByText(/Retry in 1 seconds/)).toBeVisible();
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(screen.getByRole("button", { name: "Preview retrieval" })).toBeEnabled();
  expect(screen.queryByText(/Retry in/)).toBeNull();
  expect(screen.getByText(/Minute 10\/10/)).toHaveTextContent("Rolling 24 hours 40/50");
});

it("preserves chat input and transcript when the transport preflight denies a request", async () => {
  for (let index = 0; index < 10; index++) recordBrowserRequest();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => {
    const [query, setQuery] = useState("  Keep my exact input  ");
    const [conversations, setConversations] = useState(() => [newConversation(DEFAULT_SESSION_PROFILE)]);
    const requests = useReviewRequests({ active: conversations[0], activeId: conversations[0].id, sessionProfile: DEFAULT_SESSION_PROFILE, localModel: null, sendBlocked: false, developer: false, view: "review", query, setQuery, setConversations, reviewAbort: useRef(null), onReviewStarted: vi.fn(), setDailyBudgetResetAt: vi.fn(), checkRuntimeHealth: vi.fn() });
    return { query, conversations, submit: requests.submit };
  });
  await act(async () => { await result.current.submit(); });
  expect(result.current.query).toBe("  Keep my exact input  ");
  expect(result.current.conversations[0].messages).toEqual([]);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("uses loaded policy numbers for browser counts without showing server remaining values", () => {
  configureBrowserRequestLimits({ per_minute: 3, per_day: 7 });
  recordBrowserRequest();
  render(<BrowserRequestStatus />);
  expect(screen.getByText(/Execution requests remaining in this browser/)).toHaveTextContent("Minute 2/3 · Rolling 24 hours 6/7");
});
