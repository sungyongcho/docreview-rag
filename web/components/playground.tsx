"use client";
import { notificationErrorDetail, notificationErrorMessage } from "@/lib/notification-registry";
import { useI18n } from "@/lib/i18n";


import { Play, Search } from "lucide-react";
import { useState } from "react";

import { ApiError, previewRetrieval, previewReview } from "@/lib/api";
import { failureMessage } from "@/lib/pipeline";
import type { EvidenceHit, RetrievalProfile } from "@/lib/types";
import { ProfileFields } from "@/components/profile-fields";
import { useNotifications } from "@/components/notifications";

export interface PlaygroundProps {
  live: boolean;
  profile: RetrievalProfile;
  onProfileChange: (profile: RetrievalProfile) => void;
  onOpenSnapshots: () => void;
}

interface RetrievalPreview {
  query: string;
  profile: RetrievalProfile;
  score_stage: string;
  component_rankings: Record<string, number[]>;
  results: EvidenceHit[];
}

interface ReviewSummary {
  label: string;
  answer: string | null;
  citations: Array<Record<string, unknown>>;
  failure: string | null;
}

const DEFAULT_QUESTION = "What drove NVIDIA data center revenue growth?";

function chunkIds(value: unknown): number[] {
  return Array.isArray(value) ? value.filter((id): id is number => typeof id === "number") : [];
}

/**
 * Flatten component rankings into one column per rank list. `vector` and `lexical`
 * always appear; the per-language lists behind `*_by_language` become
 * "vector · ko"-style columns when a language route produced ranks.
 */
function flattenRankings(rankings: Record<string, unknown>): Record<string, number[]> {
  const columns: Record<string, number[]> = {};
  for (const [key, value] of Object.entries(rankings)) {
    if (key.endsWith("_by_language") && typeof value === "object" && value !== null && !Array.isArray(value)) {
      const base = key.slice(0, -"_by_language".length);
      for (const [language, ids] of Object.entries(value as Record<string, unknown>)) {
        const ranks = chunkIds(ids);
        if (ranks.length) columns[`${base} · ${language}`] = ranks;
      }
      continue;
    }
    columns[key] = chunkIds(value);
  }
  return columns;
}

/** Read `/admin/retrieval/preview` defensively; missing collections become empty. */
function toRetrievalPreview(value: Record<string, unknown>): RetrievalPreview {
  const rankings = typeof value.component_rankings === "object" && value.component_rankings !== null
    ? value.component_rankings as Record<string, unknown>
    : {};
  return {
    query: String(value.query ?? ""),
    profile: value.profile as RetrievalProfile,
    score_stage: String(value.score_stage ?? "rrf"),
    component_rankings: flattenRankings(rankings),
    results: Array.isArray(value.results) ? value.results as EvidenceHit[] : [],
  };
}

/** Flatten `/admin/review/preview` into the report label, answer, citations, or failure. */
function toReviewSummary(payload: Record<string, unknown>): ReviewSummary {
  const root = (payload.run ?? payload) as Record<string, unknown>;
  const report = typeof root.report === "object" && root.report !== null ? root.report as Record<string, unknown> : null;
  const failure = typeof root.failure === "object" && root.failure !== null ? root.failure as Record<string, unknown> : null;
  if (report) {
    return {
      label: String(report.label ?? report.report_kind ?? "report"),
      answer: typeof report.answer === "string" ? report.answer : null,
      citations: Array.isArray(report.citations)
        ? report.citations.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
        : [],
      failure: null,
    };
  }
  return {
    label: String(root.status ?? "failed"),
    answer: null,
    citations: [],
    // The same sentence the review workspace shows, so one failure does not read two ways.
    failure: failure ? failureMessage(failure) : "Review completed without a report.",
  };
}

