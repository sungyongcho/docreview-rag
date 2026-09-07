import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceHistory } from "./workspace-history";

afterEach(cleanup);
const entries = [{ id: "a", label: "Conversation · NVIDIA" }, { id: "b", label: "Build · Pipeline · Step 2" }, { id: "c", label: "System · Status" }];

describe("workspace history picker", () => {
  it("keeps arrows visible and disables only the unavailable direction", () => {
    const back = vi.fn(); const forward = vi.fn(); const jump = vi.fn();
    const { rerender } = render(<WorkspaceHistory entries={entries} currentIndex={0} onBack={back} onForward={forward} onJump={jump} />);
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toHaveAttribute("title", "Forward: Build · Pipeline · Step 2");
    fireEvent.click(screen.getByRole("button", { name: "Forward" })); expect(forward).toHaveBeenCalledOnce();
    rerender(<WorkspaceHistory entries={entries} currentIndex={2} onBack={back} onForward={forward} onJump={jump} />);
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Back" })); expect(back).toHaveBeenCalledOnce();
  });
  it("marks the current entry and jumps to a selected past or future entry", () => {
    const jump = vi.fn();
    render(<WorkspaceHistory entries={entries} currentIndex={1} onBack={vi.fn()} onForward={vi.fn()} onJump={jump} />);
    const title = screen.getByRole("button", { name: entries[1].label });
    expect(title).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(title);
    expect(screen.getByRole("option", { name: entries[1].label })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("option", { name: entries[2].label }));
    expect(jump).toHaveBeenLastCalledWith(2); expect(title).toHaveFocus();
    expect(screen.queryByRole("listbox")).toBeNull();
    fireEvent.click(title); fireEvent.click(screen.getByRole("option", { name: entries[0].label }));
    expect(jump).toHaveBeenLastCalledWith(0);
  });
  it("supports keyboard focus, Home/End, arrows, Enter and Escape", () => {
    const jump = vi.fn();
    render(<WorkspaceHistory entries={entries} currentIndex={1} onBack={vi.fn()} onForward={vi.fn()} onJump={jump} />);
    const title = screen.getByRole("button", { name: entries[1].label });
    fireEvent.keyDown(title, { key: "ArrowDown" });
    const list = screen.getByRole("listbox");
    expect(screen.getByRole("option", { name: entries[1].label })).toHaveFocus();
    fireEvent.keyDown(list, { key: "Home" }); expect(screen.getByRole("option", { name: entries[0].label })).toHaveFocus();
    fireEvent.keyDown(list, { key: "ArrowDown" }); expect(screen.getByRole("option", { name: entries[1].label })).toHaveFocus();
    fireEvent.keyDown(list, { key: "End" }); expect(screen.getByRole("option", { name: entries[2].label })).toHaveFocus();
    fireEvent.keyDown(list, { key: "ArrowUp" });
    fireEvent.keyDown(list, { key: "Enter" }); expect(jump).toHaveBeenCalledWith(1);
    fireEvent.click(title); fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    expect(title).toHaveFocus(); expect(screen.queryByRole("listbox")).toBeNull();
  });
  it("closes on an outside pointer without navigating", () => {
    const jump = vi.fn();
    render(<WorkspaceHistory entries={entries} currentIndex={0} onBack={vi.fn()} onForward={vi.fn()} onJump={jump} />);
    const title = screen.getByRole("button", { name: entries[0].label });
    fireEvent.click(title); fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull(); expect(title).toHaveFocus(); expect(jump).not.toHaveBeenCalled();
  });
});
