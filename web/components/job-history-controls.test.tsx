import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJobHistorySummary, manageJobHistory } from "@/lib/api";
import { JobHistoryControls } from "./job-history-controls";
vi.mock("@/lib/api", () => ({ getJobHistorySummary: vi.fn(), manageJobHistory: vi.fn(), jobHistoryBackupUrl: (id: string) => `/admin/jobs/history/backups/${id}` }));
beforeEach(() => { vi.mocked(getJobHistorySummary).mockResolvedValue({ visible: 3, archived: 2, active: 1 }); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("only reads on open, traps focus, and returns focus on Escape", async () => {
  render(<JobHistoryControls onChanged={vi.fn()} />);
  const trigger = screen.getByRole("button", { name: "Manage history" });
  fireEvent.click(trigger);
  await screen.findByText("3 visible · 2 archived · 1 active");
  expect(manageJobHistory).not.toHaveBeenCalled();
  fireEvent.keyDown(window, { key: "Tab" });
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
  expect(screen.getByRole("textbox")).toHaveFocus();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
it("requires exact confirmation and exposes the server backup after deletion", async () => {
  const onChanged = vi.fn();
  vi.mocked(manageJobHistory).mockResolvedValue({ action: "delete", changed_count: 5, backup_id: "backup-1", summary: { visible: 0, archived: 0, active: 1 } });
  render(<JobHistoryControls onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage history" }));
  await screen.findByText("3 visible · 2 archived · 1 active");
  const remove = screen.getByRole("button", { name: "Delete job history" });
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "delete job history" } });
  expect(remove).toBeDisabled();
  expect(manageJobHistory).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "DELETE JOB HISTORY" } });
  fireEvent.click(remove);
  expect(await screen.findByRole("link", { name: "Download job history backup" })).toHaveAttribute("href", "/admin/jobs/history/backups/backup-1");
  expect(manageJobHistory).toHaveBeenCalledWith({ action: "delete", expected_count: 5, confirmation: "DELETE JOB HISTORY" });
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(remove).toBeDisabled();
});
it.each(["archive", "restore"] as const)("%s uses its own eligible count", async (action) => {
  const onChanged = vi.fn();
  vi.mocked(manageJobHistory).mockResolvedValue({ action, changed_count: action === "archive" ? 3 : 2, backup_id: null, summary: { visible: 0, archived: 5, active: 1 } });
  render(<JobHistoryControls onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage history" }));
  await screen.findByText("3 visible · 2 archived · 1 active");
  fireEvent.click(screen.getByRole("button", { name: action === "archive" ? "Archive finished jobs" : "Restore archived jobs" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(manageJobHistory).toHaveBeenCalledWith({ action, expected_count: action === "archive" ? 3 : 2 });
});
it("invalidates counts after failure and only rechecks on manual sync", async () => {
  vi.mocked(manageJobHistory).mockRejectedValue(new Error("History changed; refresh first"));
  const onChanged = vi.fn();
  render(<JobHistoryControls onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage history" }));
  await screen.findByText("3 visible · 2 archived · 1 active");
  fireEvent.click(screen.getByRole("button", { name: "Archive finished jobs" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("History changed");
  expect(manageJobHistory).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Archive finished jobs" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Sync history" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(getJobHistorySummary).toHaveBeenCalledTimes(2);
});

it("retains deletion evidence when refreshing the board fails", async () => {
  vi.mocked(manageJobHistory).mockResolvedValue({ action: "delete", changed_count: 5, backup_id: "backup-2", summary: { visible: 0, archived: 0, active: 1 } });
  render(<JobHistoryControls onChanged={() => { throw new Error("Offline"); }} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage history" }));
  await screen.findByText("3 visible · 2 archived · 1 active");
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "DELETE JOB HISTORY" } });
  fireEvent.click(screen.getByRole("button", { name: "Delete job history" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("History changed successfully");
  expect(screen.getByText("Updated 5 job records.")).toBeVisible();
  expect(screen.getByRole("link", { name: "Download job history backup" })).toBeVisible();
  expect(manageJobHistory).toHaveBeenCalledTimes(1);
});
