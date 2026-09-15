import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { Playground } from "./playground";

const HIT = {
  chunk_id: 41, doc_id: "NVDA-FY2024", item: "7", kind: "text", citation: "NVDA FY2024 · Item 7",
  start_char: 120, end_char: 480, source_sha256: "0".repeat(64),
  body: "Data Center revenue grew on Hopper demand.", context_header: "Item 7", score: 0.91,
  section_title: "Management's Discussion and Analysis",
};

describe("Playground", () => {
  it.each(["Preview retrieval", "Preview review"])("shows a policy result for %s without a misleading search result", async (button) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "unknown_issuer", message: "Missing company", path_decision: {
      intent: "document_review", source: "classifier", matched_rule: "classifier_review", rationale: "Company analysis", history_turns: 0,
      selected_scope: "auto", resolved_scope: null, routing_queries: {}, retrieval_query: "SanDisk", scope_outcome: "empty", stopping_stage: "gate", stopping_reason: "unknown_issuer", missing_issuers: ["SanDisk"], suggested_scope: null,
    } } }), { status: 422, headers: { "content-type": "application/json" } })));
    render(<Playground live profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByText("Stopped at stage 1: filing scope unavailable")).toBeVisible();
    expect(screen.getAllByText(/The available filings do not cover SanDisk/).length).toBeGreaterThan(0);
    expect(screen.queryByText("No component rankings were returned.")).toBeNull();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the score stage, component rankings, and fused evidence from a retrieval preview", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/\/?(\?|$)/, "$1");
      let payload: unknown = {};
      if (url.endsWith("/admin/retrieval/preview")) payload = {
        query: JSON.parse(String(init?.body)).query,
        profile: DEFAULT_PROFILE,
        score_stage: "rrf",
        component_rankings: { vector: [41, 77], vector_by_language: {}, lexical: [77, 41, 93], lexical_by_language: { ko: [93] } },
        results: [HIT],
      };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Playground live profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={vi.fn()} />);

    expect(screen.getByRole("textbox", { name: "Playground question" })).toHaveValue("What drove NVIDIA data center revenue growth?");
    expect(screen.queryByRole("heading", { name: "Retrieval preview" })).not.toBeInTheDocument();
    expect(screen.getByText("Advanced search settings").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByLabelText("Strategy")).toBeVisible();
    expect(screen.getByLabelText("candidate_k")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Preview retrieval" }));

    expect(await screen.findByText("Score stage · rrf")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "vector" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "lexical" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "lexical · ko" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /vector · / })).not.toBeInTheDocument();
    expect(screen.getAllByText("77")).toHaveLength(2);
    expect(screen.getAllByText("93")).toHaveLength(2);
    expect(screen.getByText("NVDA FY2024 · Item 7")).toBeInTheDocument();
    expect(screen.getByText("chunk 41 · NVDA-FY2024 · chars 120–480")).toBeInTheDocument();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body)) as Record<string, unknown>;
    expect(body.query).toBe("What drove NVIDIA data center revenue growth?");
    expect(body.profile).toEqual(DEFAULT_PROFILE);
  });

  it("renders the report label, answer, and citations from a review preview", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input).replace(/\/?(\?|$)/, "$1");
      let payload: unknown = {};
      if (url.endsWith("/admin/review/preview")) payload = {
        profile: DEFAULT_PROFILE,
        run: {
          run_id: "run-1", status: "ok", failure: null,
          report: {
            report_kind: "document_review", label: "SUPPORTED",
            answer: "Hopper demand drove Data Center revenue.",
            citations: [{ chunk_id: 41, doc_id: "NVDA-FY2024", citation: "NVDA FY2024 · Item 7", start_char: 120, end_char: 480, source_sha256: "0".repeat(64) }],
            rationale: "Direct statement.", reasons: [],
          },
        },
      };
      return new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } });
    }));
    render(<Playground live profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Preview review" }));

    expect(await screen.findByText("SUPPORTED")).toBeInTheDocument();
    expect(screen.getByText("Hopper demand drove Data Center revenue.")).toBeInTheDocument();
    expect(screen.getByText("NVDA FY2024 · Item 7")).toBeInTheDocument();
  });

  it("searches through the public retrieve endpoint and locks the answer preview in the public build", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ results: [], candidates: [], candidate_token: null, candidate_expires_at: 0, component_rankings: { vector: [1], lexical: [] } }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Playground live={false} profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={vi.fn()} />);

    const review = screen.getByRole("button", { name: "Preview review" });
    expect(review).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(review);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Preview retrieval" }));
    await screen.findByText("Retrieval preview");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/retrieve");
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("/admin/");
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body)).session_profile.retrieval_preset).toBe("custom");
  });
});


it("sends the exact public scope and disables empty-scope retrieval", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ results: [], candidates: [], candidate_token: null, resolved_scope: null }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const props = { live: false, profile: DEFAULT_PROFILE, onProfileChange: vi.fn(), onOpenSnapshots: vi.fn(), publicProfile: { ...DEFAULT_SESSION_PROFILE, doc_ids: ["NVDA-2023", "AMD-2024"] } };
  const view = render(<Playground {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Preview retrieval" }));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).session_profile.doc_ids).toEqual(["NVDA-2023", "AMD-2024"]);
  await screen.findByRole("button", { name: "Preview retrieval" });
  view.rerender(<Playground {...props} publicScopeBlocked />);
  expect(screen.getByRole("button", { name: "Preview retrieval" })).toBeDisabled();
  cleanup(); vi.unstubAllGlobals();
});
