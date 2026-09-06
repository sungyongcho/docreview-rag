import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ResetLocalPage from "./page";
import { acknowledgeWipeBrowser, getWipeStatus } from "@/lib/operator-api";
vi.mock("@/lib/operator-api", () => ({ operatorAvailable: () => true, getWipeStatus: vi.fn(), acknowledgeWipeBrowser: vi.fn() }));
afterEach(() => { cleanup(); localStorage.clear(); vi.resetAllMocks(); });
it("does not delete browser data for a stale operation", async () => {
  window.location.hash = "old";
  localStorage.setItem("docreview:conversations:v2", "keep");
  vi.mocked(getWipeStatus).mockResolvedValue({ id: "current", extreme: true, status: "running", stage: "awaiting_browser", completed: [] });
  render(<ResetLocalPage />);
  fireEvent.click(screen.getByRole("button"));
  await screen.findByText(/could not be confirmed/);
  expect(localStorage.getItem("docreview:conversations:v2")).toBe("keep");
  expect(acknowledgeWipeBrowser).not.toHaveBeenCalled();
});
it("acknowledges only after storage deletion for the matching operation", async () => {
  window.location.hash = "current";
  localStorage.setItem("docreview:conversations:v2", "erase");
  vi.mocked(getWipeStatus).mockResolvedValue({ id: "current", extreme: true, status: "running", stage: "awaiting_browser", completed: [] });
  vi.mocked(acknowledgeWipeBrowser).mockImplementation(async id => {
    expect(localStorage.getItem("docreview:conversations:v2")).toBeNull();
    return { id, acknowledged: true };
  });
  render(<ResetLocalPage />);
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(acknowledgeWipeBrowser).toHaveBeenCalledWith("current"));
  await screen.findByText(/terminal received acknowledgement/);
});
