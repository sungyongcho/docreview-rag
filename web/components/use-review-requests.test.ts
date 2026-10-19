import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { useReviewRequests } from "@/components/use-review-requests";
import { configureBrowserRequestLimits } from "@/lib/browser-request-limits";
import { configureBrowserStorage, newConversation } from "@/lib/storage";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";

vi.mock("@/components/notifications", () => ({ useNotifications: () => ({ notify: vi.fn() }) }));
vi.mock("@/lib/i18n", () => ({ useI18n: () => ({ t: (message: string) => message }) }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  configureBrowserStorage(undefined);
  configureBrowserRequestLimits(undefined);
  localStorage.clear();
});

it("lets Stop cancel the developer evidence fallback and records a cancelled outcome", async () => {
  configureBrowserStorage("dev");
  let fallbackSignal: AbortSignal | null | undefined;
  vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
    if (String(url).endsWith("/review/stream/")) {
      return Promise.resolve(new Response(
        JSON.stringify({ error: { code: "provider_unavailable", message: "Provider unavailable" } }),
        { status: 503, headers: { "content-type": "application/json" } },
      ));
    }
    if (String(url).endsWith("/retrieve/")) {
      fallbackSignal = init.signal;
      // Like a real fetch, a pending request settles only through its abort signal.
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("Request cancelled", "AbortError")));
      });
    }
    throw new Error(`Unexpected request ${url}`);
  }));
  const { result } = renderHook(() => {
    const [query, setQuery] = useState("Revenue?");
    const [conversations, setConversations] = useState(() => [newConversation(DEFAULT_SESSION_PROFILE)]);
    const reviewAbort = useRef<AbortController | null>(null);
    const requests = useReviewRequests({
      active: conversations[0],
      activeId: conversations[0].id,
      sessionProfile: DEFAULT_SESSION_PROFILE,
      localModel: null,
      sendBlocked: false,
      developer: true,
      view: "review",
      query,
      setQuery,
      setConversations,
      reviewAbort,
      onReviewStarted: vi.fn(),
      setDailyBudgetResetAt: vi.fn(),
      checkRuntimeHealth: vi.fn().mockResolvedValue(undefined),
    });
    return { ...requests, reviewAbort, conversations };
  });

  let pending!: Promise<void>;
  act(() => { pending = result.current.submit(); });
  await waitFor(() => expect(fallbackSignal).toBeDefined());
  await act(async () => { result.current.reviewAbort.current!.abort(); await pending; });

  expect(fallbackSignal?.aborted).toBe(true);
  expect(result.current.busy).toBe(false);
  const assistant = result.current.conversations[0].messages[1];
  expect(assistant.text).toBe("Request cancelled");
  expect(assistant.execution?.outcome).toBe("cancelled");
});