export function Playground({ live, profile, onProfileChange, onOpenSnapshots }: PlaygroundProps) {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [busy, setBusy] = useState<"retrieval" | "review" | null>(null);
  const [retrieval, setRetrieval] = useState<RetrievalPreview | null>(null);
  const [review, setReview] = useState<ReviewSummary | null>(null);
  const [shown, setShown] = useState<"retrieval" | "review" | null>(null);

  if (!live) {
    return <div className="empty-state"><p>{t("Playground runs on the local operator build.")}</p><button className="button" type="button" onClick={onOpenSnapshots}>{t("Open Snapshots")}</button></div>;
  }

  async function runRetrieval() {
    if (!question.trim() || busy) return;
    setBusy("retrieval");
    try {
      setRetrieval(toRetrievalPreview(await previewRetrieval(question.trim(), profile) as unknown as Record<string, unknown>));
      setShown("retrieval");
    } catch (reason) {
      notify(reason instanceof Error ? t(notificationErrorMessage(reason)) : t("Retrieval preview failed."), "error", "playground-retrieval", undefined, { event: "playground-retrieval-error", detail: notificationErrorDetail(reason), ...(reason instanceof ApiError && reason.code === "query_scope_empty" ? { actionLabel: "Check document preparation", target: { view: "build" as const, tab: "pipeline" as const, stage: 1 } } : {}) });
    } finally {
      setBusy(null);
    }
  }

  async function runReview() {
    if (!question.trim() || busy) return;
    setBusy("review");
    try {
      setReview(toReviewSummary(await previewReview(question.trim(), profile)));
      setShown("review");
    } catch (reason) {
      notify(reason instanceof Error ? t(notificationErrorMessage(reason)) : t("Review preview failed."), "error", "playground-review", undefined, { event: "playground-review-error", detail: notificationErrorDetail(reason), ...(reason instanceof ApiError && reason.code === "query_scope_empty" ? { actionLabel: "Check document preparation", target: { view: "build" as const, tab: "pipeline" as const, stage: 1 } } : {}) });
    } finally {
      setBusy(null);
    }
  }

  const rankingKeys = retrieval ? Object.keys(retrieval.component_rankings) : [];
  const rankingDepth = retrieval ? Math.max(0, ...rankingKeys.map((key) => retrieval.component_rankings[key].length)) : 0;

  return (
    <div className="panel-stack playground">
      <section className="surface form-stack">
        <div className="surface-heading"><div><h2>{t("Playground")}</h2><p className="helper">{t("One query through an explicit retrieval profile. Nothing is persisted.")}</p></div></div>
        <label>{t("Question")}<textarea aria-label={t("Playground question")} data-help="measure.playground.question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} /></label>
        <fieldset className="playground-core"><legend>{t("Core search settings")}</legend><ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.playground" fields="core" /></fieldset>
        <details><summary>{t("Advanced search settings")}</summary><ProfileFields profile={profile} onChange={onProfileChange} helpPrefix="measure.playground" fields="advanced" /></details>
        <div className="action-row">
          <button className="button primary" type="button" data-help="measure.playground.preview_retrieval" disabled={busy !== null || !question.trim()} onClick={() => void runRetrieval()}><Search size={15} /> {busy === "retrieval" ? t("Previewing…") : t("Preview retrieval")}</button>
          <button className="button" type="button" data-help="measure.playground.preview_review" disabled={busy !== null || !question.trim()} onClick={() => void runReview()}><Play size={15} /> {busy === "review" ? t("Reviewing…") : t("Preview review")}</button>
        </div>
        <p className="helper">{t("Preview review calls the answer model once and records provider usage.")}</p>
      </section>
      {busy && <p className="helper" role="status">{t(busy === "retrieval" ? "Previewing…" : "Reviewing…")}</p>}
      {shown !== null && <section className="surface playground-results" aria-live="polite">
        {shown === "retrieval" && retrieval && <>
          <div className="surface-heading"><div><h2>{t("Retrieval preview")}</h2><p className="helper">{t("Score stage ·")}{" "}{t(retrieval.score_stage)}</p></div></div>
          <h3>{t("Component rankings")}</h3>
          {rankingKeys.length ? <div className="table-wrap playground-rankings" data-help="measure.playground.rankings"><table><thead><tr><th>{t("Rank")}</th>{rankingKeys.map((key) => <th key={key}>{key.split(" · ").map((part, index) => index === 0 ? t(part) : part).join(" · ")}</th>)}</tr></thead><tbody>
            {Array.from({ length: rankingDepth }, (_item, index) => <tr key={index}><td>{index + 1}</td>{rankingKeys.map((key) => <td key={key}>{retrieval.component_rankings[key][index] ?? "—"}</td>)}</tr>)}
          </tbody></table></div> : <p className="helper">{t("No component rankings were returned.")}</p>}
          <h3>{t("Fused results ·")}{" "}{retrieval.results.length.toLocaleString(locale)}</h3>
          <div className="playground-evidence" data-help="measure.playground.results">
            {retrieval.results.map((hit) => <article className="evidence-hit" key={hit.chunk_id}><strong>{hit.citation}</strong><span>{t("chunk")}{" "}{hit.chunk_id} · {hit.doc_id}{" "}{t("· chars")}{" "}{hit.start_char}–{hit.end_char}</span><p>{hit.body}</p></article>)}
            {!retrieval.results.length && <p className="helper">{t("No chunk passed the retrieval profile.")}</p>}
          </div>
        </>}
        {shown === "review" && review && <div className="playground-report" data-help="measure.playground.review">
          <div className="surface-heading"><div><h2>{t("Review preview")}</h2><p className="helper">{t("Report label")}</p></div><span className={`mode-badge ${review.label === "SUPPORTED" ? "live" : ""}`}>{t(review.label)}</span></div>
          {review.failure ? <p className="notice error">{t(review.failure)}</p> : <>
            {review.answer && <p>{review.answer}</p>}
            {review.citations.length > 0 && <>
              <h3>{t("Citations ·")}{" "}{review.citations.length.toLocaleString(locale)}</h3>
              {review.citations.map((item, index) => <article className="evidence-hit" key={`${String(item.chunk_id ?? index)}`}><strong>{String(item.citation ?? item.doc_id ?? t("Citation {number}", { number: index + 1 }))}</strong><span>{item.chunk_id !== undefined ? t("chunk {p0} · ", { p0: String(item.chunk_id) }) : ""}{String(item.doc_id ?? "")}{item.start_char !== undefined ? t(" · chars {p0}–{p1}", { p0: String(item.start_char), p1: String(item.end_char ?? "") }) : ""}</span></article>)}
            </>}
          </>}
        </div>}
      </section>}
    </div>
  );
}
