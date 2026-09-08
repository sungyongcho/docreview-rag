import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, LOCALE_KEY } from "@/lib/i18n";
import { cancelOperatorJob, getOperatorCommands, getOperatorJobs, startOperatorJob, type OperatorCommand, type OperatorJob } from "@/lib/operator-api";
import { groupCommands, Operations, pollDelay } from "./operations";

const notifications = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("@/components/notifications", () => ({ useNotifications: () => notifications }));
vi.mock("@/lib/operator-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/operator-api")>(),
  getOperatorCommands: vi.fn(),
  getOperatorJobs: vi.fn(),
  startOperatorJob: vi.fn(),
  cancelOperatorJob: vi.fn(),
}));

function command(id: string, category: OperatorCommand["category"], label: string, confirmation: string | null = null, target: OperatorCommand["target"] = "python"): OperatorCommand {
  return { command_id: id, label, description: `${label} description`, category, target, confirmation, timeout_seconds: 60 };
}

/** Registry order from app/operator/commands.py, plus one synthetic confirmation-required verify command placed first. */
const COMMANDS: OperatorCommand[] = [
  command("git-status", "inspect", "Git status", null, "app"),
  command("verify-confirm", "verify", "Guarded verify", "Type YES"),
  command("python-lint", "verify", "Python lint"),
  command("python-format-check", "verify", "Python format check"),
  command("web-tests", "verify", "Web tests", null, "web"),
  command("schema-prepare", "service", "Prepare empty schema", "Create schema objects?", "database"),
  command("db-start", "service", "Start PostgreSQL", "Start the database?", "database"),
];

function job(status: OperatorJob["status"], output = ""): OperatorJob {
  return { job_id: "job-1", command_id: "python-lint", label: "Python lint", status, output, exit_code: status === "succeeded" ? 0 : null, started_at: "2026-09-07T00:00:00Z", finished_at: null };
}

const RUNNING = job("running", "linting…");
const FINISHED = job("succeeded", "done");
const FILTER_KEY = "docreview:operations-filter:v1";

async function flush(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

function headings(level: number): string[] {
  return screen.getAllByRole("heading", { level }).map((heading) => heading.textContent ?? "");
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(getOperatorCommands).mockResolvedValue(COMMANDS);
  vi.mocked(getOperatorJobs).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete (document as { visibilityState?: string }).visibilityState;
  localStorage.clear();
});

describe("groupCommands and pollDelay", () => {
  it("orders groups by category and puts confirmation-required commands last", () => {
    const groups = groupCommands(COMMANDS);
    expect(groups.map((group) => group.category)).toEqual(["inspect", "verify", "service"]);
    expect(groups[1].commands.map((entry) => entry.command_id)).toEqual(["python-lint", "python-format-check", "web-tests", "verify-confirm"]);
    expect(groups[2].commands.map((entry) => entry.command_id)).toEqual(["schema-prepare", "db-start"]);
    expect(groupCommands([])).toEqual([]);
  });

  it("backs off after failures and never polls a hidden tab faster than five seconds", () => {
    expect([0, 1, 2, 3, 4, 5].map((failures) => pollDelay(failures, true))).toEqual([1_000, 2_000, 4_000, 8_000, 10_000, 10_000]);
    expect(pollDelay(0, false)).toBe(5_000);
    expect(pollDelay(4, false)).toBe(10_000);
  });
});

