import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "@/lib/types";
import { RunDetailsPanel } from "./run-details-panel";

const first: ChatMessage = {
  id: "first123-message-id", role: "assistant", text: "The answer stays in the conversation.",
  question: "How did the company revenue change across these fiscal years?",
  execution: { node: "report", evidence: 2, relevant: 1, steps: 4, outcome: "completed", elapsedMs: 1250 },
  performance: { total_elapsed_ms: 1200, model_calls: [], effective_settings: { engine: "openai", model: "gpt-example", retrieval_applicable: true, provider_budget_source: "server_configuration" } },
  trace: "gate → retrieve → grade → report",
};
const second: ChatMessage = { ...first, id: "second45-message-id", question: "What changed in operating expenses?", trace: "A different run trace" };

afterEach(() => cleanup());

/** Model the parent keeping its conversation and inspector mounted across closes. */
function Conversation() {
  const [message, setMessage] = useState<ChatMessage | null>(null);
  const [draft, setDraft] = useState("My unfinished question");
  return <div className="review-workspace">
    <div className="messages" data-testid="conversation"><p>{first.text}</p><button data-run-details-open type="button" onClick={() => setMessage(first)}>Inspect first run</button><button data-run-details-open type="button" onClick={() => setMessage(second)}>Inspect second run</button></div>
    <div className="composer-wrap"><textarea aria-label="Draft question" value={draft} onChange={(event) => setDraft(event.target.value)} /></div>
    <RunDetailsPanel message={message} onClose={() => setMessage(null)} />
  </div>;
}

