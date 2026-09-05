import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { findHelpTopic } from "@/lib/help-content";
import { HELP_GROUPS, getHelpPrimer } from "@/lib/help-primer";
import { HelpOverlay } from "./help-overlay";

/** Represent actual hooks without mounting services or running the explained actions. */
function ReviewStage() {
  return <div>
    <div data-help="review.scope">scope</div>
    <select data-help="review.preset"><option>Balanced</option></select>
    <button type="button" data-help="review.filters">Filters</button>
    <button type="button" data-help="review.readiness">Read-only corpus</button>
    <textarea data-help="review.composer" />
    <button type="button" data-help="review.send">Send</button>
  </div>;
}

/** Select a task filter while keeping all topic rows on the same home view. */
function filterGroup(topicId: string) {
  const group = HELP_GROUPS.find((item) => item.clusters.some((cluster) => cluster.topicIds.includes(topicId)))!;
  const panel = screen.getByRole("complementary", { name: "Help" });
  fireEvent.click(within(panel).getByRole("button", { name: group.title }));
  return panel;
}

/** Open an exact topic through real navigation without requiring a visible target. */
function openTopic(id: string) {
  const panel = screen.getByRole("complementary", { name: "Help" });
  if (!within(panel).queryByRole("textbox", { name: "Search help" })) fireEvent.click(within(panel).getByRole("button", { name: "Back in help" }));
  fireEvent.change(within(panel).getByRole("textbox", { name: "Search help" }), { target: { value: id } });
  fireEvent.click(panel.querySelector<HTMLButtonElement>(`button[data-help-item="${id}"]`)!);
  return panel;
}

