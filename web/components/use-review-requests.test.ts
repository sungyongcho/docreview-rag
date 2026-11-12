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

/** Mount the hook with one empty conversation, as the review shell does. */
function renderRequests(developer: boolean) {
  return renderHook(() => {
    const [query, setQuery] = useState("Revenue?");
    const [conversations, setConversations] = useState(() => [newConversation(DEFAULT_SESSION_PROFILE)]);
    const reviewAbort = useRef<AbortController | null>(null);
    const requests = useReviewRequests({
      active: conversations[0],
      activeId: conversations[0].id,
      sessionProfile: DEFAULT_SESSION_PROFILE,
      localModel: null,
      sendBlocked: false,
      developer,
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
}

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
  const { result } = renderRequests(true);

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

const HIT = {
  chunk_id: 7, doc_id: "AMD-FY2025", item: "7", section_title: "MD&A", kind: "text", citation: "AMD FY2025 · Item 7",
  start_char: 0, end_char: 80, source_sha256: "a".repeat(64), body: "Revenue grew.", context_header: "AMD FY2025 · Item 7", score: 0.9,
};
const PENDING_HOLD = { registry: "sec", issuer: "AMD", fiscal_year: 2025, reason: "amendment_pending", items: [] };
const WITHHELD_HOLD = { registry: "sec", issuer: "NVDA", fiscal_year: 2024, reason: "item_withheld", items: ["7"] };

/** Encode review stream frames in the order the server would send them. */
function reviewStream(frames: [string, unknown][]): Response {
  const body = frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

/** Run one submitted question to its terminal assistant message. */
async function submitted(developer: boolean) {
  const { result } = renderRequests(developer);
  await act(async () => { await result.current.submit(); });
  return result.current.conversations[0].messages[1];
}

it("keeps the holds a search reported when the candidates are shown without an answer", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (!String(url).endsWith("/review/stream/")) throw new Error(`Unexpected request ${url}`);
    return Promise.resolve(reviewStream([
      ["candidates", { results: [], candidates: [HIT], candidate_token: "token", evidence_holds: [PENDING_HOLD] }],
      ["error", { error: { code: "provider_unavailable", message: "Provider unavailable" } }],
    ]));
  }));

  const assistant = await submitted(false);

  expect(assistant.evidenceLabel).toBe("Retrieved candidates — answer not generated");
  expect(assistant.evidence).toEqual([HIT]);
  expect(assistant.evidenceHolds).toEqual([PENDING_HOLD]);
});

it("keeps the holds of the developer's evidence-only fallback search", async () => {
  configureBrowserStorage("dev");
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (String(url).endsWith("/review/stream/")) {
      return Promise.resolve(new Response(
        JSON.stringify({ error: { code: "provider_unavailable", message: "Provider unavailable" } }),
        { status: 503, headers: { "content-type": "application/json" } },
      ));
    }
    if (String(url).endsWith("/retrieve/")) {
      return Promise.resolve(new Response(
        JSON.stringify({ results: [], candidates: [], candidate_token: null, resolved_scope: null, evidence_holds: [PENDING_HOLD] }),
        { status: 200, headers: { "content-type": "application/json" } },
      ));
    }
    throw new Error(`Unexpected request ${url}`);
  }));

  const assistant = await submitted(true);

  expect(assistant.evidence).toEqual([]);
  expect(assistant.evidenceHolds).toEqual([PENDING_HOLD]);
});

it("lets a finished report state its own holds instead of the search's", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (!String(url).endsWith("/review/stream/")) throw new Error(`Unexpected request ${url}`);
    return Promise.resolve(reviewStream([
      ["candidates", { results: [], candidates: [HIT], candidate_token: "token", evidence_holds: [PENDING_HOLD] }],
      ["report", { run_id: "run-1", status: "ok", report: {
        report_kind: "document_review", label: "NOT_IN_DOCS", answer: "NOT_IN_DOCS", citations: [], rationale: "No evidence.",
        reasons: [{ code: "evidence_held", holds: [WITHHELD_HOLD] }],
      } }],
      ["done", {}],
    ]));
  }));

  const assistant = await submitted(false);

  expect(assistant.text).toBe("No evidence.");
  expect(assistant.evidenceHolds).toEqual([WITHHELD_HOLD]);
});