describe("Operations", () => {
  it("groups commands by category, lists confirmation-required commands last and badges them", async () => {
    render(<Operations embedded helpId="system.operations" />);
    await flush();

    expect(headings(3)).toEqual(["Inspect", "Verify", "Service"]);
    const verify = screen.getByRole("heading", { level: 3, name: "Verify" }).closest("section");
    if (!verify) throw new Error("verify group missing");
    expect(within(verify).getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual(["Python lint", "Python format check", "Web tests", "Guarded verify"]);
    const guarded = within(verify).getByRole("heading", { level: 4, name: "Guarded verify" }).closest("article");
    const lint = within(verify).getByRole("heading", { level: 4, name: "Python lint" }).closest("article");
    if (!guarded || !lint) throw new Error("cards missing");
    expect(within(guarded).getByText("Confirmation required")).toHaveAttribute("title", "Type YES");
    expect(within(lint).queryByText("Confirmation required")).toBeNull();
    expect(document.querySelector(".command-card small")).toBeNull();
    expect(document.querySelector('[data-help="system.operations"]')).not.toBeNull();
  });

  it("filters groups by category and remembers the choice in this browser", async () => {
    const first = render(<Operations embedded />);
    await flush();
    fireEvent.click(within(screen.getByRole("group", { name: "Command category" })).getByRole("button", { name: "Service" }));
    expect(headings(3)).toEqual(["Service"]);
    expect(localStorage.getItem(FILTER_KEY)).toBe("service");
    first.unmount();

    render(<Operations embedded />);
    await flush();
    const filter = screen.getByRole("group", { name: "Command category" });
    expect(within(filter).getByRole("button", { name: "Service" })).toHaveAttribute("aria-pressed", "true");
    expect(headings(3)).toEqual(["Service"]);
    fireEvent.click(within(filter).getByRole("button", { name: "All" }));
    expect(localStorage.getItem(FILTER_KEY)).toBeNull();
    expect(headings(3)).toEqual(["Inspect", "Verify", "Service"]);
  });

  it("renders Korean group headings, filter and confirmation badge", async () => {
    localStorage.setItem(LOCALE_KEY, "ko");
    render(<I18nProvider><Operations embedded /></I18nProvider>);
    await flush();

    expect(headings(3)).toEqual(["점검", "검증", "서비스"]);
    expect(screen.getByRole("group", { name: "명령 유형" })).toBeInTheDocument();
    expect(screen.getAllByText("확인 필요")).toHaveLength(3);
    const targets = screen.getByRole("group", { name: "명령 대상" });
    expect(within(targets).getByRole("button", { name: "데이터베이스" })).toBeInTheDocument();
    expect(within(targets).getByRole("button", { name: "앱" })).toBeInTheDocument();
    fireEvent.click(within(targets).getByRole("button", { name: "웹" }));
    expect(document.querySelectorAll(".command-card")).toHaveLength(1);
    expect(document.querySelector(".command-card .target")).toHaveTextContent("웹");
  });

  it("runs a command after confirmation and cancels the running job", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(startOperatorJob).mockResolvedValue(RUNNING);
    vi.mocked(cancelOperatorJob).mockResolvedValue(job("cancelled"));
    render(<Operations embedded />);
    await flush();

    const card = screen.getByRole("heading", { level: 4, name: "Prepare empty schema" }).closest("article");
    if (!card) throw new Error("card missing");
    fireEvent.click(within(card).getByRole("button", { name: "Run" }));
    await flush();
    expect(window.confirm).toHaveBeenCalledWith("Create schema objects?");
    expect(startOperatorJob).toHaveBeenCalledWith("schema-prepare");
    expect(notifications.notify).toHaveBeenCalledWith("Prepare empty schema started.", "success", "operations-run", undefined, { event: "operations-run-notice" });

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await flush();
    expect(cancelOperatorJob).toHaveBeenCalledWith("job-1");
    expect(notifications.notify).toHaveBeenCalledWith("Command cancelled.", "success", "operations-cancel", undefined, { event: "operations-cancel-notice" });
  });

  it("polls a running job and shows one persistent notice after three failed polls, clearing it on recovery", async () => {
    const failure = new Error("ECONNREFUSED");
    vi.mocked(getOperatorJobs)
      .mockResolvedValueOnce([RUNNING])
      .mockRejectedValueOnce(failure)
      .mockRejectedValueOnce(failure)
      .mockRejectedValueOnce(failure)
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce([RUNNING])
      .mockResolvedValue([FINISHED]);
    render(<Operations embedded />);
    await flush();
    expect(screen.getByText(/Python lint · running/)).toBeInTheDocument();

    // Polls at 1 s, 3 s and 7 s fail: the third failure raises the single notice.
    await flush(7_500);
    expect(notifications.notify).toHaveBeenCalledTimes(1);
    expect(notifications.notify).toHaveBeenCalledWith("Local Operations is not responding. Retrying status checks.", "info", "operations-poll", 0, { event: "operations-poll-notice" });
    expect(notifications.dismissNotice).not.toHaveBeenCalled();
    expect(screen.getByText(/Python lint · running/)).toBeInTheDocument();

    // The 15 s poll fails as well without a second notice.
    await flush(8_500);
    expect(notifications.notify).toHaveBeenCalledTimes(1);

    // The 25 s poll succeeds and clears the notice; the next poll a second later delivers the finished job.
    await flush(9_500);
    expect(notifications.dismissNotice).toHaveBeenCalledWith("operations-poll");
    await flush(1_000);
    expect(screen.getByText(/Python lint · succeeded · exit 0/)).toBeInTheDocument();

    const calls = vi.mocked(getOperatorJobs).mock.calls.length;
    await flush(60_000);
    expect(vi.mocked(getOperatorJobs).mock.calls.length).toBe(calls);
    expect(calls).toBe(7);
    expect(notifications.notify.mock.calls.every(([, tone]) => tone !== "error")).toBe(true);
  });

  it("aborts the in-flight poll and clears the waiting notice on unmount", async () => {
    const failure = new Error("ECONNREFUSED");
    let captured: AbortSignal | undefined;
    vi.mocked(getOperatorJobs)
      .mockResolvedValueOnce([RUNNING])
      .mockRejectedValueOnce(failure)
      .mockRejectedValueOnce(failure)
      .mockRejectedValueOnce(failure)
      .mockImplementationOnce((signal) => { captured = signal; return new Promise(() => undefined); });
    const view = render(<Operations embedded />);
    await flush();
    await flush(15_500);
    expect(notifications.notify).toHaveBeenCalledTimes(1);
    expect(captured?.aborted).toBe(false);

    view.unmount();
    expect(captured?.aborted).toBe(true);
    expect(notifications.dismissNotice).toHaveBeenCalledWith("operations-poll");
  });

  it("slows polling to five seconds while the tab is hidden", async () => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    vi.mocked(getOperatorJobs).mockResolvedValueOnce([RUNNING]).mockResolvedValue([RUNNING]);
    render(<Operations embedded />);
    await flush();
    await flush(4_900);
    expect(getOperatorJobs).toHaveBeenCalledTimes(1);
    await flush(200);
    expect(getOperatorJobs).toHaveBeenCalledTimes(2);
  });
});


