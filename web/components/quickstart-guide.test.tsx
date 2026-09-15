import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { consumeReadingState, rememberReadingState } from "@/lib/documentation-reading";
import { QuickStartProvider, QuickStartPanels, QuickStartOutline } from "./quickstart-guide";

vi.mock("@/components/documentation-navigation", () => ({ DocumentationOutline: ({ headings }: { headings: Array<{ id: string; text: string }> }) => <nav aria-label="outline">{headings.map((h) => <a key={h.id} href={`#${h.id}`}>{h.text}</a>)}</nav> }));
afterEach(() => { cleanup(); window.history.replaceState(null, "", "/"); sessionStorage.clear(); consumeReadingState("__none__"); });
function guide() {
  return render(<QuickStartProvider><QuickStartPanels locale="en" cli={<h2 id="qs-cli-1">CLI step</h2>} web={<h2 id="qs-web-1">Web step</h2>} /><QuickStartOutline locale="en" headings={[{ id: "qs-cli-1", text: "CLI outline", depth: 2 }, { id: "qs-web-1", text: "Web outline", depth: 2 }]} /></QuickStartProvider>);
}
it("defaults to Web and excludes hidden CLI headings from the outline", () => {
  guide();
  expect(screen.getByRole("tab", { name: "Web" })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByRole("heading", { name: "CLI step" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "CLI outline" })).not.toBeInTheDocument();
});
it("switches interface with the keyboard and retains the linked step", () => {
  window.history.replaceState(null, "", "#qs-web-1");
  guide();
  fireEvent.keyDown(screen.getByRole("tab", { name: "Web" }), { key: "ArrowLeft" });
  expect(screen.getByRole("tab", { name: "CLI" })).toHaveFocus();
  expect(screen.getByRole("heading", { name: "CLI step" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Web outline" })).not.toBeInTheDocument();
  expect(window.location.hash).toBe("#qs-cli-1");
});
it("opens a direct CLI anchor after a language or page navigation", () => {
  window.history.replaceState(null, "", "#qs-cli-1");
  guide();
  expect(screen.getByRole("tab", { name: "CLI" })).toHaveAttribute("aria-selected", "true");
});
it("restores the interface captured by a pending language switch", () => {
  rememberReadingState({ documentId: "quickstart-dev", path: ["install"], progress: 0.5, details: [], quickstart: "cli" });
  guide();
  expect(screen.getByRole("tab", { name: "CLI" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("heading", { name: "CLI step" })).toBeVisible();
});
it("lets an explicit step link outrank the restored interface", () => {
  rememberReadingState({ documentId: "quickstart-dev", path: ["install"], progress: 0.5, details: [], quickstart: "cli" });
  window.history.replaceState(null, "", "#qs-web-2");
  guide();
  expect(screen.getByRole("tab", { name: "Web" })).toHaveAttribute("aria-selected", "true");
});