describe("HelpOverlay", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("renders nothing while closed", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open={false} onClose={vi.fn()} location="review" /></>);
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    expect(document.querySelector(".help-marker")).toBeNull();
  });

  it("shows four inline task filters and direct topic rows without intermediate menus", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const panel = screen.getByRole("complementary", { name: "Help" });
    expect(within(panel).getByRole("heading", { name: "Choose a topic" })).toBeVisible();
    const groups = within(panel).getByRole("group", { name: "Browse help" });
    expect(within(groups).getAllByRole("button")).toHaveLength(4);
    expect(panel.querySelectorAll(".help-inline-cluster").length).toBeGreaterThan(0);
    expect(within(panel).queryByRole("button", { name: "Back in help" })).toBeNull();
    const recommended = within(panel).getByRole("region", { name: "Recommended" });
    expect(within(recommended).getAllByRole("button")).toHaveLength(4);
    expect(panel.querySelector("details")).toBeNull();
    expect(within(panel).queryByRole("combobox")).toBeNull();
    expect(document.querySelector(".help-marker, .help-arrow, .help-target-highlight")).toBeNull();
  });

  it("opens any listed guide in one click and returns directly home with one Back", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const panel = filterGroup("review.scope");
    expect(panel.querySelector("details")).toBeNull();
    const row = panel.querySelector<HTMLButtonElement>('.help-home-topics button[data-help-item="review.scope"]')!;
    fireEvent.click(row);
    const topic = findHelpTopic("review.scope")!;
    const primer = getHelpPrimer(topic);
    const detail = panel.querySelector<HTMLElement>("article.help-topic-detail")!;
    expect(detail).toHaveAttribute("data-help-item", topic.id);
    expect(within(panel).getByRole("heading", { name: topic.title })).toBeVisible();
    expect(within(detail).getByText(primer.summary)).toBeVisible();
    expect(detail.querySelectorAll(".help-steps li")).toHaveLength(3);
    const reference = within(detail).getByText("Reference").closest("details")!;
    expect(reference.open).toBe(false);
    expect(within(reference).getByText(topic.body[0])).not.toBeVisible();
    fireEvent.click(within(detail).getByText("Reference"));
    expect(within(reference).getByText(topic.body[0])).toBeVisible();
    expect(panel.querySelectorAll("article.help-topic-detail")).toHaveLength(1);
    fireEvent.click(within(panel).getByRole("button", { name: "Back in help" }));
    expect(within(panel).getByRole("heading", { name: "Choose a topic" })).toBeVisible();
    expect(within(panel).getByRole("group", { name: "Browse help" })).toBeVisible();
    expect(within(panel).queryByRole("button", { name: "Back in help" })).toBeNull();
  });

  it("highlights only the selected topic without navigating or changing its real control", () => {
    const navigate = vi.fn();
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" onNavigateTopic={navigate} /></>);
    const target = document.querySelector<HTMLElement>('[data-help="review.scope"]')!;
    const scrolled = vi.fn(); target.scrollIntoView = scrolled;
    const panel = openTopic("review.filters");
    expect(panel.querySelector("article.help-topic-detail")).toHaveAttribute("data-help-item", "review.filters");
    fireEvent.click(within(panel).getByRole("button", { name: "Corpus scope" }));
    expect(panel.querySelector("article.help-topic-detail")).toHaveAttribute("data-help-item", "review.scope");
    expect(document.querySelectorAll(".help-target-highlight")).toHaveLength(1);
    expect(document.querySelector(".help-target-highlight")).toHaveAttribute("data-help-highlight", "review.scope");
    expect(document.querySelector<HTMLElement>(".help-target-highlight")!.style.pointerEvents).toBe("none");
    expect(document.querySelector(".help-marker, .help-arrow")).toBeNull();
    expect(scrolled).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("restores search, scope, list scroll and row focus when going Back", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const panel = screen.getByRole("complementary", { name: "Help" });
    const chosenGroup = HELP_GROUPS.at(-1)!;
    fireEvent.click(within(panel).getByRole("button", { name: chosenGroup.title }));
    fireEvent.click(within(panel).getByRole("button", { name: "Current screen" }));
    fireEvent.change(within(panel).getByRole("textbox", { name: "Search help" }), { target: { value: "Corpus scope" } });
    const row = within(panel).getByRole("button", { name: "Corpus scope" });
    row.focus();
    const list = panel.querySelector<HTMLElement>(".help-browser-content")!;
    list.scrollTop = 225;
    fireEvent.click(row);
    expect(within(panel).queryByRole("textbox")).toBeNull();
    expect(list.scrollTop).toBe(0);
    fireEvent.click(within(panel).getByRole("button", { name: "Back in help" }));
    expect(within(panel).getByRole("textbox", { name: "Search help" })).toHaveValue("Corpus scope");
    expect(within(panel).getByRole("button", { name: "Current screen" })).toHaveAttribute("aria-pressed", "true");
    expect(within(panel).getByRole("button", { name: chosenGroup.title })).toHaveAttribute("aria-pressed", "true");
    expect(list.scrollTop).toBe(225);
    expect(within(panel).getByRole("button", { name: "Corpus scope" })).toHaveFocus();
    expect(within(panel).queryByRole("button", { name: "Back in help" })).toBeNull();
  });

  it("consolidates repeated explanations while exact target searches retain their context", () => {
    render(<><select data-help="measure.runs.strategy"><option>Hybrid</option></select><HelpOverlay screen="measure.runs" open onClose={vi.fn()} location="measure/runs" /></>);
    const panel = filterGroup("measure.runs.strategy");
    const rows = [...panel.querySelectorAll<HTMLButtonElement>('.help-home-topics button[data-help-item$=".strategy"]')];
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-help-item", "measure.runs.strategy");
    fireEvent.change(within(panel).getByRole("textbox", { name: "Search help" }), { target: { value: "Strategy" } });
    expect(within(panel).getAllByRole("button", { name: "Strategy" })).toHaveLength(1);
    expect(within(panel).getByRole("button", { name: "Strategy" })).toHaveAttribute("data-help-item", "measure.runs.strategy");
    fireEvent.change(within(panel).getByRole("textbox", { name: "Search help" }), { target: { value: "measure.playground.strategy" } });
    expect(within(panel).getByRole("button", { name: "Strategy" })).toHaveAttribute("data-help-item", "measure.playground.strategy");
  });

  it("searches English and Korean locally and provides an actionable empty result", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const panel = screen.getByRole("complementary", { name: "Help" });
    const search = within(panel).getByRole("textbox", { name: "Search help" });
    fireEvent.change(search, { target: { value: "실행 한도" } });
    expect(panel.querySelector('[data-help-item="review.run-limits"]')).not.toBeNull();
    fireEvent.change(search, { target: { value: "unmatched-help-zzyzx" } });
    expect(within(panel).getByRole("heading", { name: "No matching help topics." })).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Browse all topics" }));
    expect(search).toHaveValue("");
    expect(within(panel).getByRole("group", { name: "Browse help" })).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("supports arrow-key drill-in and Back without hijacking text input", () => {
    const onClose = vi.fn();
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={onClose} location="review" /></>);
    const panel = screen.getByRole("complementary", { name: "Help" });
    const first = panel.querySelector<HTMLButtonElement>("button[data-help-row]")!;
    fireEvent.keyDown(panel, { key: "ArrowDown" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(first).not.toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(panel.querySelector(".help-topic-detail")).not.toBeNull();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(panel.querySelector("button[data-help-row]")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    fireEvent.click(within(panel).getByRole("button", { name: "Back in help" }));
    const search = within(panel).getByRole("textbox", { name: "Search help" });
    search.focus();
    for (const key of ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Enter", "Escape"]) fireEvent.keyDown(search, { key });
    expect(search).toHaveFocus();
    expect(panel.querySelector(".help-topic-detail")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("reveals a control only on Go to and never executes its action", () => {
    const onClose = vi.fn(), action = vi.fn();
    render(<><details><summary>Actions</summary><button data-help="review.send" onClick={action}>Send</button></details><HelpOverlay screen="review" open onClose={onClose} location="review" /></>);
    const panel = screen.getByRole("complementary", { name: "Help" });
    fireEvent.change(within(panel).getByRole("textbox", { name: "Search help" }), { target: { value: "Send" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Send" }));
    expect(document.querySelector("details")!.open).toBe(false);
    fireEvent.click(within(panel).getByRole("button", { name: "Go to this control" }));
    expect(document.querySelector("details")!.open).toBe(true);
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toHaveFocus();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("delegates absent conditional controls only after the explicit Go to action", () => {
    const navigate = vi.fn(), onClose = vi.fn();
    render(<HelpOverlay screen="review" open onClose={onClose} location="review" onNavigateTopic={navigate} />);
    const panel = screen.getByRole("complementary", { name: "Help" });
    fireEvent.change(within(panel).getByRole("textbox", { name: "Search help" }), { target: { value: "Snapshot" } });
    const row = panel.querySelector<HTMLButtonElement>('[data-help-item="review.snapshot"]')!;
    fireEvent.click(row);
    expect(navigate).not.toHaveBeenCalled();
    fireEvent.click(within(panel).getByRole("button", { name: "Go to Measure · Snapshots" }));
    expect(navigate).toHaveBeenCalledWith("review.snapshot");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps only one home origin even after many related-topic selections", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const panel = openTopic("review.scope");
    for (let index = 0; index < 34; index += 1) fireEvent.click(within(panel).getByRole("button", { name: index % 2 ? "Corpus scope" : "Filters" }));
    let returned = 0;
    while (screen.queryByRole("button", { name: "Back in help" }) && returned < 40) { fireEvent.click(screen.getByRole("button", { name: "Back in help" })); returned += 1; }
    expect(returned).toBe(1);
    expect(within(panel).getByRole("textbox", { name: "Search help" })).toHaveValue("review.scope");
    expect(within(panel).getByRole("group", { name: "Browse help" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Back in help" })).toBeNull();
  });

  it("leaves focus and keyboard events to a dialog even without a parent keyboard flag", () => {
    const onClose = vi.fn();
    render(<><div role="dialog" aria-modal="true"><button>Dialog action</button></div><HelpOverlay screen="review" open onClose={onClose} location="review" /></>);
    const action = screen.getByRole("button", { name: "Dialog action" }); action.focus();
    fireEvent.keyDown(action, { key: "Escape" });
    fireEvent.keyDown(action, { key: "ArrowRight" });
    expect(action).toHaveFocus();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes from Escape and from the close button", () => {
    const onClose = vi.fn();
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={onClose} location="review" /></>);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("explains the absence of topics for an unmapped screen", () => {
    render(<HelpOverlay screen={null} open onClose={vi.fn()} location="build/documents" />);
    expect(screen.getByText("No help topics for this screen yet.")).toBeInTheDocument();
    expect(document.querySelector(".help-marker")).toBeNull();
  });

  it("clips the single highlight to the viewport and scroll pane, excluding hidden targets", async () => {
    const box = (top: number, left: number, width: number, height: number) => ({ top, left, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
    vi.spyOn(document.documentElement, "getBoundingClientRect").mockReturnValue(box(0, 0, 1024, 768));
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const pane = document.querySelector<HTMLElement>("div")!;
    pane.style.overflowY = "auto";
    vi.spyOn(pane, "getBoundingClientRect").mockReturnValue(box(100, 0, 800, 300));
    const visible = document.querySelector<HTMLElement>('[data-help="review.scope"]')!;
    const outside = document.querySelector<HTMLElement>('[data-help="review.preset"]')!;
    const hidden = document.querySelector<HTMLElement>('[data-help="review.filters"]')!;
    vi.spyOn(visible, "getBoundingClientRect").mockReturnValue(box(140, 20, 180, 30));
    vi.spyOn(outside, "getBoundingClientRect").mockReturnValue(box(-60, 20, 180, 30));
    vi.spyOn(hidden, "getBoundingClientRect").mockReturnValue(box(0, 0, 0, 0));
    fireEvent(window, new Event("resize"));
    openTopic("review.scope");
    expect(document.querySelector<HTMLElement>(".help-target-highlight")!.style.top).toBe("140px");
    openTopic("review.preset");
    expect(document.querySelector(".help-target-highlight")).toBeNull();
    openTopic("review.filters");
    expect(document.querySelector(".help-target-highlight")).toBeNull();
    const straddling = document.querySelector<HTMLElement>('[data-help="review.composer"]')!;
    vi.spyOn(straddling, "getBoundingClientRect").mockReturnValue(box(60, 20, 180, 90));
    fireEvent(window, new Event("resize"));
    openTopic("review.composer");
    const highlight = document.querySelector<HTMLElement>(".help-target-highlight")!;
    expect(highlight.style.top).toBe("100px");
    expect(highlight.style.height).toBe("50px");
    expect(highlight.style.pointerEvents).toBe("none");
    expect(highlight).toHaveTextContent("Question");
    fireEvent(window, new Event("resize"));
    expect(document.querySelector(".help-target-highlight")).toBe(highlight);
    await act(async () => { straddling.hidden = true; });
    expect(document.querySelector(".help-target-highlight")).toBeNull();
    await act(async () => { straddling.hidden = false; straddling.setAttribute("inert", ""); });
    expect(document.querySelector(".help-target-highlight")).toBeNull();
  });

  it("moves focus into the panel and hands it back when Help closes", () => {
    render(<><button type="button" className="help-toggle">Toggle help</button><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    expect(screen.getByRole("complementary", { name: "Help" })).toHaveFocus();

    cleanup();
    render(<><button type="button" className="help-toggle">Toggle help</button><ReviewStage /></>);
    const toggle = screen.getByRole("button", { name: "Toggle help" });
    toggle.focus();
    const { rerender } = render(<HelpOverlay screen="review" open onClose={vi.fn()} location="review" />);
    expect(screen.getByRole("complementary", { name: "Help" })).toHaveFocus();
    rerender(<HelpOverlay screen="review" open={false} onClose={vi.fn()} location="review" />);
    expect(toggle).toHaveFocus();
  });

  it("leaves Escape to the modal on top of it", () => {
    const onClose = vi.fn();
    render(<><ReviewStage /><HelpOverlay screen="review" open keyboard={false} onClose={onClose} location="review" /></>);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("re-measures the selected highlight when the host changes tabs", () => {
    function Host() {
      const [tab, setTab] = useState("status");
      return <>{tab === "status" ? <section data-help="system.status">Status</section> : <section data-help="system.api">API inspector</section>}<button type="button" onClick={() => setTab("api")}>Go to API inspector</button><HelpOverlay screen="system" open onClose={vi.fn()} location={`system/${tab}`} /></>;
    }
    vi.stubGlobal("MutationObserver", undefined);
    render(<Host />);
    openTopic("system.status");
    expect(document.querySelector(".help-target-highlight")).toHaveAttribute("data-help-highlight", "system.status");
    fireEvent.click(screen.getByRole("button", { name: "Go to API inspector" }));
    expect(document.querySelector(".help-target-highlight")).toBeNull();
    openTopic("system.api");
    expect(document.querySelectorAll(".help-target-highlight")).toHaveLength(1);
    expect(document.querySelector(".help-target-highlight")).toHaveAttribute("data-help-highlight", "system.api");
    vi.unstubAllGlobals();
  });

  it("withholds a selected target highlight inside a closed disclosure or active dialog", async () => {
    render(<><details data-help="measure.runs.profile"><summary>Retrieval profile</summary><label data-help="measure.runs.k">k<input type="number" /></label></details><HelpOverlay screen="measure.runs" open onClose={vi.fn()} location="measure/runs" /></>);
    openTopic("measure.runs.k");
    expect(document.querySelector(".help-target-highlight")).toBeNull();
    const disclosure = document.querySelector<HTMLDetailsElement>('details[data-help="measure.runs.profile"]')!;
    await act(async () => { disclosure.open = true; });
    expect(document.querySelector(".help-target-highlight")).toHaveAttribute("data-help-highlight", "measure.runs.k");
    const modal = document.createElement("div"); modal.setAttribute("role", "dialog"); modal.setAttribute("aria-modal", "true");
    await act(async () => { document.body.append(modal); });
    expect(document.querySelector(".help-target-highlight")).toBeNull();
    await act(async () => { modal.remove(); });
    expect(document.querySelector(".help-target-highlight")).toHaveAttribute("data-help-highlight", "measure.runs.k");
    await act(async () => { disclosure.open = false; });
    expect(document.querySelector(".help-target-highlight")).toBeNull();
  });
});
