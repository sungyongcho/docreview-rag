import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MasterDetailDivider } from "./master-detail-divider";
import { useMasterDetail } from "./use-master-detail";

/** Feed measured widths to the hook without pretending jsdom performs browser layout. */
function observeWorkspace(initialWidth = 1400) {
  let onResize: ResizeObserverCallback;
  let workspace: Element;
  const disconnect = vi.fn();
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: ResizeObserverCallback) { onResize = callback; }
    observe(element: Element) {
      workspace = element;
      onResize([{ target: workspace, contentRect: { width: initialWidth } } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    disconnect = disconnect;
  });
  return {
    disconnect,
    measure(width: number) {
      act(() => onResize([{ target: workspace, contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver));
    },
  };
}

/** Exercise the real hook and divider together, including their persistence boundary. */
function Workspace({ storageKey = "docreview:layout:documents" }: { storageKey?: string }) {
  const layout = useMasterDetail({ storageKey });
  return <div ref={layout.workspaceRef} style={layout.splitStyle}>
    <section id={layout.listPanelId} hidden={layout.detailOpen && layout.narrow}>
      <div ref={layout.listRef}>List</div>
      <button onClick={layout.openDetail}>Open detail</button>
    </section>
    {layout.detailOpen && !layout.narrow && <MasterDetailDivider label="Resize panels" controls={layout.listPanelId} resize={layout.resize} />}
    {layout.detailOpen && <button onClick={layout.closeDetail}>Back to list</button>}
  </div>;
}

/** Stub only native pointer capture; pointer coordinates still drive the real handlers. */
function capturePointer(divider: HTMLElement) {
  const capture = vi.fn();
  const release = vi.fn();
  Object.assign(divider, { setPointerCapture: capture, hasPointerCapture: () => true, releasePointerCapture: release });
  return { capture, release };
}

afterEach(() => {
  cleanup();
  window.localStorage.removeItem("docreview:layout:documents");
  window.localStorage.removeItem("docreview:layout:jobs");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.style.userSelect = "";
  document.body.style.cursor = "";
});

describe("resizable master detail panels", () => {
  it("exposes keyboard resizing, bounds, controls, and a reset gesture", () => {
    observeWorkspace();
    render(<Workspace />);
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    const divider = screen.getByRole("separator", { name: "Resize panels" });
    expect(divider).toHaveAttribute("aria-orientation", "vertical");
    expect(divider).toHaveAttribute("aria-valuemin", "320");
    expect(divider).toHaveAttribute("aria-valuemax", "600");
    expect(divider).toHaveAttribute("aria-valuenow", "360");
    expect(document.getElementById(divider.getAttribute("aria-controls")!)).toHaveTextContent("List");
    expect(divider).toHaveAccessibleDescription(/Drag or use arrow keys/);

    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(divider).toHaveAttribute("aria-valuenow", "376");
    fireEvent.keyDown(divider, { key: "ArrowRight", shiftKey: true });
    expect(divider).toHaveAttribute("aria-valuenow", "440");
    fireEvent.keyDown(divider, { key: "End" });
    fireEvent.keyDown(divider, { key: "+" });
    expect(divider).toHaveAttribute("aria-valuenow", "600");
    fireEvent.keyDown(divider, { key: "Home" });
    fireEvent.keyDown(divider, { key: "ArrowLeft" });
    expect(divider).toHaveAttribute("aria-valuenow", "320");
    fireEvent.keyDown(divider, { key: "=" });
    expect(divider).toHaveAttribute("aria-valuenow", "336");
    fireEvent.keyDown(divider, { key: "-" });
    expect(window.localStorage.getItem("docreview:layout:documents")).toBe("320");
    fireEvent.doubleClick(divider);
    expect(divider).toHaveAttribute("aria-valuenow", "360");
    expect(window.localStorage.getItem("docreview:layout:documents")).toBeNull();
  });

  it("captures one pointer, clamps live movement, and saves only the completed gesture", () => {
    observeWorkspace();
    render(<Workspace />);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    const divider = screen.getByRole("separator");
    const { capture, release } = capturePointer(divider);
    document.body.style.cursor = "crosshair";
    fireEvent.pointerDown(divider, { pointerId: 7, isPrimary: true, button: 0, clientX: 400 });
    expect(capture).toHaveBeenCalledWith(7);
    expect(divider).toHaveFocus();
    expect(document.body.style.userSelect).toBe("none");
    fireEvent.pointerMove(divider, { pointerId: 8, clientX: 700 });
    expect(divider).toHaveAttribute("aria-valuenow", "360");
    fireEvent.pointerMove(divider, { pointerId: 7, clientX: 1400 });
    expect(divider).toHaveAttribute("aria-valuenow", "600");
    fireEvent.pointerMove(divider, { pointerId: 7, clientX: -100 });
    expect(divider).toHaveAttribute("aria-valuenow", "320");
    fireEvent.pointerMove(divider, { pointerId: 7, clientX: 490 });
    expect(divider).toHaveAttribute("aria-valuenow", "450");
    expect(window.localStorage.getItem("docreview:layout:documents")).toBeNull();
    fireEvent.pointerUp(divider, { pointerId: 7 });
    expect(window.localStorage.getItem("docreview:layout:documents")).toBe("450");
    expect(release).toHaveBeenCalledWith(7);
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("crosshair");
  });

  it("cancels interrupted gestures and cleans up selection styles on unmount", () => {
    observeWorkspace();
    const view = render(<Workspace />);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    const divider = screen.getByRole("separator");
    const { release } = capturePointer(divider);
    fireEvent.pointerDown(divider, { pointerId: 1, isPrimary: true, button: 0, clientX: 400 });
    fireEvent.pointerMove(divider, { pointerId: 1, clientX: 500 });
    fireEvent.pointerCancel(divider, { pointerId: 1 });
    expect(divider).toHaveAttribute("aria-valuenow", "360");
    expect(release).toHaveBeenCalledWith(1);
    expect(window.localStorage.getItem("docreview:layout:documents")).toBeNull();
    expect(document.body.style.userSelect).toBe("");
    fireEvent.pointerDown(divider, { pointerId: 2, isPrimary: true, button: 0, clientX: 400 });
    fireEvent.pointerMove(divider, { pointerId: 2, clientX: 500 });
    fireEvent.lostPointerCapture(divider, { pointerId: 2 });
    expect(divider).toHaveAttribute("aria-valuenow", "360");
    fireEvent.pointerDown(divider, { pointerId: 3, isPrimary: true, button: 0, clientX: 400 });
    view.unmount();
    expect(document.body.style.userSelect).toBe("");
    expect(document.body.style.cursor).toBe("");
  });

  it("keeps separate persisted workspace choices and ignores corrupt preferences", () => {
    observeWorkspace();
    window.localStorage.setItem("docreview:layout:documents", "488");
    window.localStorage.setItem("docreview:layout:jobs", "corrupt");
    const view = render(<Workspace />);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "488");
    view.rerender(<Workspace storageKey="docreview:layout:jobs" />);
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "360");
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    expect(window.localStorage.getItem("docreview:layout:jobs")).toBe("376");
    expect(window.localStorage.getItem("docreview:layout:documents")).toBe("488");
    view.unmount();
    render(<Workspace storageKey="docreview:layout:jobs" />);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "376");
  });

  it("clamps to changing content width and preserves the choice across narrow detail navigation", () => {
    const observer = observeWorkspace();
    window.localStorage.setItem("docreview:layout:documents", "600");
    render(<Workspace />);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    observer.measure(1100);
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuemax", "522");
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "522");
    expect(window.localStorage.getItem("docreview:layout:documents")).toBe("600");
    observer.measure(1099);
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open detail" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to list" }));
    expect(screen.getByRole("button", { name: "Open detail" })).toBeInTheDocument();
    observer.measure(1400);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "600");
  });

  it("remains resizable when browser preference storage is unavailable", () => {
    observeWorkspace();
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked", "QuotaExceededError"); });
    render(<Workspace />);
    fireEvent.click(screen.getByRole("button", { name: "Open detail" }));
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "376");
    expect(getItem).toHaveBeenCalled();
    expect(setItem).toHaveBeenCalled();
  });
});
