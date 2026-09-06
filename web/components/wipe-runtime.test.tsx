import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearDocReviewBrowserData, WipeRuntime } from "./wipe-runtime";
import { RetainedPanel } from "./retained-panel";
import { getWipeCapability, getWipeStatus, OperatorRequestError, previewWipe, recoverWipe, startWipe, type WipeCapability, type WipePreview, type WipeResult } from "@/lib/operator-api";

vi.mock("@/lib/operator-api", async (importOriginal) => ({ ...await importOriginal<typeof import("@/lib/operator-api")>(), operatorAvailable: () => true, getWipeCapability: vi.fn(), previewWipe: vi.fn(), recoverWipe: vi.fn(), startWipe: vi.fn(), getWipeStatus: vi.fn() }));
beforeEach(() => {
  vi.mocked(getWipeCapability).mockResolvedValue({ available: true, reason: null });
  vi.mocked(getWipeStatus).mockResolvedValue({ status: "idle", completed: [] });
  vi.mocked(previewWipe).mockImplementation(async (): Promise<WipePreview> => ({ token: "preview-1", expires: Date.now() / 1000 + 300, confirmation: "WIPE test", backup: false, preserved: [], target: { project: "test", volume: "test_pg_data", tables: { documents: 2 }, files: [] } }));
});
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); localStorage.clear(); });

async function openPreview() {
  fireEvent.click(screen.getByText("Reset runtime data"));
  const action = screen.getByRole("button", { name: "Wipe everything" });
  await waitFor(() => expect(action).toBeEnabled());
  fireEvent.click(action);
  return screen.findByRole("textbox");
}

it("does not expose the destructive action in public or prod UI", () => {
  render(<WipeRuntime enabled={false} />);
  expect(screen.queryByText("Wipe everything")).not.toBeInTheDocument();
  expect(getWipeCapability).not.toHaveBeenCalled();
  expect(getWipeStatus).not.toHaveBeenCalled();
  expect(previewWipe).not.toHaveBeenCalled();
});

it("keeps a delayed reset recovery dialog dormant while an ancestor workspace is hidden", async () => {
  let resolveStatus!: (status: WipeResult) => void;
  vi.mocked(getWipeStatus).mockReturnValue(new Promise((resolve) => { resolveStatus = resolve; }));
  const content = (active: boolean) => <><button>Other workspace</button><RetainedPanel active={active}><RetainedPanel active><WipeRuntime enabled /></RetainedPanel></RetainedPanel></>;
  const { rerender } = render(content(true));
  rerender(content(false));
  await act(async () => resolveStatus({ status: "interrupted", completed: [], recovery: ["Inspect retained audit."] }));
  expect(screen.queryByRole("dialog")).toBeNull();
  const other = screen.getByRole("button", { name: "Other workspace" });
  other.focus();
  fireEvent.keyDown(other, { key: "Tab" });
  expect(other).toHaveFocus();
  fireEvent.keyDown(other, { key: "Escape" });
  rerender(content(true));
  expect(screen.getByRole("dialog", { name: "Delete all runtime data?" })).toBeVisible();
  expect(screen.getByText("Inspect retained audit.")).toBeVisible();
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
});

it("keeps reset disabled until capability and status are verified without creating a preview", async () => {
  let resolveCapability!: (capability: WipeCapability) => void;
  vi.mocked(getWipeCapability).mockReturnValue(new Promise((resolve) => { resolveCapability = resolve; }));
  render(<WipeRuntime enabled />);
  fireEvent.click(screen.getByText("Reset runtime data"));
  const action = screen.getByRole("button", { name: "Wipe everything" });
  expect(action).toBeDisabled();
  await act(async () => { resolveCapability({ available: true, reason: null }); });
  expect(action).toBeEnabled();
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
});

