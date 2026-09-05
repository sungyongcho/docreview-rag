"use client";

import { Check, Circle, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { ReviewProgress } from "@/lib/api";
import type { CorpusScope, ReviewEventNode, ReviewExecution, ReviewResolvedScope } from "@/lib/types";

export type ReviewNode = ReviewEventNode;
export type ReviewProgressState = ReviewExecution;

export const REVIEW_STEPS = [
  { node: "gate", label: "Understand the question", detail: "Intent and filing scope" },
  { node: "retrieve", label: "Retrieve evidence", detail: "Search the prepared corpus" },
  { node: "grade", label: "Select relevant evidence", detail: "Evaluate candidate support" },
  { node: "check", label: "Verify answer and citations", detail: "Check claims against sources" },
  { node: "report", label: "Prepare the result", detail: "Return the verified outcome" },
] as const;

export function currentStepIndex(node: ReviewNode): number {
  if (["waiting", "gate", "route"].includes(node)) return 0;
  if (node === "candidates" || node === "retrieve") return 1;
  return REVIEW_STEPS.findIndex((step) => step.node === node);
}

/** Keep the current pass; later-phase evidence is superseded when retrieval repeats. */
function advanceProgress(node: ReviewNode, evidence: number, relevant: number, steps: number, previous?: ReviewProgressState): ReviewProgressState {
  const phase = currentStepIndex(node);
  const retry = Boolean(previous && phase >= 0 && phase < currentStepIndex(previous.node));
  const retained = retry ? (previous?.observed ?? []).filter((item) => currentStepIndex(item) < phase) : previous?.observed ?? [];
  return { ...previous, node, evidence, relevant, steps, observed: [...new Set([...retained, node])], outcome: "running", retries: (previous?.retries ?? 0) + (retry ? 1 : 0) };
}

export function reviewProgressFromEvent(event: ReviewProgress, previous?: ReviewProgressState): ReviewProgressState {
  const next = advanceProgress(event.node, event.evidence_count ?? previous?.evidence ?? 0, event.relevant_count ?? previous?.relevant ?? 0, event.step_count ?? previous?.steps ?? 0, previous);
  const phase = currentStepIndex(event.node);
  const repeated = previous && phase < currentStepIndex(previous.node);
  const completed = repeated ? (previous.completedNodes ?? []).filter((node) => currentStepIndex(node) < phase) : previous?.completedNodes ?? [];
  return { ...next, lastEventAt: Date.now(), activeNode: event.phase === "start" ? event.node : null,
    resolvedScope: resolvedScopeFromServer(event.resolved_scope) ?? previous?.resolvedScope,
    completedNodes: event.phase === "start" || event.status === "failed" ? completed : [...new Set([...completed, event.node])],
    outcome: event.status === "failed" ? "failed" : "running",
    stageTimings: event.phase === "end" && typeof event.elapsed_ms === "number" ? [...(previous?.stageTimings ?? []), { node: event.node, elapsed_ms: event.elapsed_ms, status: event.status ?? "completed" }] : previous?.stageTimings };
}

export function initialReviewProgress(revalidating = false, evidence = 0, selectedScope?: CorpusScope): ReviewProgressState {
  return { node: "waiting", selectedScope, evidence, relevant: 0, steps: 0, observed: [], outcome: "running", revalidating, retries: 0, startedAt: Date.now(), activeNode: null, completedNodes: [] };
}

export function candidateProgress(previous: ReviewProgressState, evidence: number, resolvedScope?: unknown): ReviewProgressState {
  const next = advanceProgress("candidates", evidence, 0, previous.steps, previous);
  return { ...next, resolvedScope: resolvedScopeFromServer(resolvedScope) ?? previous.resolvedScope, lastEventAt: Date.now(), activeNode: previous.activeNode === "retrieve" ? "retrieve" : null, completedNodes: [...(previous.completedNodes ?? []).filter((node) => currentStepIndex(node) < 1), "candidates"] };
}

/** Only actual observed phases become complete; skipped phases stay explicit. */
export function phaseStatus(state: ReviewProgressState, index: number): string {
  const current = currentStepIndex(state.node);
  const seen = new Set((state.observed ?? [state.node]).map(currentStepIndex));
  if (state.completedNodes) {
    const done = state.completedNodes.some((node) => currentStepIndex(node) === index);
    if (state.outcome === "completed") return done ? "done" : "not-run";
    if (index === current && (state.outcome === "failed" || state.outcome === "cancelled")) return state.outcome;
    if (state.activeNode && currentStepIndex(state.activeNode) === index) return "current";
    if (done) return "done";
    return state.node === "waiting" && index === 0 ? "waiting" : "pending";
  }
  if (state.outcome === "completed") return seen.has(index) ? "done" : "not-run";
  if (index === current) return state.outcome === "failed" || state.outcome === "cancelled" ? state.outcome : state.node === "waiting" ? "waiting" : "current";
  return index < current && seen.has(index) ? "done" : "pending";
}

export function finishReviewProgress(state: ReviewProgressState, outcome: "completed" | "failed" | "cancelled", elapsedMs: number, performance?: unknown): ReviewProgressState {
  const data = performance && typeof performance === "object" ? performance as Record<string, unknown> : undefined;
  const effective = data?.effective_settings && typeof data.effective_settings === "object" ? data.effective_settings as Record<string, unknown> : undefined;
  state = { ...state, resolvedScope: resolvedScopeFromServer(effective?.resolved_scope ?? data?.resolved_scope) ?? state.resolvedScope };
  if (outcome !== "completed") return { ...state, outcome, elapsedMs };
  return { ...state, node: "report", activeNode: null, completedNodes: state.completedNodes ? [...new Set([...state.completedNodes, "report" as const])] : undefined, observed: [...new Set([...(state.observed ?? []), "report" as const])], outcome, elapsedMs };
}

/** Read only actual applied filters, never infer routing from the question or selected mode. */
export function resolvedScopeFromServer(value: unknown): ReviewResolvedScope | undefined {
  if (!value || typeof value !== "object") return undefined;
  const scope = value as Record<string, unknown>;
  if (!scope.filters || typeof scope.filters !== "object") return undefined;
  const filters = scope.filters as Record<string, unknown>;
  if (!Array.isArray(filters.registries) || !filters.registries.every((item) => typeof item === "string") || !Array.isArray(filters.issuers) || !filters.issuers.every((item) => typeof item === "string") || !Array.isArray(filters.fiscal_years) || !filters.fiscal_years.every((item) => typeof item === "number" && Number.isFinite(item))) return undefined;
  return { source: typeof scope.source === "string" ? scope.source : undefined, filters: { registries: filters.registries, issuers: filters.issuers, fiscal_years: filters.fiscal_years } };
}

/** The requested mode and confirmed applied routing remain distinct throughout execution. */
export function RoutingSummary({ state }: { state: ReviewProgressState }) {
  const { t } = useI18n();
  const resolved = state.resolvedScope;
  const reason = resolved?.source === "explicit" ? "Explicit scope or filters" : resolved?.source === "alias" ? "Company alias matched in the question" : resolved?.source === "query_language" ? "Question language" : "Routing reason not collected";
  const waiting = state.outcome === "running" && state.selectedScope !== undefined;
  return <div className="review-routing">
    {state.selectedScope && <p>{t("Selected corpus")}: <strong>{t(state.selectedScope === "auto" ? "Auto" : state.selectedScope.toUpperCase())}</strong></p>}
    {resolved ? <>
      <p><strong>{t("Server-confirmed scope")}</strong>: {t("Source")}: {resolved.filters.registries.length ? resolved.filters.registries.map((registry) => registry.toUpperCase()).join(", ") : t("No source restriction")} · {t("Company")}: {resolved.filters.issuers.join(", ") || t("No company restriction")} · {t("Fiscal year")}: {resolved.filters.fiscal_years.join(", ") || t("No year restriction")}</p>
      <p>{t("Routing reason")}: {t(reason)}</p>
    </> : <p>{t(waiting ? "Waiting for server-confirmed routing" : "Routing details not collected")}</p>}
  </div>;
}

export function progressCountsLabel({ evidence, relevant, steps }: ReviewProgressState): string {
  return `${evidence} candidates · ${relevant} relevant · ${steps} model steps`;
}

export function WaitingGlyph() {
  return <span className="waiting-glyph" aria-hidden="true">◐</span>;
}

export function ReviewProgressSteps({ state }: { state: ReviewProgressState }) {
  const { t, locale } = useI18n();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (state.outcome !== "running" || !state.startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.outcome, state.startedAt]);
  const current = currentStepIndex(state.node);
  const chat = state.node === "chat" || ((state.observed ?? []).includes("chat") && !(state.observed ?? []).some((node) => node === "retrieve" || node === "candidates"));
  const status = state.outcome ?? "running";
  const announcement = status === "completed" ? "Execution complete" : status === "failed" ? "Stopped after the last reported step" : status === "cancelled" ? "Request cancelled" : state.node === "waiting" ? "Waiting for the server" : chat ? "Replying…" : REVIEW_STEPS[current]?.label ?? "Waiting for the server";
  return <div className={`review-progress ${status}`} role="status" aria-live="polite">
    <div className="review-progress-heading">{status === "running" && !state.activeNode && <WaitingGlyph />}<strong>{t(announcement)}</strong>{state.revalidating && <span><RotateCcw size={12} />{t("Re-checking selected evidence")}</span>}{Boolean(state.retries) && <span>{t("Repeated phases: {p0}", { p0: state.retries! })}</span>}</div>
    {!chat && <RoutingSummary state={state} />}
    {!chat && <ol className="review-progress-steps" aria-label={t("Evidence review progress")}>
      {REVIEW_STEPS.map((step, index) => {
        const phase = phaseStatus(state, index);
        return <li key={step.node} className={phase} aria-current={phase === "current" || phase === "waiting" ? "step" : undefined}>
          <span className="review-phase-icon" aria-hidden="true">{phase === "done" ? <Check size={14} /> : phase === "current" ? <LoaderCircle size={14} /> : phase === "failed" || phase === "cancelled" ? <TriangleAlert size={14} /> : <Circle size={12} />}</span>
          <span><strong>{index + 1}. {t(step.label)}</strong><small>{t(phase === "not-run" ? "Not performed in this request" : step.detail)}</small></span>
        </li>;
      })}
    </ol>}
    <p className="review-progress-counts">{t("{p0} candidates · {p1} relevant · {p2} model steps", { p0: state.evidence, p1: state.relevant, p2: state.steps })}{state.elapsedMs !== undefined && <span> · {t("Request time")}: {(state.elapsedMs / 1000).toLocaleString(locale === "ko" ? "ko-KR" : "en-US", { maximumFractionDigits: 1 })}s</span>}</p>
    {status === "running" && state.startedAt && <p className="review-progress-counts" aria-live="off">{t("Elapsed")}: {Math.max(0, Math.floor((now - state.startedAt) / 1000))}s · {state.lastEventAt ? t("Last update: {seconds}s ago", { seconds: Math.max(0, Math.floor((now - state.lastEventAt) / 1000)) }) : t("Waiting for the first server event")}</p>}
  </div>;
}
