import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_PROFILE } from "@/lib/types";
import { Playground } from "./playground";

const HIT = {
  chunk_id: 41, doc_id: "NVDA-FY2024", item: "7", kind: "text", citation: "NVDA FY2024 · Item 7",
  start_char: 120, end_char: 480, source_sha256: "0".repeat(64),
  body: "Data Center revenue grew on Hopper demand.", context_header: "Item 7", score: 0.91,
};

describe("Playground", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders the score stage, component rankings, and fused evidence from a retrieval preview", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
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
      const url = String(input);
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

  it("shows the locked state and opens Snapshots in the public build", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const onOpenSnapshots = vi.fn();
    render(<Playground live={false} profile={DEFAULT_PROFILE} onProfileChange={vi.fn()} onOpenSnapshots={onOpenSnapshots} />);

    expect(screen.getByText("Playground runs on the local operator build.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Snapshots" }));
    expect(onOpenSnapshots).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
