import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { OperatorJob } from "@/lib/types";
import { SearchUpdateStatus } from "./search-update-status";

const job = { job_id: "parse-1", domain: "corpus", kind: "ingest_manifest", status: "running", overall_current: 43, overall_total: 100, updated_at: "2026-09-08T19:00:00Z" } as OperatorJob;
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("shows actual progress on hover and an accessible job action on click", () => {
  const onOpenJobs = vi.fn();
  render(<SearchUpdateStatus updating preparation={null} jobs={[job]} onOpenJobs={onOpenJobs} />);
  const button = screen.getByRole("button", { name: "Search paused" });
  fireEvent.mouseEnter(button);
  expect(screen.getByRole("tooltip")).toHaveTextContent("43%");
  fireEvent.click(button);
  expect(screen.getByRole("dialog")).toHaveTextContent("Parsing / chunking");
  fireEvent.click(screen.getByRole("button", { name: "View jobs" }));
  expect(onOpenJobs).toHaveBeenCalledWith("parse-1");
});

it("keeps preparation warnings and only dismisses after search is ready", () => {
  vi.useFakeTimers();
  const props = { jobs: [job], onOpenJobs: vi.fn() };
  const { rerender } = render(<SearchUpdateStatus {...props} updating preparation={null} />);
  rerender(<SearchUpdateStatus {...props} updating={false} preparation="Rebuild BM25 first." />);
  act(() => vi.advanceTimersByTime(3000));
  expect(screen.getByRole("button", { name: "Search preparation needed" })).toBeInTheDocument();
  rerender(<SearchUpdateStatus {...props} updating={false} preparation={null} />);
  expect(screen.getByRole("button", { name: "Search ready" })).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(2500));
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("does not report stale progress or show an update for downloads alone", () => {
  const { rerender } = render(<SearchUpdateStatus updating={false} preparation={null} jobs={[{ ...job, kind: "acquire_dart" }]} onOpenJobs={vi.fn()} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  rerender(<SearchUpdateStatus updating preparation={null} stale jobs={[job]} onOpenJobs={vi.fn()} />);
  fireEvent.focus(screen.getByRole("button"));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Checking current job progress");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
