"use client";

import { ArrowUpRight, Check, Circle, FileSearch, LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useStageCompanyLabels, type CompanyCatalogMode } from "@/lib/use-stage-company-labels";
import { useI18n } from "@/lib/i18n";
import type { ReviewProgress } from "@/lib/api";
import type { CorpusScope, ReviewEventNode, ReviewExecution, ReviewResolvedScope, ReviewPathDecision } from "@/lib/types";

import { ReviewStageDetails, type DisclosureStage } from "@/components/review-stage-details";

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
  if (event.display_stage === "path") {
    const state = previous ?? initialReviewProgress();
    return { ...state, pathStatus: event.phase === "start" ? "current" : event.status === "failed" ? "failed" : "done", pathDecision: event.path_decision ?? state.pathDecision, lastEventAt: Date.now(), outcome: event.status === "failed" ? "failed" : "running" };
  }
  const next = advanceProgress(event.node, event.evidence_count ?? previous?.evidence ?? 0, event.relevant_count ?? previous?.relevant ?? 0, event.step_count ?? previous?.steps ?? 0, previous);
  const phase = currentStepIndex(event.node);
  const repeated = previous && phase < currentStepIndex(previous.node);
  const completed = repeated ? (previous.completedNodes ?? []).filter((node) => currentStepIndex(node) < phase) : previous?.completedNodes ?? [];
  return { ...next, lastEventAt: Date.now(), activeNode: event.phase === "start" ? event.node : null,
    pathDecision: event.path_decision ?? previous?.pathDecision,
    resolvedScope: resolvedScopeFromServer(event.path_decision?.resolved_scope ?? event.resolved_scope) ?? previous?.resolvedScope,
    completedNodes: event.phase === "start" || event.status === "failed" ? completed : [...new Set([...completed, event.node])],
    outcome: event.status === "failed" ? "failed" : "running",
    stageTimings: event.phase === "end" && typeof event.elapsed_ms === "number" ? [...(previous?.stageTimings ?? []), { node: event.node, elapsed_ms: event.elapsed_ms, status: event.status ?? "completed" }] : previous?.stageTimings };
}

export function initialReviewProgress(revalidating = false, evidence = 0, selectedScope?: CorpusScope): ReviewProgressState {
  return { node: "waiting", pathStatus: "waiting", selectedScope, evidence, relevant: 0, steps: 0, observed: [], outcome: "running", revalidating, retries: 0, startedAt: Date.now(), activeNode: null, completedNodes: [] };
}

export function candidateProgress(previous: ReviewProgressState, evidence: number, resolvedScope?: unknown, pathDecision?: ReviewPathDecision | null): ReviewProgressState {
  const next = advanceProgress("candidates", evidence, 0, previous.steps, previous);
  return { ...next, pathDecision: pathDecision ?? previous.pathDecision, resolvedScope: resolvedScopeFromServer(resolvedScope) ?? previous.resolvedScope, lastEventAt: Date.now(), activeNode: previous.activeNode === "retrieve" ? "retrieve" : null, completedNodes: [...(previous.completedNodes ?? []).filter((node) => currentStepIndex(node) < 1), "candidates"] };
}

/** Only actual observed phases become complete; skipped phases stay explicit. */
export function phaseStatus(state: ReviewProgressState, index: number): string {
  const current = currentStepIndex(state.node);
  if (state.pathStatus === "failed" || state.pathStatus === "cancelled") return "not-run";
  if (state.skippedNodes?.[REVIEW_STEPS[index]?.node]) return "skipped";
  if ((state.pathDecision?.intent === "casual_chat" || (state.observed ?? []).includes("chat")) && ["retrieve", "grade", "check"].includes(REVIEW_STEPS[index]?.node)) return "skipped";
  const stopped = state.outcome === "failed" || state.outcome === "cancelled";
  const seen = new Set((state.observed ?? [state.node]).map(currentStepIndex));
  if (state.completedNodes) {
    const done = state.completedNodes.some((node) => currentStepIndex(node) === index);
    if (state.outcome === "completed") return done ? "done" : "not-run";
    if (index === current && (state.outcome === "failed" || state.outcome === "cancelled")) return state.outcome;
    if (state.activeNode && currentStepIndex(state.activeNode) === index) return "current";
    if (done) return "done";
    if (stopped) return "not-run";
    return state.node === "waiting" && index === 0 ? "waiting" : "pending";
  }
  if (state.outcome === "completed") return seen.has(index) ? "done" : "not-run";
  if (index === current) return state.outcome === "failed" || state.outcome === "cancelled" ? state.outcome : state.node === "waiting" ? "waiting" : "current";
  return index < current && seen.has(index) ? "done" : stopped ? "not-run" : "pending";
}