describe("Run details panel", () => {
  it("identifies the question and message without covering the conversation with a modal", () => {
    render(<Conversation />);
    fireEvent.click(screen.getByRole("button", { name: "Inspect first run" }));
    const panel = screen.getByRole("dialog", { name: "Run details" });
    expect(panel).toHaveAttribute("aria-modal", "false");
    expect(panel).toHaveFocus();
    const heading = within(panel).getByRole("heading", { name: `Q. ${first.question}` });
    expect(heading).toHaveAttribute("title", `Q. ${first.question}`);
    expect(within(panel).getByText("first123")).toHaveAttribute("title", first.id);
    expect(screen.getByText(first.text)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Draft question" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Show full question" }));
    expect(heading).toHaveClass("is-expanded");
    expect(screen.getByRole("button", { name: "Collapse question" })).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Collapse question" }));
    expect(heading).not.toHaveClass("is-expanded");
  });

  it("retains each message's section across switching and closing", () => {
    render(<Conversation />);
    fireEvent.click(screen.getByRole("button", { name: "Inspect first run" }));
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
    expect(screen.getByText(first.trace!)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Inspect second run" }));
    expect(screen.getByRole("heading", { name: `Q. ${second.question}` })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Server settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Inspect first run" }));
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText(second.trace!)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close run details" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Inspect first run" }));
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Trace" })).toHaveAttribute("data-help", "review.run-trace");
  });

  it("restores opener focus on Escape and the explicit close action", () => {
    render(<Conversation />);
    const opener = screen.getByRole("button", { name: "Inspect first run" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByRole("button", { name: "Close run details" }));
    expect(opener).toHaveFocus();
  });

  it("collapses to its edge and restores the current section on expand", () => {
    render(<RunDetailsPanel message={first} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
    fireEvent.click(screen.getByRole("button", { name: "Collapse run details" }));
    expect(screen.getByRole("dialog")).toHaveClass("is-collapsed");
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByRole("button", { name: "Expand run details" })).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByRole("button", { name: "Expand run details" }));
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(first.trace!)).toBeVisible();
  });

  it("closes on conversation or composer input without discarding draft, focus or scroll", () => {
    render(<Conversation />);
    const conversation = screen.getByTestId("conversation");
    conversation.scrollTop = 480;
    const draft = screen.getByRole("textbox", { name: "Draft question" });
    fireEvent.change(draft, { target: { value: "Keep this composer draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect first run" }));
    draft.focus();
    fireEvent.pointerDown(draft);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(draft).toHaveFocus();
    expect(draft).toHaveValue("Keep this composer draft");
    expect(conversation.scrollTop).toBe(480);
    fireEvent.click(screen.getByRole("button", { name: "Inspect first run" }));
    fireEvent.pointerDown(screen.getByText(first.text));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(conversation.scrollTop).toBe(480);
  });

  it("uses arrow keys, Home and End to focus and activate the detail tabs", () => {
    render(<RunDetailsPanel message={first} onClose={vi.fn()} />);
    const performance = screen.getByRole("tab", { name: "Performance" });
    performance.focus();
    fireEvent.keyDown(performance, { key: "ArrowRight" });
    const settings = screen.getByRole("tab", { name: "Server settings" });
    expect(settings).toHaveFocus();
    expect(settings).toHaveAttribute("aria-selected", "true");
    expect(performance).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(settings, { key: "End" });
    const trace = screen.getByRole("tab", { name: "Preview" });
    expect(trace).toHaveFocus();
    fireEvent.keyDown(trace, { key: "Home" });
    expect(performance).toHaveFocus();
    expect(performance).toHaveAttribute("aria-selected", "true");
  });

  it("shows collected server settings and explains retrieval-free replies", () => {
    const { rerender } = render(<RunDetailsPanel message={first} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Server settings" }));
    const settings = screen.getByRole("tabpanel", { name: "Server settings" });
    expect(settings).toHaveTextContent('"provider_budget_source": "server_configuration"');
    expect(settings).not.toHaveTextContent("not recorded");
    rerender(<RunDetailsPanel message={{ ...first, performance: { effective_settings: { retrieval_applicable: false, retrieval: null } } }} onClose={vi.fn()} />);
    expect(screen.getByText("This conversation reply did not use retrieval settings.")).toBeVisible();
  });

  it("preserves failure facts and its settings recovery action", () => {
    const fix = vi.fn();
    render(<RunDetailsPanel message={{ ...first, diagnostics: [{ label: "Status", value: "failed" }, { label: "Exhausted resource", value: "output_tokens" }, { label: "Limit", value: "1800" }], failureFix: { category: "limits", label: "Open run limits" } }} onClose={vi.fn()} onOpenFix={fix} />);
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
    expect(screen.getByRole("heading", { name: "Run trace · why it stopped" })).toBeVisible();
    expect(screen.getByText("output_tokens")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open run limits" }));
    expect(fix).toHaveBeenCalledWith("limits");
  });

  it("keeps historical missing measurements, settings and traces explicit", () => {
    render(<RunDetailsPanel message={{ id: "legacy", role: "assistant", text: "Older reply" }} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Q. Question unavailable" })).toBeVisible();
    expect(screen.getByText("Execution measurements were not recorded for this message.")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Server settings" }));
    expect(screen.getByText("Server-applied settings were not recorded for this message.")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
    expect(screen.getByText("A run trace was not recorded for this message.")).toBeVisible();
  });
});


it("opens the selected stage on Performance while retaining every collected node and pass", () => {
  const nodes = ["gate", "route", "retrieve", "route", "retrieve", "grade", "check", "report"];
  const message = { ...first, performance: { stages: nodes.map((node, index) => ({ node, status: "completed", elapsed_ms: index + 1 })) } };
  const { rerender } = render(<RunDetailsPanel message={message} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("tab", { name: "Server settings" }));
  rerender(<RunDetailsPanel message={message} onClose={vi.fn()} stageRequest={{ stage: "retrieve" }} />);
  expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute("aria-selected", "true");
  const table = screen.getByRole("table", { name: /Measured stage durations/ });
  expect(Array.from(table.querySelectorAll("tbody tr"), (row) => row.getAttribute("data-stage-node"))).toEqual(nodes);
  expect(table.querySelectorAll('tr[aria-current="true"]')).toHaveLength(2);
  expect(Array.from(table.querySelectorAll('tr[aria-current="true"]'), (row) => row.getAttribute("data-stage-node"))).toEqual(["retrieve", "retrieve"]);
  fireEvent.click(screen.getByRole("tab", { name: "Trace" }));
  fireEvent.click(screen.getByRole("button", { name: "Collapse run details" }));
  rerender(<RunDetailsPanel message={message} onClose={vi.fn()} stageRequest={{ stage: "retrieve" }} />);
  expect(screen.getByRole("tab", { name: "Performance" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "Collapse run details" })).toHaveAttribute("aria-expanded", "true");
});
