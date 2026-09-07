"use client";

import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";
import type { ReviewExecution } from "@/lib/types";
import "./review-stage-details.css";

export type DisclosureStage = "path" | "gate" | "retrieve" | "grade" | "check" | "report";

/** Accept only object records from optional historical execution fields. */
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** Retain recorded rows in collection order, including repeated stage passes. */
function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item) => item !== null && typeof item === "object" && !Array.isArray(item)).map(record) : [];
}

/** Render recorded values while distinguishing missing measurements from zero and empty sets. */
export function ReviewStageDetails({ stage, state, performance, finalLabel, onOpenDetails, onShowEvidence }: {
  stage: DisclosureStage;
  state: ReviewExecution;
  performance?: Record<string, unknown>;
  finalLabel?: string;
  onOpenDetails?: () => void;
  onShowEvidence?: () => void;
}) {
  const { t } = useI18n();
  const missing = t("Not recorded for this run");
  const nodes = stage === "path" ? ["gate"] : stage === "gate" ? ["gate", "route"] : stage === "report" && state.pathDecision?.intent === "casual_chat" ? ["chat", "report"] : [stage];
  const results = records(performance?.stage_results).filter((item) => nodes.includes(String(item.node)));
  const calls = records(performance?.model_calls).filter((item) => nodes.includes(String(item.node)));
  const timings = records(performance?.stages ?? state.stageTimings).filter((item) => nodes.includes(String(item.node)) && item.phase !== "start");
  const path = record(performance?.path_decision ?? state.pathDecision);
  const settings = record(performance?.effective_settings);
  const scope = record(path.resolved_scope ?? performance?.resolved_scope ?? state.resolvedScope);
  const filters = record(scope.filters);
  const requested = record(settings.requested_profile ?? performance?.requested_profile);
  const retrieval = record(settings.retrieval);
  const resolved = record(settings.resolved_profile ?? performance?.resolved_profile);
  /** Keep raw server decisions inspectable; translate only stable presentation labels. */
  const value = (item: unknown): ReactNode => item === undefined || item === null ? missing : typeof item === "object" ? <pre>{JSON.stringify(item, null, 2)}</pre> : String(item);
  /** Pair each measurement with its own missing-field marker. */
  const field = (label: string, item: unknown) => <div key={label}><dt>{t(label)}</dt><dd>{value(item)}</dd></div>;
  /** Show a numeric count only when the server actually recorded the set. */
  const ids = (label: string, item: unknown) => <div key={label}><dt>{t(label)}</dt><dd>{Array.isArray(item) ? `${item.length} · ${item.join(", ") || "[]"}` : missing}</dd></div>;
  const skip = state.pathDecision?.intent === "casual_chat" && ["retrieve", "grade", "check"].includes(stage) ? "Skipped: conversation reply without retrieval" : stage === "check" && state.skippedNodes?.check ? "Skipped: relevance threshold not met" : null;

  const stageFields = stage === "path" || stage === "gate"
    ? [path.selected_scope ?? state.selectedScope, filters.registries, filters.issuers, filters.fiscal_years, path.rationale ?? scope.source, path.matched_rule, path.history_turns, path.intent, path.source, path.routing_queries ?? performance?.routing_queries, path.retrieval_query, path.stopping_reason]
    : stage === "retrieve" ? [retrieval.preset ?? requested.retrieval_preset ?? settings.retrieval_preset, retrieval.k ?? resolved.k, ...results.map((result) => result.candidates)]
    : stage === "grade" ? results.flatMap((result) => [result.kept_chunk_ids, result.rejected_chunk_ids])
    : stage === "check" ? results.flatMap((result) => [result.decision, result.reasons])
    : [finalLabel, performance?.total_elapsed_ms ?? state.elapsedMs, ...results.flatMap((result) => [record(result.decision).label, result.reasons])];
  const hasRecordedFields = Boolean(skip) || timings.length > 0 || Array.isArray(performance?.model_calls)
    || [...stageFields, ...results.map((result) => result.failure)].some((item) => item !== undefined && item !== null);
  if (!hasRecordedFields) return <div className="review-stage-details"><p className="review-stage-empty">{t("This stage was not recorded for this run.")}</p></div>;

  return <div className="review-stage-details">
    {skip && <p className="review-stage-skip">{t(skip)}</p>}
    {(stage === "path" || stage === "gate") && <dl>
      {field("Selected corpus", path.selected_scope ?? state.selectedScope)}
      {field("Source", filters.registries)}{field("Company", filters.issuers)}{field("Fiscal year", filters.fiscal_years)}
      {field("Routing reason", path.rationale ?? scope.source)}
      {field("Deterministic rule", path.matched_rule)}{field("History turns considered", path.history_turns)}
      {field("Path decision", path.intent)}{field("Decision source", path.source)}
      {field("Routing queries", path.routing_queries ?? performance?.routing_queries)}
      {field("Retrieval query", path.retrieval_query)}{field("Stopping reason", path.stopping_reason)}
    </dl>}
    {stage === "retrieve" && <dl>
      {field("Search preset", retrieval.preset ?? requested.retrieval_preset ?? settings.retrieval_preset)}
      {field("Retrieval k", retrieval.k ?? resolved.k)}
    </dl>}
    {!["path", "gate"].includes(stage) && (results.length ? results : [{}]).map((result, index) => <section key={index}>
      {results.length > 1 && <h4>{t("Recorded pass")} {index + 1}</h4>}
      {stage === "retrieve" && <>
        <dl>{field("Candidate count", Array.isArray(result.candidates) ? result.candidates.length : undefined)}</dl>
        {!Array.isArray(result.candidates) && <p>{t("Ranked candidates")}: {missing}</p>}
        {Array.isArray(result.candidates) && result.candidates.length > 0 && <table>
          <caption>{t("Ranked candidates")}</caption>
          <thead><tr><th>{t("Rank")}</th><th>{t("Citation")}</th><th>{t("Score")}</th></tr></thead>
          <tbody>{records(result.candidates).map((candidate, candidateIndex) => <tr key={candidateIndex}><td>{value(candidate.rank)}</td><td>{value(candidate.citation)}<br /><code>{value(candidate.doc_id)} / {value(candidate.chunk_id)}</code></td><td>{value(candidate.score)}</td></tr>)}</tbody>
        </table>}
      </>}
      {stage === "grade" && <dl>{ids("Kept candidate IDs", result.kept_chunk_ids)}{ids("Rejected candidate IDs", result.rejected_chunk_ids)}</dl>}
      {stage === "check" && <dl>{field("Verification decision", result.decision)}{field("Reasons", result.reasons)}</dl>}
      {stage === "report" && <dl>{field("Final label", finalLabel ? t(finalLabel) : record(result.decision).label)}{field("Reasons", result.reasons)}{field("Request time", performance?.total_elapsed_ms ?? state.elapsedMs)}</dl>}
      <dl>{field("Failure", result.failure)}</dl>
    </section>)}
    <dl>{field("Stage timings", timings.length ? timings.map((item) => ({ node: item.node, status: item.status, elapsed_ms: item.elapsed_ms ?? missing })) : undefined)}</dl>
    <h4>{t("Model calls / attempts")}</h4>
    {calls.length ? calls.map((call, index) => <dl key={index}>
      {field("Model", call.model)}{field("Attempts", call.attempts)}{field("Elapsed (ms)", call.elapsed_ms)}
      {field("Input tokens", call.input_tokens)}{field("Output tokens", call.output_tokens)}{field("Error", call.error)}
    </dl>) : <p>{Array.isArray(performance?.model_calls) ? "0" : missing}</p>}
    {stage === "report" && <div className="review-stage-actions">
      <button type="button" onClick={onShowEvidence} disabled={!onShowEvidence}>{t("Show evidence")}</button>
      <button type="button" onClick={onOpenDetails} disabled={!onOpenDetails}>{t("Open run details")}</button>
    </div>}
  </div>;
}