it("shows unavailable capability and rechecks it only to enable a fresh manual preview", async () => {
  vi.mocked(getWipeCapability).mockResolvedValueOnce({ available: false, reason: "The request gate is unavailable" });
  render(<WipeRuntime enabled />);
  fireEvent.click(screen.getByText("Reset runtime data"));
  expect(await screen.findByText("The request gate is unavailable")).toBeVisible();
  expect(screen.getByRole("button", { name: "Wipe everything" })).toBeDisabled();
  expect(previewWipe).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Check reset availability" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Wipe everything" })).toBeEnabled());
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
});

it("keeps reset disabled when status cannot be read even if capability is available", async () => {
  vi.mocked(getWipeStatus).mockRejectedValue(new Error("Status request failed"));
  render(<WipeRuntime enabled />);
  fireEvent.click(screen.getByText("Reset runtime data"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Status request failed");
  expect(screen.getByRole("button", { name: "Wipe everything" })).toBeDisabled();
  expect(previewWipe).not.toHaveBeenCalled();
});

it("requires exact confirmation and keeps browser data when reset fails", async () => {
  localStorage.setItem("docreview:conversations:v2", "keep");
  vi.mocked(startWipe).mockResolvedValue({ status: "failed", stage: "runtime_files", message: "File changed", completed: ["database_removed"], recovery: ["Restore the development stack before requesting a new preview."] });
  render(<WipeRuntime enabled />);
  const input = await openPreview();
  expect(screen.getByText("No backup. This cannot be undone.")).toBeVisible();
  const action = screen.getByRole("button", { name: "Permanently clear this runtime" });
  fireEvent.change(input, { target: { value: "WIPE wrong" } });
  expect(action).toBeDisabled();
  expect(startWipe).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "WIPE test" } });
  fireEvent.click(action);
  await waitFor(() => expect(startWipe).toHaveBeenCalledWith("preview-1", "WIPE test"));
  expect(await screen.findByText("File changed")).toBeVisible();
  expect(screen.getByText("Restore the development stack before requesting a new preview.")).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(localStorage.getItem("docreview:conversations:v2")).toBe("keep");
  expect(screen.queryByRole("button", { name: "Clear browser data and start again" })).not.toBeInTheDocument();
});

it("invalidates confirmation if the capability disappears before execution", async () => {
  render(<WipeRuntime enabled />);
  const input = await openPreview();
  vi.mocked(getWipeCapability).mockResolvedValue({ available: false, reason: "Application restarted" });
  fireEvent.change(input, { target: { value: "WIPE test" } });
  fireEvent.click(screen.getByRole("button", { name: "Permanently clear this runtime" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Application restarted");
  expect(startWipe).not.toHaveBeenCalled();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

it("discards an expired preview and never sends its token", async () => {
  render(<WipeRuntime enabled />);
  await openPreview();
  fireEvent.click(screen.getByRole("button", { name: "Close reset dialog" }));
  fireEvent.click(screen.getByRole("button", { name: "Reset runtime data" }));
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "Wipe everything" }));
  await act(async () => { await Promise.resolve(); });
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "WIPE test" } });
  await act(async () => { vi.advanceTimersByTime(300001); });
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("The reset preview expired");
  expect(startWipe).not.toHaveBeenCalled();
});

