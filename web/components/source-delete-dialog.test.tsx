import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { previewSourceDeletion } from "@/lib/api";
import { I18nProvider, LOCALE_KEY } from "@/lib/i18n";
import type { SourceDeletionPreview } from "@/lib/types";
import { RetainedPanel } from "./retained-panel";
import { SourceDeleteDialog } from "./source-delete-dialog";

vi.mock("@/lib/api", () => ({ previewSourceDeletion: vi.fn() }));

/** Use distinct same-year filing identities and a retained original in the exact preview. */
function preview(): SourceDeletionPreview {
  return { token: "reviewed-token", expires_at: Date.now() / 1000 + 300, retained_derived: true, retained_inputs: 2,
    documents: ["filing-a", "filing-b"].map((id) => ({ document_id: id, filing_id: `accession-${id}`, registry: "sec", issuer: "NVDA", fiscal_year: 2024 })),
    files: [{ path: "data/corpus/sec/filing-a.html", byte_length: 1024, retained: false }, { path: "data/corpus/sec/shared.html", byte_length: 2048, retained: true }],
  };
}

beforeEach(() => { vi.mocked(previewSourceDeletion).mockReset().mockResolvedValue(preview()); });
afterEach(() => { cleanup(); localStorage.clear(); vi.useRealTimers(); });

describe("source deletion confirmation", () => {
  it("previews exact IDs, distinguishes retained data and cancels without a queue request", async () => {
    const confirm = vi.fn();
    render(<SourceDeleteDialog documentIds={["filing-a", "filing-b", "filing-a"]} disabled={false} onConfirm={confirm} />);
    const trigger = screen.getByRole("button", { name: "Delete all downloaded originals" });
    trigger.focus(); fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveFocus();
    await screen.findByText("accession-filing-b");
    expect(previewSourceDeletion).toHaveBeenCalledExactlyOnceWith(["filing-a", "filing-b"]);
    expect(dialog).toHaveTextContent("To use deleted originals again, download them again in Filings.");
    expect(dialog).toHaveTextContent("Database documents, chunks, embeddings, and past job inputs are preserved.");
    expect(screen.getByText("data/corpus/sec/shared.html").closest("li")).toHaveTextContent("Preserved shared or past input");
    expect(dialog).toHaveTextContent("Past job inputs preserved: 2");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("requires confirmation of the token and reports queued status until Jobs completes", async () => {
    const confirm = vi.fn().mockResolvedValue(undefined); const jobs = vi.fn();
    render(<SourceDeleteDialog documentIds={["filing-a", "filing-b"]} disabled={false} onConfirm={confirm} onOpenJobs={jobs} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete all downloaded originals" }));
    const button = await screen.findByRole("button", { name: "Confirm deletion of originals" });
    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(button);
    await screen.findByText("Source deletion queued. Files are not deleted yet; check Jobs for the result.");
    expect(confirm).toHaveBeenCalledExactlyOnceWith("reviewed-token");
    fireEvent.click(screen.getByRole("button", { name: "Open Jobs" }));
    expect(jobs).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each(["preview", "confirm"])("keeps raw %s errors inline and requires a fresh preview", async (failure) => {
    const confirm = vi.fn().mockRejectedValue(new Error("exact server failure"));
    if (failure === "preview") vi.mocked(previewSourceDeletion).mockRejectedValueOnce(new Error("exact server failure"));
    render(<SourceDeleteDialog documentIds={["filing-a"]} disabled={false} onConfirm={confirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete all downloaded originals" }));
    if (failure === "confirm") fireEvent.click(await screen.findByRole("button", { name: "Confirm deletion of originals" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("exact server failure");
    expect(screen.getByRole("dialog")).toContainElement(screen.getByRole("alert"));
    expect(screen.queryByRole("button", { name: "Confirm deletion of originals" })).toBeNull();
    expect(screen.getByRole("button", { name: "Review deletion preview" })).toBeEnabled();
  });

  it("can cancel a pending preview and ignores its late response", async () => {
    let resolve!: (value: SourceDeletionPreview) => void;
    vi.mocked(previewSourceDeletion).mockReturnValue(new Promise((done) => { resolve = done; }));
    const confirm = vi.fn();
    render(<SourceDeleteDialog documentIds={["filing-a"]} disabled={false} onConfirm={confirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete all downloaded originals" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await act(async () => resolve(preview()));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("traps focus, hides retained portals, and disables confirmation after runtime becomes busy", async () => {
    const props = { documentIds: ["filing-a"], disabled: false, onConfirm: vi.fn() };
    const { rerender } = render(<RetainedPanel active><SourceDeleteDialog {...props} /></RetainedPanel>);
    fireEvent.click(screen.getByRole("button", { name: "Delete all downloaded originals" }));
    const confirm = await screen.findByRole("button", { name: "Confirm deletion of originals" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    confirm.focus(); fireEvent.keyDown(window, { key: "Tab" }); expect(cancel).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true }); expect(confirm).toHaveFocus();
    rerender(<RetainedPanel active={false}><SourceDeleteDialog {...props} /></RetainedPanel>);
    expect(screen.queryByRole("dialog")).toBeNull();
    rerender(<RetainedPanel active><SourceDeleteDialog {...props} disabled /></RetainedPanel>);
    expect(screen.getByRole("button", { name: "Confirm deletion of originals" })).toBeDisabled();
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it("invalidates an expired token and explains an empty physical deletion set", async () => {
    vi.useFakeTimers();
    vi.mocked(previewSourceDeletion).mockResolvedValue({ ...preview(), expires_at: Date.now() / 1000 + 1, files: [] });
    render(<SourceDeleteDialog documentIds={["filing-a"]} disabled={false} onConfirm={vi.fn()} />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete all downloaded originals" })); });
    expect(screen.getByText("No physical files will be deleted. Only the selected acquisition records may be removed.")).toBeVisible();
    await act(async () => { vi.advanceTimersByTime(1001); });
    expect(screen.getByRole("alert")).toHaveTextContent("The deletion preview expired.");
    expect(screen.queryByRole("button", { name: "Confirm deletion of originals" })).toBeNull();
  });

  it("localizes the warning and keeps the explicit confirmation visible in Korean", async () => {
    localStorage.setItem(LOCALE_KEY, "ko");
    render(<I18nProvider><SourceDeleteDialog documentIds={["filing-a"]} disabled={false} onConfirm={vi.fn()} /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "다운로드 원문 모두 삭제" }));
    await screen.findByRole("button", { name: "원본 삭제 확인" });
    expect(screen.getByRole("dialog")).toHaveTextContent("다시 다운로드해야 합니다.");
    expect(screen.getByRole("dialog")).toHaveTextContent("DB 문서·청크·임베딩과 과거 작업 입력은 보존됩니다.");
  });
});
