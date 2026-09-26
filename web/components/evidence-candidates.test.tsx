import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvidenceCandidates } from "./evidence-candidates";
import type { ChatMessage, EvidenceHit } from "@/lib/types";

const MDA = "Management's Discussion and Analysis";

function hit(index: number, overrides: Partial<EvidenceHit> = {}): EvidenceHit {
  return {
    chunk_id: index, doc_id: "NVDA-FY2024", item: String(index), section_title: `Title ${index}`, kind: "text",
    citation: `NVDA FY2024 · Item ${index}`, start_char: index * 100, end_char: index * 100 + 80, source_sha256: "0".repeat(64),
    body: `Body ${index}`, context_header: `NVDA FY2024 · Item ${index} · Title ${index}`, score: 1 - index / 100,
    ...overrides,
  };
}

function hits(count: number): EvidenceHit[] {
  return Array.from({ length: count }, (_, index) => hit(index + 1));
}

function message(evidence: EvidenceHit[], overrides: Partial<ChatMessage> = {}): ChatMessage {
  return { id: "m1", role: "assistant", text: "Answer", evidence, candidateToken: "token", pinnedChunkIds: [], excludedChunkIds: [], ...overrides };
}

/** Render the controlled view; the shell owns pin/exclude updates. */
function EvidenceView({ initial, busy = false, onMark = () => undefined, onUseSelected = () => undefined }: { initial: ChatMessage; busy?: boolean; onMark?: (chunkId: number, mode: "pin" | "exclude") => void; onUseSelected?: () => void }) {
  return <details open><summary>Retrieved evidence candidates</summary><EvidenceCandidates message={initial} busy={busy} onMark={onMark} onUseSelected={onUseSelected} /></details>;
}

function card(heading: string): HTMLElement {
  const article = screen.getByRole("button", { name: heading }).closest("article");
  if (!article) throw new Error(`no card for ${heading}`);
  return article;
}

describe("evidence candidates", () => {
  afterEach(cleanup);

  it("renders collapsed section-titled cards and expands one on demand", () => {
    render(<EvidenceView initial={message([hit(1, { section_title: MDA }), hit(2), hit(3)])} />);

    const toggle = screen.getByRole("button", { name: `Item 1 - (${MDA})` });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).not.toHaveAttribute("aria-controls");
    expect(toggle).toHaveAttribute("title", "NVDA FY2024 · Item 1");
    expect(screen.queryByText("Body 1")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1–3 of 3")).toBeInTheDocument();
    expect(screen.getByText("0 pinned · 0 excluded")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(within(card("Item 2 - (Title 2)")).getByText("NVDA-FY2024")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const body = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(body).not.toBeNull();
    expect(within(body as HTMLElement).getByText("Body 1")).toBeVisible();
    expect(within(body as HTMLElement).getByText("NVDA FY2024 · Item 1")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByText("Body 1")).not.toBeInTheDocument();
  });

  it("opens pinned cards by default and leaves others collapsed", () => {
    render(<EvidenceView initial={message(hits(3), { pinnedChunkIds: [2] })} />);

    expect(screen.getByText("Body 2")).toBeVisible();
    expect(screen.queryByText("Body 1")).not.toBeInTheDocument();
    expect(within(card("Item 2 - (Title 2)")).getByRole("button", { name: "Pin" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 pinned · 0 excluded")).toBeInTheDocument();
  });

  it("expands and collapses every card across pages", () => {
    render(<EvidenceView initial={message(hits(12))} />);

    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(screen.getAllByText(/^Body \d+$/)).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Body 11")).toBeVisible();
    expect(screen.getByText("Body 12")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.queryByText(/^Body \d+$/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(screen.queryByText(/^Body \d+$/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Item 1 - (Title 1)" })).toHaveAttribute("aria-expanded", "false");
  });

  it("pages through candidates and keeps pin and exclude state across pages", () => {
    const onUseSelected = vi.fn();
    const onMark = vi.fn();
    const evidence = hits(12);
    const view = render(<EvidenceView initial={message(evidence)} onMark={onMark} onUseSelected={onUseSelected} />);

    expect(screen.getByText("Showing 1–5 of 12")).toBeInTheDocument();
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Review again with selected evidence" })).not.toBeInTheDocument();

    fireEvent.click(within(card("Item 1 - (Title 1)")).getByRole("button", { name: "Pin" }));
    expect(onMark).toHaveBeenLastCalledWith(1, "pin");
    view.rerender(<EvidenceView initial={message(evidence, { pinnedChunkIds: [1] })} onMark={onMark} onUseSelected={onUseSelected} />);
    expect(screen.getByText("1 pinned · 0 excluded")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review again with selected evidence" }));
    expect(onUseSelected).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("2/3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Showing 11–12 of 12")).toBeInTheDocument();
    expect(screen.getByText("3/3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Item 1 - (Title 1)" })).not.toBeInTheDocument();

    fireEvent.click(within(card("Item 12 - (Title 12)")).getByRole("button", { name: "Exclude" }));
    expect(onMark).toHaveBeenLastCalledWith(12, "exclude");
    view.rerender(<EvidenceView initial={message(evidence, { pinnedChunkIds: [1], excludedChunkIds: [12] })} onMark={onMark} onUseSelected={onUseSelected} />);
    expect(within(card("Item 12 - (Title 12)")).getByRole("button", { name: "Exclude" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 pinned · 1 excluded")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(within(card("Item 1 - (Title 1)")).getByRole("button", { name: "Pin" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 pinned · 1 excluded")).toBeInTheDocument();
  });

  it("falls back to the citation label without a section title and does not repeat DART titles", () => {
    // A conversation saved before the field existed carries no `section_title` at all.
    const legacy = Object.fromEntries(
      Object.entries(hit(3, { citation: "NVDA FY2023 · Item 7" })).filter(([key]) => key !== "section_title"),
    ) as EvidenceHit;
    render(<EvidenceView initial={message([
      hit(1, { citation: "NVDA FY2020 · Item 15", section_title: null, kind: "table" }),
      hit(2, { doc_id: "005930-FY2024", citation: "005930 FY2024 · II. 사업의 내용", section_title: "사업의 내용" }),
      legacy,
    ])} />);

    expect(screen.getByRole("button", { name: "Item 15" })).toBeInTheDocument();
    expect(within(card("Item 15")).getByText("table")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "II. 사업의 내용" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Item 7" })).toBeInTheDocument();
  });

  it("hides the pager for a single page and keeps Pin and Exclude disabled without a candidate token", () => {
    render(<EvidenceView initial={message(hits(2), { candidateToken: undefined, pinnedChunkIds: [1] })} />);

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByText("This saved result cannot change evidence. Run the question again to retrieve a fresh selection.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review again with selected evidence" })).not.toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: /^(Pin|Exclude)$/ })) expect(button).toBeDisabled();
    expect(screen.getByText("Body 1")).toBeVisible();
    expect(screen.getByText("1 pinned · 0 excluded")).toBeInTheDocument();
  });
});
