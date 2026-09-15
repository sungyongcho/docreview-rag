"use client";

import { useI18n } from "@/lib/i18n";
import type { ReviewExecution } from "@/lib/types";
import { RecordedStageTimings, RecordedTable, RecordedValue, recordedFieldLabel, type CompanyLabels, type RecordedColumn, type ValueKind } from "./review-stage-value";
import "./review-stage-details.css";
import { ReviewPathChoice } from "./review-path-choice";

export type DisclosureStage = "path" | "gate" | "retrieve" | "grade" | "check" | "report";
interface Field { label: string; value: unknown; kind?: ValueKind; wide?: boolean; count?: boolean }
interface Section { fields: Field[]; candidates?: Record<string, unknown>[]; pass?: number }

/** Accept only object records from optional historical execution fields. */
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** Retain recorded rows in collection order, including repeated stage passes. */
function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item) => item !== null && typeof item === "object" && !Array.isArray(item)).map(record) : [];
}

/** Flatten a recorded decision once, preserving unknown fields and empty historical values. */
function verificationFields(value: unknown): Field[] {
  const entries = Object.entries(record(value));
  if (!entries.length) return [{ label: "Verification decision", value }];
  return entries.map(([key, item]) => ({
    label: key === "label" ? "Verification decision" : recordedFieldLabel(key),
    value: item,
    kind: key.endsWith("_id") || key.endsWith("_ids") ? "code" : "plain",
    wide: !["label", "citation_chunk_ids"].includes(key),
  }));
}

/** Map the visual strip to the actual nodes recorded by the server. */
export function disclosureNodes(stage: DisclosureStage, state: ReviewExecution): string[] {
  return stage === "path" ? ["gate"] : stage === "gate" ? ["gate", "route"] : stage === "report" && state.pathDecision?.intent === "casual_chat" ? ["chat", "report"] : [stage];
}

const DISCLOSURE_LABELS: Record<DisclosureStage, [number, string]> = {
  path: [0, "Path decision"], gate: [1, "Understand the question"], retrieve: [2, "Retrieve evidence"],
  grade: [3, "Select relevant evidence"], check: [4, "Verify answer and citations"], report: [5, "Prepare the result"],
};

const CALL_COLUMNS: RecordedColumn[] = [{ key: "order", label: "Order" }, { key: "node", label: "Stage", kind: "stage" }, { key: "model", label: "Model", kind: "code" }, { key: "attempts", label: "Attempts" }, { key: "elapsed_ms", label: "Elapsed", kind: "duration" }, { key: "input_tokens", label: "Input tokens" }, { key: "output_tokens", label: "Output tokens" }, { key: "error", label: "Error" }];
const CANDIDATE_COLUMNS: RecordedColumn[] = [{ key: "rank", label: "Rank" }, { key: "citation", label: "Citation", kind: "citation" }, { key: "doc_id", label: "Document ID", kind: "code" }, { key: "chunk_id", label: "Chunk ID", kind: "code" }, { key: "score", label: "Score", kind: "score" }];

