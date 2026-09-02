import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HELP_TOPICS } from "@/lib/help-content";
import { HelpOverlay } from "./help-overlay";

const REVIEW = HELP_TOPICS.review;

/** The Ask composer hooks without the snapshot chip or an answered review. */
function ReviewStage() {
  return (
    <div>
      <div data-help="review.scope">scope</div>
      <select data-help="review.preset"><option>Balanced</option></select>
      <button type="button" data-help="review.filters">Filters</button>
      <button type="button" data-help="review.readiness">Read-only corpus</button>
      <textarea data-help="review.composer" />
      <button type="button" data-help="review.send">Send</button>
    </div>
  );
}

describe("HelpOverlay", () => {
  afterEach(cleanup);

  it("renders nothing while closed", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open={false} onClose={vi.fn()} location="review" /></>);
    expect(screen.queryByRole("complementary", { name: "Help" })).toBeNull();
    expect(document.querySelector(".help-marker")).toBeNull();
  });

  it("marks only the topics present in the DOM, numbered in topic order", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);

    const markers = document.querySelectorAll<HTMLButtonElement>(".help-marker");
    const expected = REVIEW.flatMap((topic, index) => (document.querySelector(`[data-help="${topic.id}"]`) ? [`Help ${index + 1}: ${topic.title}`] : []));
    expect(expected.length).toBeGreaterThan(0);
    expect([...markers].map((marker) => marker.getAttribute("aria-label"))).toEqual(expected);
    const missing = REVIEW.filter((topic) => !document.querySelector(`[data-help="${topic.id}"]`)).map((topic) => topic.id);
    expect(missing).toEqual(["review.snapshot", "review.evidence"]);
    expect(screen.getAllByText("Not on this screen right now")).toHaveLength(missing.length);
    for (const id of missing) expect(document.querySelector(`[data-help-item="${id}"]`)).toHaveClass("absent");
  });

  it("lists every topic in the panel with body, tuning and see-also links", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const panel = screen.getByRole("complementary", { name: "Help" });

    expect(within(panel).getByRole("heading", { name: "Ask" })).toBeInTheDocument();
    for (const [index, topic] of REVIEW.entries()) {
      expect(within(panel).getByText(`${index + 1}. ${topic.title}`)).toBeInTheDocument();
      expect(within(panel).getByText(topic.body[0])).toBeInTheDocument();
    }
    const scope = REVIEW.find((topic) => topic.id === "review.scope")!;
    const scopeItem = document.querySelector('[data-help-item="review.scope"]')!;
    expect(within(scopeItem as HTMLElement).getByText("How to tune")).toBeInTheDocument();
    expect(within(scopeItem as HTMLElement).getByText(scope.tune!, { exact: false })).toBeInTheDocument();
  });

  it("activates the panel item from its marker and the marker from a see-also link", () => {
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);

    fireEvent.click(screen.getByRole("button", { name: "Help 3: Filters" }));
    const filters = document.querySelector<HTMLDetailsElement>('[data-help-item="review.filters"]')!;
    expect(filters).toHaveClass("active");
    expect(filters.open).toBe(true);
    expect(screen.getByRole("button", { name: "Help 3: Filters" })).toHaveClass("active");

    // See also on Filters → Corpus scope, a topic on this screen, activates it; the cross-screen ref is plain text.
    fireEvent.click(within(filters).getByRole("button", { name: "Corpus scope" }));
    expect(document.querySelector('[data-help-item="review.scope"]')).toHaveClass("active");
    expect(filters).not.toHaveClass("active");
    expect(screen.getByRole("button", { name: "Help 1: Corpus scope" })).toHaveClass("active");
    expect(within(filters).queryByRole("button", { name: "Route by language" })).toBeNull();
    expect(within(filters).getByText("Route by language")).toBeInTheDocument();

    // A panel summary selects its topic and scrolls the control it explains back into view.
    const send = document.querySelector<HTMLElement>('[data-help="review.send"]')!;
    const scrolled = vi.fn();
    send.scrollIntoView = scrolled;
    fireEvent.click(screen.getByText("7. Send"));
    expect(document.querySelector('[data-help-item="review.send"]')).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Help 7: Send" })).toHaveClass("active");
    expect(scrolled).toHaveBeenCalledWith({ block: "center", inline: "nearest" });
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

  it("gives layout-aware builds no marker for a hidden or scrolled-away target", () => {
    // jsdom measures nothing, so the test supplies the layout: a document with height, a scrolling
    // pane from y 100 to 400, one target inside it and one scrolled above it.
    const box = (top: number, left: number, width: number, height: number) =>
      ({ top, left, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;
    vi.spyOn(document.documentElement, "getBoundingClientRect").mockReturnValue(box(0, 0, 1024, 768));
    render(<><ReviewStage /><HelpOverlay screen="review" open onClose={vi.fn()} location="review" /></>);
    const pane = document.querySelector<HTMLElement>("div")!;
    pane.style.overflowY = "auto";
    vi.spyOn(pane, "getBoundingClientRect").mockReturnValue(box(100, 0, 800, 300));
    const visible = document.querySelector<HTMLElement>('[data-help="review.scope"]')!;
    const scrolledAway = document.querySelector<HTMLElement>('[data-help="review.preset"]')!;
    const hidden = document.querySelector<HTMLElement>('[data-help="review.filters"]')!;
    vi.spyOn(visible, "getBoundingClientRect").mockReturnValue(box(140, 20, 180, 30));
    vi.spyOn(scrolledAway, "getBoundingClientRect").mockReturnValue(box(-60, 20, 180, 30));
    vi.spyOn(hidden, "getBoundingClientRect").mockReturnValue(box(0, 0, 0, 0));
    fireEvent(window, new Event("resize"));

    expect(screen.getByRole("button", { name: "Help 1: Corpus scope" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Help 2: Retrieval preset" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Help 3: Filters" })).toBeNull();
    // A target straddling the top of its pane keeps a marker, pinned to the part the reader can see.
    const straddling = document.querySelector<HTMLElement>('[data-help="review.composer"]')!;
    vi.spyOn(straddling, "getBoundingClientRect").mockReturnValue(box(60, 20, 180, 90));
    fireEvent(window, new Event("resize"));
    expect(screen.getByRole("button", { name: "Help 6: Question" }).style.top).toBe("100px");
    expect(document.querySelector('[data-help-item="review.preset"]')).toHaveClass("absent");
    // The rect guard keeps a repeated measurement from re-rendering: the marker element survives.
    const marker = screen.getByRole("button", { name: "Help 1: Corpus scope" });
    fireEvent(window, new Event("resize"));
    expect(screen.getByRole("button", { name: "Help 1: Corpus scope" })).toBe(marker);
    vi.restoreAllMocks();
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

  it("re-measures when the host switches tabs inside one screen", () => {
    // System keeps one help screen across its tabs, so only the committed location tells the overlay
    // that a different set of hooks is now mounted.
    function Host() {
      const [tab, setTab] = useState("status");
      return (
        <>
          {tab === "status" ? <section data-help="system.status">Status</section> : <section data-help="system.api">API inspector</section>}
          <button type="button" onClick={() => setTab("api")}>Go to API inspector</button>
          <HelpOverlay screen="system" open onClose={vi.fn()} location={`system/${tab}`} />
        </>
      );
    }
    // Without the observer only the committed location can trigger the re-measure, and it must happen
    // in the same commit as the swap so no frame shows markers pointing at the old screen.
    vi.stubGlobal("MutationObserver", undefined);
    render(<Host />);
    expect(screen.getByRole("button", { name: /^Help 1: / })).toBeInTheDocument();
    const first = screen.getByRole("button", { name: /^Help 1: / }).getAttribute("aria-label");

    fireEvent.click(screen.getByRole("button", { name: "Go to API inspector" }));

    const labels = [...document.querySelectorAll(".help-marker")].map((marker) => marker.getAttribute("aria-label"));
    expect(labels).toHaveLength(1);
    expect(labels[0]).not.toBe(first);
    expect(labels[0]).toMatch(/API inspector|Raw API/);
    vi.unstubAllGlobals();
  });

  it("skips markers for hooks inside a closed disclosure until it opens", async () => {
    render(
      <>
        <details data-help="measure.runs.profile">
          <summary>Retrieval profile</summary>
          <label data-help="measure.runs.k">k<input type="number" /></label>
        </details>
        <HelpOverlay screen="measure.runs" open onClose={vi.fn()} location="measure/runs" />
      </>,
    );
    expect(screen.getByRole("button", { name: /Help \d+: Retrieval profile/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Help \d+: k$/ })).toBeNull();

    // Opening the disclosure is a DOM attribute change: the observer must re-measure and add the marker.
    const disclosure = document.querySelector<HTMLDetailsElement>('details[data-help="measure.runs.profile"]')!;
    await act(async () => { disclosure.open = true; });
    expect(screen.getByRole("button", { name: /Help \d+: k$/ })).toBeInTheDocument();
  });
});
