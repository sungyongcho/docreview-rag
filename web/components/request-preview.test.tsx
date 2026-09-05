import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile } from "@/lib/types";
import { RequestPreview, presetChanges, presetDescription } from "./request-preview";
import { RetainedPanel } from "./retained-panel";

afterEach(cleanup);

describe("Request inspector", () => {
  it("suspends a retained inspector and its focus guards until its workspace is visible", () => {
    const content = (active: boolean) => <><button>Other workspace</button><RetainedPanel active={active}><RequestPreview profile={DEFAULT_SESSION_PROFILE} query="Retained draft" /></RetainedPanel></>;
    const { container, rerender } = render(content(true));
    fireEvent.click(screen.getByRole("button", { name: "Settings details / request preview" }));
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(container).toHaveAttribute("inert");
    rerender(content(false));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).not.toBe("hidden");
    const other = screen.getByRole("button", { name: "Other workspace" });
    other.focus();
    fireEvent.keyDown(other, { key: "Tab" });
    expect(other).toHaveFocus();
    fireEvent.keyDown(other, { key: "Escape" });
    rerender(content(true));
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByRole("button", { name: "Close request preview" })).toHaveFocus();
  });

  it("uses an accessible portal dialog with focus trapping and Escape focus return", () => {
    const { container } = render(<div className="lab-shell"><textarea aria-label="Question" defaultValue="Keep my question" /><RequestPreview profile={DEFAULT_SESSION_PROFILE} query="Keep my question" /></div>);
    const trigger = screen.getByRole("button", { name: "Settings details / request preview" });
    expect(trigger).toHaveTextContent("Inspect request");
    expect(trigger).toHaveAttribute("title", "Settings details / request preview");
    expect(trigger.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Settings details / request preview" });
    expect(container.contains(dialog)).toBe(false);
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(container).toHaveAttribute("inert");
    const close = within(dialog).getByRole("button", { name: "Close request preview" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(within(dialog).getByText("Request payload")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container).not.toHaveAttribute("inert");
    expect(trigger).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "Question" })).toHaveValue("Keep my question");
  });

  it("keeps the next request current and closes by button without editing its profile", () => {
    const profile = { ...DEFAULT_SESSION_PROFILE, issuers: ["NVDA"], fiscal_years: [2024] };
    const original = JSON.stringify(profile);
    const { rerender } = render(<RequestPreview profile={profile} query="First question" />);
    fireEvent.click(screen.getByRole("button", { name: "Settings details / request preview" }));
    expect(within(screen.getByRole("dialog")).queryByRole("combobox")).toBeNull();
    fireEvent.click(screen.getByText("Request payload"));
    expect(screen.getByText(/"query": "First question"/)).toBeVisible();
    rerender(<RequestPreview profile={profile} query="Revised question" />);
    expect(screen.getByText(/"query": "Revised question"/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close request preview" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(JSON.stringify(profile)).toBe(original);
  });

  it("derives preset changes and visible settings from the effective retrieval profiles", () => {
    const baseline = resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE);
    for (const preset of ["balanced", "korean", "accuracy"] as const) {
      const effective = resolvedRetrievalProfile({ ...DEFAULT_SESSION_PROFILE, retrieval_preset: preset });
      const changes = presetChanges(DEFAULT_SESSION_PROFILE, preset);
      expect(Object.fromEntries(changes)).toEqual(Object.fromEntries(Object.entries(effective).filter(([key, value]) => baseline[key as keyof typeof baseline] !== value)));
      for (const [key, value] of changes) expect(presetDescription(DEFAULT_SESSION_PROFILE, preset).settings).toContain(`${key}: ${String(value)}`);
    }
    expect(presetDescription(DEFAULT_SESSION_PROFILE, "balanced").settings).toContain(`candidate_k: ${baseline.candidate_k}`);
    expect(presetDescription(DEFAULT_SESSION_PROFILE, "korean").purpose).toBe("Uses language-aware retrieval across the selected filing corpus.");
  });
});