/** Apply terminal evidence without inferring execution from the verdict alone. */
export function finishReviewProgress(state: ReviewProgressState, outcome: "completed" | "failed" | "cancelled", elapsedMs: number, performance?: unknown, report?: unknown): ReviewProgressState {
  const data = objectRecord(performance);
  const effective = objectRecord(data?.effective_settings);
  const metadata = objectRecord(objectRecord(report)?.llm_metadata);
  const pathDecision = (data?.path_decision ?? metadata?.path_decision) as ReviewPathDecision | undefined;
  state = { ...state, pathDecision: pathDecision ?? state.pathDecision, steps: Array.isArray(data?.model_calls) ? data.model_calls.length : state.steps };
  state = { ...state, resolvedScope: resolvedScopeFromServer(state.pathDecision?.resolved_scope ?? effective?.resolved_scope ?? data?.resolved_scope) ?? state.resolvedScope, skippedNodes: undefined };
  const stages = Array.isArray(data?.stages) ? data.stages.map(objectRecord).filter((value) => value && ["gate", "route", "retrieve", "chat", "grade", "check", "report"].includes(String(value.node)) && value.phase !== "start" && ["completed", "failed"].includes(String(value.status))) : [];
  if (stages.length) {
    let recorded: ReviewProgressState = { ...state, node: "waiting", observed: [], completedNodes: [], activeNode: null, retries: 0 };
    for (const stage of stages) recorded = reviewProgressFromEvent({ display_stage: stage!.display_stage === "path" ? "path" : undefined, node: stage!.node as ReviewProgress["node"], phase: "end", status: stage!.status as "completed" | "failed", evidence_count: recorded.evidence, relevant_count: recorded.relevant, step_count: recorded.steps }, recorded);
    state = { ...state, pathStatus: recorded.pathStatus, node: recorded.node, observed: recorded.observed, completedNodes: recorded.completedNodes, activeNode: null, retries: recorded.retries };
  }
  if (outcome !== "completed") return { ...state, pathStatus: !state.pathDecision && state.node === "waiting" ? outcome : state.pathStatus, outcome, elapsedMs };
  const result = objectRecord(report);
  const results = Array.isArray(data?.stage_results) ? data.stage_results.map(objectRecord).filter((value) => value !== undefined) : [];
  const reported = results.filter((value) => value?.node === "report").at(-1);
  const label = result?.label ?? objectRecord(reported?.decision)?.label;
  const reasons = [result?.reasons, ...results.filter((value) => value?.node === "grade" || value?.node === "report").map((value) => value?.reasons)].flatMap((value) => Array.isArray(value) ? value : []);
  const threshold = reasons.map(objectRecord).find((reason) => reason?.code === "relevance_below_threshold");
  const checkObserved = (state.observed ?? []).includes("check") || (state.completedNodes ?? []).includes("check");
  if (label === "NOT_IN_DOCS" && threshold && !checkObserved) {
    state = { ...state, skippedNodes: { check: "relevance_below_threshold" }, evidence: typeof threshold.candidate_count === "number" ? threshold.candidate_count : state.evidence, relevant: typeof threshold.relevant_count === "number" ? threshold.relevant_count : state.relevant };
  }
  return { ...state, node: "report", activeNode: null, completedNodes: state.completedNodes ? [...new Set([...state.completedNodes, "report" as const])] : undefined, observed: [...new Set([...(state.observed ?? []), "report" as const])], outcome, elapsedMs };
}

/** Accept only JSON objects at the optional historical execution boundary. */
function objectRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
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