/** Render compact recorded facts, preserving empty collections and consolidating absent fields. */
export function ReviewStageDetails({ stage, state, performance, finalLabel, companyLabels = {} }: {
  stage: DisclosureStage; state: ReviewExecution; performance?: Record<string, unknown>; finalLabel?: string;
  companyLabels?: CompanyLabels;
}) {
  const { t } = useI18n();
  const nodes = disclosureNodes(stage, state);
  const results = records(performance?.stage_results).filter((item) => nodes.includes(String(item.node)));
  const calls = Array.isArray(performance?.model_calls) ? records(performance.model_calls).map((item, index): Record<string, unknown> => ({ ...item, order: index + 1 })).filter((item) => nodes.includes(String(item.node))) : undefined;
  const timingSource = performance?.stages ?? state.stageTimings;
  const timings = Array.isArray(timingSource) ? records(timingSource).map((item, index): Record<string, unknown> => ({ ...item, order: index + 1 })).filter((item) => nodes.includes(String(item.node)) && item.phase !== "start") : undefined;
  const path = record(performance?.path_decision ?? state.pathDecision);
  const settings = record(performance?.effective_settings);
  const scope = record(path.resolved_scope ?? performance?.resolved_scope ?? state.resolvedScope);
  const filters = record(scope.filters);
  const registries = Array.isArray(filters.registries) ? filters.registries.map(String) : [];
  const requested = record(settings.requested_profile ?? performance?.requested_profile);
  const retrieval = record(settings.retrieval);
  const resolved = record(settings.resolved_profile ?? performance?.resolved_profile);
  const skip = state.pathDecision?.intent === "casual_chat" && ["retrieve", "grade", "check"].includes(stage) ? "Skipped: conversation reply without retrieval" : stage === "check" && state.skippedNodes?.check ? "Skipped: relevance threshold not met" : null;
  const sections: Section[] = [];
  if (stage === "path") sections.push({ fields: [
    { label: "Decision source", value: path.source },
    { label: "Deterministic rule", value: path.matched_rule, kind: "code" },
    { label: "History turns considered", value: path.history_turns },
    ...(path.stopping_stage === "path" ? [{ label: "Stopping reason", value: path.stopping_reason, wide: true }] : []),
  ] });
  if (stage === "gate") sections.push({ fields: [
    { label: "Selected corpus", value: path.selected_scope ?? state.selectedScope },
    { label: "Source", value: filters.registries, kind: "registry" }, { label: "Company", value: filters.issuers, kind: "issuer" }, { label: "Fiscal year", value: filters.fiscal_years, kind: "year" },
    { label: "Routing reason", value: path.rationale ?? scope.source, wide: true },
    { label: "Deterministic rule", value: path.matched_rule }, { label: "History turns considered", value: path.history_turns },
    { label: "Path decision", value: path.intent }, { label: "Decision source", value: path.source },
    { label: "Routing queries", value: path.routing_queries ?? performance?.routing_queries, wide: true },
    { label: "Retrieval query", value: path.retrieval_query, wide: true }, { label: "Stopping reason", value: path.stopping_reason },
    { label: "Stopping stage", value: path.stopping_stage },
    { label: "Requested companies", value: path.requested_issuers },
    { label: "Missing companies", value: path.missing_issuers },
  ] });
  if (stage === "retrieve") sections.push({ fields: [{ label: "Search preset", value: retrieval.preset ?? requested.retrieval_preset ?? settings.retrieval_preset }, { label: "Retrieval k", value: retrieval.k ?? resolved.k }] });
  if (!["path", "gate"].includes(stage)) for (const [index, result] of (results.length ? results : [{}]).entries()) {
    const fields: Field[] = [];
    if (stage === "retrieve") fields.push({ label: "Candidate count", value: Array.isArray(result.candidates) ? result.candidates.length : undefined });
    if (stage === "grade") fields.push({ label: "Kept candidate IDs", value: result.kept_chunk_ids, count: true, kind: "code" }, { label: "Rejected candidate IDs", value: result.rejected_chunk_ids, count: true, kind: "code" });
    if (stage === "check") fields.push(...verificationFields(result.decision), { label: "Reasons", value: result.reasons });
    if (stage === "report") fields.push({ label: "Final label", value: finalLabel ? t(finalLabel) : record(result.decision).label }, { label: "Reasons", value: result.reasons, wide: true }, { label: "Request time", value: performance?.total_elapsed_ms ?? state.elapsedMs, kind: "duration" });
    fields.push({ label: "Failure", value: result.failure, wide: true });
    sections.push({ fields, candidates: stage === "retrieve" && Array.isArray(result.candidates) ? records(result.candidates) : undefined, pass: results.length > 1 ? index + 1 : undefined });
  }
  const missing = new Set(sections.flatMap((section) => section.fields.filter((field) => field.value === undefined || field.value === null).map((field) => `${section.pass ? `${t("Recorded pass")} ${section.pass} · ` : ""}${t(field.label)}`)));
  if (!timings) missing.add(t("Stage timings"));
  if (!calls) missing.add(t("Model calls / attempts"));
  const hasRecordedFields = Boolean(skip) || (stage === "path" && Object.keys(path).length > 0) || calls !== undefined || timings !== undefined || sections.some((section) => section.fields.some((field) => field.value !== undefined && field.value !== null));
  if (!hasRecordedFields) return <div className="review-stage-details"><p className="review-stage-empty">{t("This stage was not recorded for this run.")}</p></div>;
  return <div className="review-stage-details" data-stage={stage}>
    <h4 className="review-stage-mapping">{DISCLOSURE_LABELS[stage][0]}. {t(DISCLOSURE_LABELS[stage][1])} · <code>{nodes.join(", ")}</code></h4>
    {stage === "path" && <ReviewPathChoice path={path} />}
    {skip && <p className="review-stage-skip">{t(skip)}</p>}
    {sections.map((section, index) => <section key={index}>
      {section.pass && <h4>{t("Recorded pass")} {section.pass}</h4>}
      <dl className="review-stage-fields">{section.fields.filter((field) => field.value !== undefined && field.value !== null).map((field) => <div key={field.label} className={field.wide ? "review-field-wide" : undefined}><dt>{t(field.label)}</dt><dd>{field.count && Array.isArray(field.value) && <span>{field.value.length} · </span>}<RecordedValue value={field.value} kind={field.kind} companyLabels={companyLabels} registries={registries} /></dd></div>)}</dl>
      {section.candidates && <RecordedTable label="Ranked candidates" rows={section.candidates} columns={CANDIDATE_COLUMNS} collapsed />}
    </section>)}
    {timings && <section><RecordedStageTimings rows={timings} /></section>}
    {calls && <section><RecordedTable label="Model calls / attempts" rows={calls} columns={CALL_COLUMNS} /></section>}
    {missing.size > 0 && <p className="review-unrecorded">{t("Not recorded for this run")}: {[...missing].join(" · ")}</p>}

  </div>;
}
