import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { I18nProvider, translate } from "@/lib/i18n";
import { scopeFailurePatch, scopeFailureProgress, publicScopeFailure } from "@/lib/scope-failure";
import type { ChatMessage } from "@/lib/types";
import { ScopeFailureSummary } from "./scope-failure-summary";
import { ReviewProgressSteps, initialReviewProgress, finishReviewProgress, phaseStatus, reviewProgressFromEvent } from "./review-progress";

afterEach(cleanup);

const error = new ApiError(503, "query_scope_unavailable", "Query scope metadata is unavailable.", undefined, { failed_stage: "path", cause: "invalid_json", path: "data/corpus/manifest.json", detail: "ValueError: broken JSON at line 3" });

it.each(["en", "ko"] as const)("renders DEV cause, file, terminal checks and one mapped action (%s)", (locale) => {
  localStorage.setItem("docreview.locale", locale);
  const onOpenFix = vi.fn();
  const message = { id: "error", role: "assistant", ...scopeFailurePatch(error, true) } as ChatMessage;
  render(<I18nProvider><ScopeFailureSummary message={message} developer onOpenFix={onOpenFix} /></I18nProvider>);
  expect(screen.getByText(translate(locale, "The corpus manifest is not valid JSON."))).toBeVisible();
  expect(screen.getByText("data/corpus/manifest.json")).toBeVisible();
  expect(screen.getByText("rag-dev schema check")).toBeVisible();
  expect(screen.getByText("rag-dev corpus status")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: translate(locale, "Open Documents") }));
  expect(onOpenFix).toHaveBeenCalledWith("documents");
  expect(message.trace).toContain("broken JSON at line 3");
});

it("opens Jobs when a recent acquisition job is available and explains active writes", () => {
  const jobError = new ApiError(503, error.code, error.message, undefined, { ...error.failure, corpus_job: { job_id: "admin-source", status: "running" } });
  const message = { id: "job", role: "assistant", ...scopeFailurePatch(jobError, true) } as ChatMessage;
  const open = vi.fn();render(<ScopeFailureSummary message={message} developer onOpenFix={open} />);
  expect(screen.getByText("admin-source")).toBeVisible();
  fireEvent.click(screen.getByRole("button"));expect(open).toHaveBeenCalledWith("jobs");
});

it("hides all DEV diagnostic fields from a public failure and a saved DEV failure", () => {
  const original = { id: "error", role: "assistant", ...scopeFailurePatch(error, true) } as ChatMessage;
  const message = publicScopeFailure(original, false)!;
  render(<ScopeFailureSummary message={message} developer={false} onOpenFix={vi.fn()} />);
  expect(screen.queryByText("data/corpus/manifest.json")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
  expect(message.trace).toBeUndefined();expect(message.failureFix).toBeUndefined();
  expect(scopeFailurePatch(error, false)?.scopeFailure?.path).toBeUndefined();
});

it("marks the pre-decision error at stage zero and leaves stages one to five unrun", () => {
  const progress = finishReviewProgress(scopeFailureProgress(error, initialReviewProgress()), "failed", 10);
  expect([0, 1, 2, 3, 4].map(i => phaseStatus(progress, i))).toEqual(Array(5).fill("not-run"));
  const { container } = render(<ReviewProgressSteps state={progress} />);
  expect(container.querySelector(".review-progress-steps li")).toHaveClass("failed");
});

it("keeps path telemetry separate from later scope resolution failures", () => {
  let state = reviewProgressFromEvent({ display_stage: "path", node: "gate", phase: "end", status: "completed", evidence_count: 0, relevant_count: 0, step_count: 0 }, initialReviewProgress());
  state = reviewProgressFromEvent({ node: "route", phase: "end", status: "failed", evidence_count: 0, relevant_count: 0, step_count: 0 }, state);
  expect(state.pathStatus).toBe("done");expect(phaseStatus(state, 0)).toBe("failed");
  expect(phaseStatus(state, 1)).toBe("not-run");
});
