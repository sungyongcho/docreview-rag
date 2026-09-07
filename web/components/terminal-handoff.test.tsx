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