/** Keep the server scope outcome visible alongside the answer verdict. */
export function PathDecisionBadge({ decision }: { decision: ReviewPathDecision }) {
  const { t } = useI18n();
  const scope = decision.resolved_scope;
  const outcome = decision.scope_outcome === "conflict" ? "Scope conflict" : decision.scope_outcome === "empty" ? "Empty scope" : decision.scope_outcome === "not_applicable" ? "No retrieval" : "Scope resolved";
  return <p className="review-scope-outcome"><strong>{t(outcome)}</strong> · {t(decision.selected_scope === "auto" ? "Auto" : "Pinned")} {decision.selected_scope !== "auto" && decision.selected_scope.toUpperCase()}{scope && <> → {scope.filters.registries.join(" / ").toUpperCase()} / {scope.filters.issuers.join(", ") || t("No company restriction")}</>}</p>;
}

/** The requested mode and confirmed applied routing remain distinct throughout execution. */
export function RoutingSummary({ state, onSwitchScope }: { state: ReviewProgressState; onSwitchScope?: () => void }) {
  const { t } = useI18n();
  const decision = state.pathDecision;
  const resolved = decision?.resolved_scope ?? state.resolvedScope;
  const selected = decision?.selected_scope ?? state.selectedScope;
  const chat = decision?.intent === "casual_chat" || (state.observed ?? []).includes("chat");
  const reason = resolved?.source === "explicit" ? "Explicit scope or filters" : resolved?.source === "alias" ? "Company alias matched in the question" : resolved?.source === "query_language" ? "Question language" : "Routing reason not collected";
  const waiting = state.outcome === "running" && state.selectedScope !== undefined;
  return <div className="review-routing">
    {decision && <>
      <p className="review-routing-meta"><span><strong>{t(decision.intent === "casual_chat" ? "Conversation reply" : "Document review")}</strong> · {t(decision.source === "classifier" ? "Classifier" : "Deterministic rule")}: <code>{decision.matched_rule}</code></span><span>{t("History turns considered")}: {decision.history_turns}</span></p>
      <p className="review-routing-rationale">{t(decision.rationale)}</p>
    </>}
    {selected && <p className="review-routing-selected">{t("Selected corpus")}: <strong>{t(selected === "auto" ? "Auto" : selected.toUpperCase())}</strong></p>}
    {decision && <p className="review-scope-outcome"><strong>{t("Scope outcome")}: {t(decision.scope_outcome === "conflict" ? "Scope conflict" : decision.scope_outcome === "empty" ? "Empty scope" : decision.scope_outcome === "not_applicable" ? "No retrieval" : "Scope resolved")}</strong>{resolved && <> · {t(selected === "auto" ? "Auto" : "Pinned")} → {resolved.filters.registries.join(" / ").toUpperCase()} / {resolved.filters.issuers.join(", ") || t("No company restriction")}</>}</p>}
    {decision?.stopping_reason && <p>{t("Stopping reason")}: {t(decision.stopping_reason)}</p>}
    {decision?.intent === "document_review" && <p className="review-routing-query">{t("Retrieval query")}: {decision.retrieval_query}</p>}
    {decision?.suggested_scope === "auto" && <><p>{t("Switch the document scope to Auto above the composer and send the question again.")}</p>{onSwitchScope && <button type="button" className="button ghost" onClick={onSwitchScope}>{t("Switch to Auto and restore question")}</button>}</>}
    {decision?.intent === "document_review" && Object.entries(decision.routing_queries).length > 0 && <details><summary>{t("Routing queries")}</summary>{Object.entries(decision.routing_queries).map(([registry, query]) => <p key={registry}><strong>{registry.toUpperCase()}</strong>: {query}</p>)}</details>}
    {resolved ? <>
      <p className="review-routing-confirmed"><strong>{t("Server-confirmed scope")}</strong>: {t("Source")}: {resolved.filters.registries.length ? resolved.filters.registries.map((registry) => registry.toUpperCase()).join(", ") : t("No source restriction")} · {t("Company")}: {resolved.filters.issuers.join(", ") || t("No company restriction")} · {t("Fiscal year")}: {resolved.filters.fiscal_years.join(", ") || t("No year restriction")}</p>
      <p className="review-routing-reason">{t("Routing reason")}: {t(reason)}</p>
    </> : chat ? <p>{t("No retrieval")}</p> : <p>{t(waiting ? "Waiting for server-confirmed routing" : "Routing details not collected")}</p>}
  </div>;
}

