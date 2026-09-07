import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NotificationOutlet, NotificationProvider, useNotifications } from "./notifications";

function Probe() {
  const { notify, dismissNotice } = useNotifications();
  return <><button onClick={() => notify("Waiting for API", "info", "health-wait", 0)}>Wait</button><button onClick={() => { for (let i = 0; i < 4; i++) notify(`Job ${i}`); }}>Jobs</button><button onClick={() => dismissNotice("health-wait")}>Recover</button></>;
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("keeps one persistent waiting notice through job updates and removes it on recovery", async () => {
  vi.useFakeTimers();
  render(<NotificationProvider><Probe /></NotificationProvider>);
  fireEvent.click(screen.getByText("Wait")); fireEvent.click(screen.getByText("Wait"));
  fireEvent.click(screen.getByText("Jobs"));
  await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
  expect(screen.getAllByText("Waiting for API")).toHaveLength(1);
  fireEvent.click(screen.getByText("Recover"));
  expect(screen.queryByText("Waiting for API")).toBeNull();
});


interface OutletState { main?: boolean; inspector?: boolean; dialog?: boolean; }

/** Exercise the public notification API with real prioritized outlet lifecycles. */
function setup(initial: OutletState = {}) {
  let api!: ReturnType<typeof useNotifications>;
  /** Capture the provider API without exposing implementation state to assertions. */
  function Capture() { api = useNotifications(); return <button type="button">Outside control</button>; }
  /** Keep the provider mounted while contextual outlets become active or disappear. */
  function Tree({ main = true, inspector = false, dialog = false }: OutletState) {
    return <NotificationProvider><Capture />
      {main && <div data-testid="main-outlet"><NotificationOutlet /></div>}
      <div data-testid="inspector-outlet"><NotificationOutlet priority={10} active={inspector} /></div>
      <div data-testid="dialog-outlet"><NotificationOutlet priority={20} active={dialog} /></div>
    </NotificationProvider>;
  }
  const view = render(<Tree {...initial} />);
  return { ...view,
    notify: (...args: Parameters<typeof api.notify>) => act(() => api.notify(...args)),
    outlets: (next: OutletState) => view.rerender(<Tree {...next} />),
  };
}

/** Advance only the active timer, keeping React updates inside its test transaction. */
async function advance(milliseconds: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}

/** JSDOM does not lay out text; supply the same measured overflow the browser reports. */
function overflowingMessage() {
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) { return this.classList.contains("notification-message") ? 120 : 0; });
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) { return this.classList.contains("notification-message") ? 40 : 0; });
}