it("discards a rejected token and reads the recorded state without retrying deletion", async () => {
  render(<WipeRuntime enabled />);
  const input = await openPreview();
  vi.mocked(startWipe).mockRejectedValue(new Error("Preview token is no longer valid"));
  vi.mocked(getWipeStatus).mockResolvedValue({ status: "interrupted", stage: "database_removed", completed: ["database_removed"], recovery: ["Inspect the retained audit before restoring the stack."] });
  fireEvent.change(input, { target: { value: "WIPE test" } });
  fireEvent.click(screen.getByRole("button", { name: "Permanently clear this runtime" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Preview token is no longer valid");
  expect(await screen.findByText("Inspect the retained audit before restoring the stack.")).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(startWipe).toHaveBeenCalledTimes(1);
});

it("restores interrupted partial status after remount and releases a hold only on explicit action", async () => {
  const recovery = { status: "interrupted", stage: "app_stopped", message: "Operator restarted during reset", completed: ["app_stopped"], recovery: ["Release the reset hold after checking the recorded state."], recovery_required: true, retryable: false };
  vi.mocked(getWipeCapability).mockResolvedValue({ available: false, reason: "Recovery required" });
  vi.mocked(getWipeStatus).mockResolvedValue(recovery);
  vi.mocked(recoverWipe).mockResolvedValue({ ...recovery, recovery_required: false });
  render(<WipeRuntime enabled />);
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(screen.getByText("Operator restarted during reset")).toBeVisible();
  expect(screen.getByText("Release the reset hold after checking the recorded state.")).toBeVisible();
  expect(recoverWipe).not.toHaveBeenCalled();
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
  vi.mocked(getWipeStatus).mockResolvedValue({ ...recovery, recovery_required: false });
  fireEvent.click(screen.getByRole("button", { name: "Release reset hold" }));
  await waitFor(() => expect(recoverWipe).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Release reset hold" })).not.toBeInTheDocument());
  expect(startWipe).not.toHaveBeenCalled();
  expect(previewWipe).not.toHaveBeenCalled();
});

it("waits for successful server status before offering browser cleanup", async () => {
  localStorage.setItem("docreview:conversations:v2", "keep");
  vi.mocked(startWipe).mockResolvedValue({ status: "running", completed: [] });
  render(<WipeRuntime enabled />);
  const input = await openPreview();
  vi.useFakeTimers();
  fireEvent.change(input, { target: { value: "WIPE test" } });
  fireEvent.click(screen.getByRole("button", { name: "Permanently clear this runtime" }));
  await act(async () => { await Promise.resolve(); });
  expect(screen.queryByRole("button", { name: "Clear browser data and start again" })).not.toBeInTheDocument();
  vi.mocked(getWipeStatus).mockResolvedValue({ status: "succeeded", completed: ["empty_schema_created"] });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(screen.getByRole("button", { name: "Clear browser data and start again" })).toBeEnabled();
  expect(localStorage.getItem("docreview:conversations:v2")).toBe("keep");
});

it("clears only this application's browser keys after successful server reset", () => {
  localStorage.setItem("docreview:conversations:v2", "old");
  localStorage.setItem("docreview.locale", "ko");
  localStorage.setItem("other-app", "preserve");
  clearDocReviewBrowserData(localStorage);
  expect(localStorage.getItem("docreview:conversations:v2")).toBeNull();
  expect(localStorage.getItem("docreview.locale")).toBe("ko");
  expect(localStorage.getItem("other-app")).toBe("preserve");
});

it("reports check success and its time only after runtime status also resolves", async () => {
  let resolveStatus!: (status: WipeResult) => void;
  vi.mocked(getWipeStatus).mockReturnValue(new Promise((resolve) => { resolveStatus = resolve; }));
  vi.mocked(getWipeCapability).mockResolvedValue({ available: true, reason: null, checked_at: "2026-09-05T14:00:00+00:00" });
  render(<WipeRuntime enabled />);
  fireEvent.click(screen.getByText("Reset runtime data"));
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole("button", { name: "Wipe everything" })).toBeDisabled();
  expect(screen.getByText("Checking reset availability…")).toBeVisible();
  await act(async () => { resolveStatus({ status: "idle", completed: [] }); });
  expect(screen.getByText("Reset is available. All preview checks passed.")).toBeVisible();
  expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-09-05T14:00:00+00:00");
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
});

it("shows the exact permission diagnosis and allows cancellation after a preview error", async () => {
  const detail = {
    code: "runtime_file_permission",
    details: { path: "data/local-settings/local-llm.json", parent: { uid: 65534, mode: "0755" }, operator_uid: 1000 },
    remediation: ["Ask the owner to grant access.", "sudo setfacl -m u:1000:r -- /tmp/runtime/local-llm.json"],
  };
  vi.mocked(previewWipe).mockRejectedValue(new OperatorRequestError("Runtime file cannot be removed by this operator: data/local-settings/local-llm.json", detail));
  const { container } = render(<WipeRuntime enabled />);
  fireEvent.click(screen.getByText("Reset runtime data"));
  const trigger = screen.getByRole("button", { name: "Wipe everything" });
  await waitFor(() => expect(trigger).toBeEnabled());
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Delete all runtime data?" });
  expect(container).not.toContainElement(dialog);
  expect(await screen.findByRole("alert")).toHaveTextContent("local-llm.json");
  expect(screen.getByRole("region", { name: "Reset diagnosis" })).toBeVisible();
  expect(screen.getByText("runtime_file_permission")).toBeVisible();
  expect(screen.getByText("Ask the owner to grant access.")).toBeVisible();
  expect(screen.getByText("sudo setfacl -m u:1000:r -- /tmp/runtime/local-llm.json")).toBeVisible();
  const cancel = screen.getByRole("button", { name: "Cancel" });
  expect(cancel).toBeEnabled();
  fireEvent.click(cancel);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reset runtime data" })).toHaveFocus();
  expect(startWipe).not.toHaveBeenCalled();
});

it("traps keyboard focus and cancels the final confirmation without executing reset", async () => {
  render(<WipeRuntime enabled />);
  const input = await openPreview();
  expect(screen.getByRole("dialog", { name: "Delete all runtime data?" })).toHaveFocus();
  fireEvent.keyDown(window, { key: "Tab" });
  expect(screen.getByRole("button", { name: "Close reset dialog" })).toHaveFocus();
  fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  fireEvent.change(input, { target: { value: "WIPE test" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(startWipe).not.toHaveBeenCalled();
});

it("immediately discards a prior preview while an availability recheck is pending", async () => {
  render(<WipeRuntime enabled />);
  const input = await openPreview();
  fireEvent.change(input, { target: { value: "WIPE test" } });
  vi.mocked(getWipeCapability).mockReturnValue(new Promise(() => {}));
  fireEvent.click(screen.getByRole("button", { name: "Check reset availability" }));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Permanently clear this runtime" })).not.toBeInTheDocument();
  expect(startWipe).not.toHaveBeenCalled();
});

it("opens a terminal-initiated completed reset without submitting another wipe", async () => {
  render(<WipeRuntime enabled />);
  fireEvent.click(screen.getByText("Reset runtime data"));
  const status = screen.getByRole("button", { name: "View reset status" });
  await waitFor(() => expect(status).toBeEnabled());
  vi.mocked(getWipeStatus).mockResolvedValue({ id: "terminal-reset", status: "succeeded", completed: ["empty_schema_created"] });
  fireEvent.click(status);
  expect(await screen.findByRole("button", { name: "Clear browser data and start again" })).toBeEnabled();
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
  expect(screen.getByText(/run rag-fresh-start/)).toBeInTheDocument();
});


it("opens all reset controls in a popup and returns focus without clearing data", async () => {
  localStorage.setItem("docreview:conversations:v2", "keep");
  const { container } = render(<WipeRuntime enabled />);
  const trigger = screen.getByRole("button", { name: "Reset runtime data" });
  expect(container.querySelector("details")).toBeNull();
  expect(screen.queryByRole("button", { name: "Wipe everything" })).not.toBeInTheDocument();
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog");
  expect(container).not.toContainElement(dialog);
  expect(dialog).toHaveFocus();
  await waitFor(() => expect(screen.getByRole("button", { name: "Wipe everything" })).toBeEnabled());
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(previewWipe).not.toHaveBeenCalled();
  expect(startWipe).not.toHaveBeenCalled();
  expect(recoverWipe).not.toHaveBeenCalled();
  expect(localStorage.getItem("docreview:conversations:v2")).toBe("keep");
});