export function progressCountsLabel({ evidence, relevant, steps }: ReviewProgressState): string {
  return `${evidence} candidates · ${relevant} relevant · ${steps} model steps`;
}

export function WaitingGlyph() {
  return <span className="waiting-glyph" aria-hidden="true">◐</span>;
}

export function ReviewProgressSteps({ state, onSwitchScope, performance, finalLabel, catalogMode, onOpenDetails, onShowEvidence, showDetailsAction = true }: { showDetailsAction?: boolean; catalogMode?: CompanyCatalogMode; state: ReviewProgressState; onSwitchScope?: () => void; performance?: Record<string, unknown>; finalLabel?: string; onOpenDetails?: (stage?: DisclosureStage) => void; onShowEvidence?: () => void }) {
  const { t, locale } = useI18n();
  const [now, setNow] = useState(Date.now());
  const [expanded, setExpanded] = useState<DisclosureStage | null>(null);
  const disclosureId = useId();
  const pathPhase = state.pathStatus === "failed" || state.pathStatus === "cancelled" ? state.pathStatus : state.pathDecision ? "done" : state.pathStatus ?? ((state.outcome ?? "running") === "running" ? "waiting" : "not-run");
  const phases = Object.fromEntries(REVIEW_STEPS.map((step, index) => [step.node, phaseStatus(state, index)]));
  /** Waiting and unobserved phases cannot expose a stage panel. */
  const selectable = (phase: string) => ["done", "current", "failed", "cancelled", "skipped"].includes(phase);
  const openStage = expanded && selectable(expanded === "path" ? pathPhase : phases[expanded]) ? expanded : null;
  useEffect(() => { if (expanded && !openStage) setExpanded(null); }, [expanded, openStage]);
  const detailScope = resolvedScopeFromServer(objectRecord(performance?.path_decision)?.resolved_scope ?? performance?.resolved_scope) ?? state.pathDecision?.resolved_scope ?? state.resolvedScope;
  const registryKey = [...new Set(detailScope?.filters.registries ?? [])].map((registry) => registry.toLowerCase()).sort().join(",");
  const needsCompanyNames = (openStage === "path" || openStage === "gate") && Boolean(detailScope?.filters.issuers.length);
  const names = useStageCompanyLabels(needsCompanyNames, catalogMode, registryKey);
  /** Keep phase colors and layout while marking only actionable and expanded stages. */
  const stageClass = (stage: DisclosureStage, phase: string) => `${phase}${selectable(phase) ? " review-stage-selectable" : ""}${openStage === stage ? " review-stage-selected" : ""}`;
  /** Native buttons preserve Enter/Space; unreached stages have no activation surface. */
  const toggle = (stage: DisclosureStage, label: string, phase: string) => selectable(phase) ? <button id={`${disclosureId}-${stage}`} type="button" className="review-stage-toggle" aria-label={t(label)} aria-expanded={openStage === stage} aria-current={openStage === stage ? "true" : undefined} aria-controls={`${disclosureId}-panel`} onClick={() => setExpanded((current) => current === stage ? null : stage)} /> : null;
  useEffect(() => {
    if (state.outcome !== "running" || !state.startedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.outcome, state.startedAt]);
  const current = currentStepIndex(state.node);
  const chat = state.pathDecision?.intent === "casual_chat" || state.node === "chat" || ((state.observed ?? []).includes("chat") && !(state.observed ?? []).some((node) => node === "retrieve" || node === "candidates"));
  const status = state.outcome ?? "running";
  const announcement = status === "completed" ? "Execution complete" : status === "failed" ? "Stopped after the last reported step" : status === "cancelled" ? "Request cancelled" : state.node === "waiting" ? "Waiting for the server" : chat ? "Replying…" : REVIEW_STEPS[current]?.label ?? "Waiting for the server";
  return <div className={`review-progress ${status}`} role="status" aria-live="polite">
    <div className="review-progress-heading">{status === "running" && !state.activeNode && <WaitingGlyph />}<strong>{t(announcement)}</strong>{state.revalidating && <span><RotateCcw size={12} />{t("Re-checking selected evidence")}</span>}{Boolean(state.retries) && <span>{t("Repeated phases: {p0}", { p0: state.retries! })}</span>}<div className="review-stage-actions">{onShowEvidence && <button className="button review-summary-action" type="button" onClick={onShowEvidence}><FileSearch size={14} aria-hidden="true" />{t("Show evidence")}</button>}{onOpenDetails && showDetailsAction && <button className="button review-summary-action" type="button" data-run-details-open onClick={() => onOpenDetails(openStage ?? undefined)}>{t("Open run details")}<ArrowUpRight size={14} aria-hidden="true" /></button>}</div></div>
    <ol className="review-progress-steps" aria-label={t("Evidence review progress")}>
      <li className={stageClass("path", pathPhase)}>
        {toggle("path", "Path decision", pathPhase)}
        <span className="review-phase-icon" aria-hidden="true">{pathPhase === "done" ? <Check size={14} /> : pathPhase === "current" ? <LoaderCircle size={14} /> : pathPhase === "failed" || pathPhase === "cancelled" ? <TriangleAlert size={14} /> : <Circle size={12} />}</span>
        <span><strong>0. {t("Path decision")}</strong><small>{state.pathDecision ? t(state.pathDecision.intent === "casual_chat" ? "Conversation reply" : "Document review") : t("Intent and filing scope")}</small></span>
      </li>
      {REVIEW_STEPS.map((step, index) => {
        const phase = phaseStatus(state, index);
        return <li key={step.node} className={stageClass(step.node, phase)} aria-current={phase === "current" || phase === "waiting" ? "step" : undefined}>
          {toggle(step.node, step.label, phase)}
          <span className="review-phase-icon" aria-hidden="true">{phase === "done" ? <Check size={14} /> : phase === "current" ? <LoaderCircle size={14} /> : phase === "failed" || phase === "cancelled" || phase === "skipped" ? <TriangleAlert size={14} /> : <Circle size={12} />}</span>
          <span><strong>{index + 1}. {t(step.label)}</strong><small className={phase === "skipped" ? "review-phase-reason" : undefined}>{t(phase === "skipped" ? chat ? "Skipped: conversation reply without retrieval" : "Skipped: relevance threshold not met" : phase === "not-run" ? "Not performed in this request" : step.detail)}</small></span>
        </li>;
      })}
    </ol>
    <section id={`${disclosureId}-panel`} hidden={!openStage} role="region" aria-labelledby={openStage ? `${disclosureId}-${openStage}` : undefined} className="review-stage-panel">{openStage && <ReviewStageDetails stage={openStage} companyLabels={names.labels} state={state} performance={performance} finalLabel={finalLabel} />}{needsCompanyNames && names.failed && <p className="review-unrecorded">{t("Company names are unavailable. Original company codes are shown.")}</p>}</section>
    <RoutingSummary state={state} onSwitchScope={onSwitchScope} />
    <p className="review-progress-counts">{t("{p0} candidates · {p1} relevant · {p2} model steps", { p0: state.evidence, p1: state.relevant, p2: state.steps })}{chat && <span> · {t("No retrieval")}</span>}{state.elapsedMs !== undefined && <span> · {t("Request time")}: {(state.elapsedMs / 1000).toLocaleString(locale === "ko" ? "ko-KR" : "en-US", { maximumFractionDigits: 1 })}s</span>}</p>
    {status === "running" && state.startedAt && <p className="review-progress-counts" aria-live="off">{t("Elapsed")}: {Math.max(0, Math.floor((now - state.startedAt) / 1000))}s · {state.lastEventAt ? t("Last update: {seconds}s ago", { seconds: Math.max(0, Math.floor((now - state.lastEventAt) / 1000)) }) : t("Waiting for the first server event")}</p>}
  </div>;
}