describe("notification timing and keyed delivery", () => {
  it("does not remount or restart the timer for an identical keyed repeat", async () => {
    vi.useFakeTimers();
    const view = setup();
    view.notify("Saved", "success", "save", 5000);
    const card = screen.getByText("Saved").closest(".notification");
    await advance(3000);
    view.notify("Saved", "success", "save", 5000);
    expect(screen.getByText("Saved").closest(".notification")).toBe(card);
    await advance(1999);
    expect(screen.getByText("Saved")).toBeVisible();
    await advance(1);
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("updates a changed keyed notice in one card and gives the new message its own duration", async () => {
    vi.useFakeTimers();
    const view = setup();
    view.notify("Saving", "info", "save", 5000);
    const card = screen.getByText("Saving").closest(".notification");
    await advance(3000);
    view.notify("Saved", "success", "save", 5000);
    expect(screen.queryByText("Saving")).toBeNull();
    expect(screen.getByText("Saved").closest(".notification")).toBe(card);
    expect(document.querySelectorAll(".notification")).toHaveLength(1);
    await advance(4999);
    expect(screen.getByText("Saved")).toBeVisible();
    await advance(1);
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("limits the stack to three while retaining duration-zero feedback through transient updates", async () => {
    vi.useFakeTimers();
    const view = setup();
    view.notify("Waiting", "info", "waiting", 0);
    for (let index = 0; index < 4; index++) view.notify(`Job ${index}`, "success", `job-${index}`, 5000);
    expect(document.querySelectorAll(".notification")).toHaveLength(3);
    expect(screen.queryByText("Job 0")).toBeNull();
    expect(screen.queryByText("Job 1")).toBeNull();
    expect(screen.getByText("Job 2")).toBeVisible();
    expect(screen.getByText("Job 3")).toBeVisible();
    await advance(9000);
    expect(document.querySelectorAll(".notification")).toHaveLength(1);
    expect(screen.getByText("Waiting")).toBeVisible();
  });

  it("does not resume after hover leaves while focus still owns the notice", async () => {
    vi.useFakeTimers();
    const view = setup();
    view.notify("Read me", "info", "read", 5000);
    await advance(1000);
    const card = screen.getByText("Read me").closest(".notification")!;
    const dismiss = within(card as HTMLElement).getByRole("button", { name: "Dismiss notification" });
    fireEvent.mouseEnter(card);
    fireEvent.focus(dismiss);
    fireEvent.mouseLeave(card);
    await advance(10000);
    expect(screen.getByText("Read me")).toBeVisible();
    fireEvent.blur(dismiss, { relatedTarget: screen.getByRole("button", { name: "Outside control" }) });
    await advance(3999);
    expect(screen.getByText("Read me")).toBeVisible();
    await advance(1);
    expect(screen.queryByText("Read me")).toBeNull();
  });

  it("does not resume after focus leaves while the pointer still owns the notice", async () => {
    vi.useFakeTimers();
    const view = setup();
    view.notify("Read me", "info", "read", 5000);
    await advance(1000);
    const card = screen.getByText("Read me").closest(".notification")!;
    const dismiss = screen.getByRole("button", { name: "Dismiss notification" });
    fireEvent.focus(dismiss);
    fireEvent.mouseEnter(card);
    fireEvent.blur(dismiss, { relatedTarget: screen.getByRole("button", { name: "Outside control" }) });
    await advance(10000);
    expect(screen.getByText("Read me")).toBeVisible();
    fireEvent.mouseLeave(card);
    await advance(4000);
    expect(screen.queryByText("Read me")).toBeNull();
  });

  it("keeps focus paused when moving between controls inside the same card", async () => {
    vi.useFakeTimers(); overflowingMessage();
    const view = setup();
    view.notify("A long message", "warning", "long", 5000);
    await advance(1000);
    const expand = screen.getByRole("button", { name: "Expand notification" });
    const dismiss = screen.getByRole("button", { name: "Dismiss notification" });
    fireEvent.focus(expand);
    fireEvent.blur(expand, { relatedTarget: dismiss });
    fireEvent.focus(dismiss);
    await advance(10000);
    expect(screen.getByText("A long message")).toBeVisible();
    fireEvent.blur(dismiss, { relatedTarget: screen.getByRole("button", { name: "Outside control" }) });
    await advance(4000);
    expect(screen.queryByText("A long message")).toBeNull();
  });

  it("pauses an explicitly expanded message until it is collapsed", async () => {
    vi.useFakeTimers(); overflowingMessage();
    const view = setup();
    view.notify("A long message", "warning", "long", 5000);
    await advance(1000);
    fireEvent.click(screen.getByRole("button", { name: "Expand notification" }));
    expect(screen.getByRole("button", { name: "Collapse notification" })).toHaveAttribute("aria-expanded", "true");
    await advance(10000);
    expect(screen.getByText("A long message")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Collapse notification" }));
    await advance(3999);
    expect(screen.getByText("A long message")).toBeVisible();
    await advance(1);
    expect(screen.queryByText("A long message")).toBeNull();
  });
});

describe("notification outlet ownership and viewport", () => {
  it("moves the only rail through dialog, inspector and main while preserving remaining time", async () => {
    vi.useFakeTimers();
    const view = setup();
    view.notify("Feedback", "info", "feedback", 5000);
    await advance(1000);
    view.outlets({ inspector: true });
    expect(within(screen.getByTestId("inspector-outlet")).getByText("Feedback")).toBeVisible();
    expect(within(screen.getByTestId("main-outlet")).queryByText("Feedback")).toBeNull();
    await advance(2000);
    view.outlets({ inspector: true, dialog: true });
    expect(within(screen.getByTestId("dialog-outlet")).getByText("Feedback")).toBeVisible();
    expect(document.querySelectorAll(".notification-stack")).toHaveLength(1);
    await advance(500);
    view.outlets({ inspector: true });
    expect(within(screen.getByTestId("inspector-outlet")).getByText("Feedback")).toBeVisible();
    await advance(500);
    view.outlets({});
    expect(within(screen.getByTestId("main-outlet")).getByText("Feedback")).toBeVisible();
    await advance(999);
    expect(screen.getByText("Feedback")).toBeVisible();
    await advance(1);
    expect(screen.queryByText("Feedback")).toBeNull();
  });

  it("provides standalone feedback without an outlet and returns there when the last outlet disappears", async () => {
    vi.useFakeTimers();
    const view = setup({ main: false });
    view.notify("Standalone", "info", "standalone", 5000);
    expect(screen.getByRole("region", { name: "Notifications" })).toHaveTextContent("Standalone");
    await advance(2000);
    view.outlets({ main: false, dialog: true });
    expect(within(screen.getByTestId("dialog-outlet")).getByText("Standalone")).toBeVisible();
    await advance(1000);
    view.outlets({ main: false });
    expect(within(screen.getByTestId("dialog-outlet")).queryByText("Standalone")).toBeNull();
    expect(screen.getByText("Standalone")).toBeVisible();
    await advance(2000);
    expect(screen.queryByText("Standalone")).toBeNull();
  });

  it("resizes the visual-viewport rail cap for a software keyboard and restores the desktop cap", () => {
    const viewport = new EventTarget() as EventTarget & { height: number };
    viewport.height = 900;
    vi.stubGlobal("visualViewport", viewport);
    const view = setup();
    view.notify("Viewport feedback", "info", "viewport", 0);
    const rail = screen.getByRole("region", { name: "Notifications" });
    expect(rail).toHaveStyle({ maxHeight: "180px" });
    act(() => { viewport.height = 300; viewport.dispatchEvent(new Event("resize")); });
    expect(Number.parseFloat(rail.style.maxHeight)).toBeCloseTo(84, 5);
    act(() => { viewport.height = 900; viewport.dispatchEvent(new Event("resize")); });
    expect(rail).toHaveStyle({ maxHeight: "180px" });
  });

  it("uses window height when visualViewport is unavailable", () => {
    vi.stubGlobal("visualViewport", undefined);
    vi.stubGlobal("innerHeight", 400);
    const view = setup();
    view.notify("Window feedback", "info", "window", 0);
    const rail = screen.getByRole("region", { name: "Notifications" });
    expect(Number.parseFloat(rail.style.maxHeight)).toBeCloseTo(112, 5);
    act(() => { window.innerHeight = 800; window.dispatchEvent(new Event("resize")); });
    expect(rail).toHaveStyle({ maxHeight: "180px" });
  });
});