it("combines category and target filters and restores both without running a command", async () => {
  render(<Operations />);
  await flush();
  expect(screen.getByRole("heading", { name: "Git status" })).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("group", { name: "Command category" })).getByRole("button", { name: "Verify" }));
  fireEvent.click(within(screen.getByRole("group", { name: "Command target" })).getByRole("button", { name: "Web" }));
  expect(screen.getByRole("heading", { name: "Web tests" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Python lint" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Prepare empty schema" })).not.toBeInTheDocument();
  expect(startOperatorJob).not.toHaveBeenCalled();
  cleanup();
  render(<Operations />);
  await flush();
  expect(screen.getByRole("heading", { name: "Web tests" })).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Command category" })).getByRole("button", { name: "Verify" })).toHaveAttribute("aria-pressed", "true");
  expect(within(screen.getByRole("group", { name: "Command target" })).getByRole("button", { name: "Web" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(screen.getByRole("group", { name: "Command target" })).getByRole("button", { name: "Database" }));
  expect(screen.getByText("No commands match these filters.")).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("group", { name: "Command category" })).getByRole("button", { name: "Service" }));
  expect(screen.getByRole("heading", { name: "Prepare empty schema" })).toBeInTheDocument();
  expect(screen.queryByText("No commands match these filters.")).not.toBeInTheDocument();
});

it("keeps an older operator response visible without guessing its missing target", async () => {
  const { target: _target, ...legacy } = COMMANDS[0];
  vi.mocked(getOperatorCommands).mockResolvedValue([legacy as OperatorCommand]);
  render(<Operations />);
  await flush();
  expect(screen.getByRole("heading", { name: "Git status" })).toBeInTheDocument();
  expect(screen.getByText("Target not reported")).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("group", { name: "Command target" })).getByRole("button", { name: "App" }));
  expect(screen.getByText("No commands match these filters.")).toBeInTheDocument();
  expect(startOperatorJob).not.toHaveBeenCalled();
});
