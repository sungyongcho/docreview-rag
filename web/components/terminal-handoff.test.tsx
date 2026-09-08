import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TerminalHandoff } from "./terminal-handoff";

afterEach(cleanup);
const steps = [{ reason: "Inspect schema", command: "uv run python -m scripts.schema check", expected: "Schema must be compatible" }];

it("shows a terminal handoff without executing or marking the prerequisite resolved", async () => {
  const refresh = vi.fn().mockResolvedValue(true);
  const view = render(<TerminalHandoff steps={steps} onRefresh={refresh} />);
  expect(screen.getByText(steps[0].command)).toBeVisible();
  expect(refresh).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Check updated status" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(await screen.findByText("Preparation state updated")).toBeVisible();
  view.rerender(<TerminalHandoff steps={[]} onRefresh={refresh} />);
  expect(screen.queryByText("Prerequisites are ready. Continue with the selected step.")).not.toBeInTheDocument();
});

it("copies the exact command and reports refresh failures honestly", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  render(<TerminalHandoff steps={steps} onRefresh={vi.fn().mockRejectedValue(new Error("offline"))} />);
  fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(steps[0].command));
  fireEvent.click(screen.getByRole("button", { name: "Check updated status" }));
  expect(await screen.findByText("Could not refresh status. Check the connection and try again.")).toBeVisible();
  expect(screen.queryByText("Prerequisites are ready. Continue with the selected step.")).not.toBeInTheDocument();
});

it("uses observed diagnosis after recheck and navigates to its prerequisite", async () => {
  const navigate = vi.fn();
  const diagnosis = { state: "blocked" as const, title: "Prepare the required step first", detail: "Open Parse & chunk and inspect its current state.", returnTo: "index" as const, terminalSteps: [] };
  render(<TerminalHandoff diagnosis={diagnosis} steps={[]} onNavigate={navigate} onRefresh={vi.fn().mockResolvedValue(true)} />);
  fireEvent.click(screen.getByRole("button", { name: "Check updated status" }));
  await screen.findByText("Preparation state updated");
  expect(screen.getByText(diagnosis.title)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Go to prerequisite step" }));
  expect(navigate).toHaveBeenCalledWith("index");
});

it("shows compact running status with an accessible refresh control and failure feedback", async () => {
  const diagnosis = { state: "running" as const, title: "This step is running", detail: "Follow the existing job.", returnTo: null, terminalSteps: [] };
  render(<TerminalHandoff compact blocking={false} diagnosis={diagnosis} steps={[]} onRefresh={vi.fn().mockResolvedValue(false)} />);
  expect(screen.getByText("Running")).not.toHaveAttribute("title");
  expect(screen.queryByText(diagnosis.title)).not.toBeInTheDocument();
  const refresh = screen.getByRole("button", { name: "Check updated status" });
  expect(refresh).toHaveTextContent("");
  fireEvent.click(refresh);
  expect(await screen.findByText("Could not refresh status. Check the connection and try again.")).toBeVisible();
});

it("acknowledges a compact refresh in the button without adding a status text row", async () => {
  const refresh = vi.fn().mockResolvedValue(true);
  const diagnosis = { state: "running" as const, title: "This step is running", detail: "Follow the existing job.", returnTo: null, terminalSteps: [] };
  render(<TerminalHandoff compact blocking={false} diagnosis={diagnosis} steps={[]} onRefresh={refresh} />);
  fireEvent.click(screen.getByRole("button", { name: "Check updated status" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Check updated status" })).toBeEnabled());
  expect(refresh).toHaveBeenCalledOnce();
  expect(screen.queryByText("Preparation state updated")).not.toBeInTheDocument();
  expect(screen.getByText("Running")).toBeVisible();
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
});


it("opens a custom hint on hover or focus and dismisses it on leave or Escape", () => {
  const diagnosis = { state: "running" as const, title: "This step is running", detail: "Follow the existing job.", returnTo: null, terminalSteps: [] };
  render(<TerminalHandoff compact diagnosis={diagnosis} steps={[]} onRefresh={vi.fn()} />);
  const state = screen.getByText("Running");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.mouseEnter(state);
  expect(screen.getByRole("tooltip")).toHaveTextContent(diagnosis.detail);
  expect(state).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
  fireEvent.mouseLeave(state.closest(".terminal-handoff-heading")!);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.focus(state);
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.keyDown(state, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  fireEvent.mouseEnter(screen.getByRole("button", { name: "Check updated status" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Check updated status");
});
