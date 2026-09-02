"use client";

import { Play, Search } from "lucide-react";
import { useState } from "react";

import { previewRetrieval, previewReview } from "@/lib/api";
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
    failure: failure
      ? String(failure.message ?? failure.status ?? failure.code ?? "provider failure")
      : "Review completed without a report.",
  };
}

export function Playground({ live, profile, onProfileChange, onOpenSnapshots }: PlaygroundProps) {
  const { notify } = useNotifications();
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [busy, setBusy] = useState<"retrieval" | "review" | null>(null);
  const [retrieval, setRetrieval] = useState<RetrievalPreview | null>(null);
  const [review, setReview] = useState<ReviewSummary | null>(null);
  const [shown, setShown] = useState<"retrieval" | "review" | null>(null);

  if (!live) {
    return <div className="empty-state"><p>Playground runs on the local operator build.</p><button className="button" type="button" onClick={onOpenSnapshots}>Open Snapshots</button></div>;
  }

  async function runRetrieval() {
    if (!question.trim() || busy) return;
    setBusy("retrieval");
    try {
      setRetrieval(toRetrievalPreview(await previewRetrieval(question.trim(), profile) as unknown as Record<string, unknown>));
      setShown("retrieval");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Retrieval preview failed.", "error", "playground-retrieval");
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
      notify(reason instanceof Error ? reason.message : "Review preview failed.", "error", "playground-review");
    } finally {
      setBusy(null);
    }
  }

  const rankingKeys = retrieval ? Object.keys(retrieval.component_rankings) : [];
  const rankingDepth = retrieval ? Math.max(0, ...rankingKeys.map((key) => retrieval.component_rankings[key].length)) : 0;

  return (
    <div className="two-column playground">
      <section className="surface form-stack">
        <div className="surface-heading"><div><h2>Playground</h2><p className="helper">One query through an explicit retrieval profile. Nothing is persisted.</p></div></div>
        <label>Question<textarea aria-label="Playground question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} /></label>
        <details open><summary>Retrieval profile</summary><ProfileFields profile={profile} onChange={onProfileChange} /></details>
        <div className="action-row">
          <button className="button primary" type="button" aria-disabled={busy !== null || !question.trim()} onClick={() => void runRetrieval()}><Search size={15} /> {busy === "retrieval" ? "Previewing…" : "Preview retrieval"}</button>
          <button className="button" type="button" aria-disabled={busy !== null || !question.trim()} onClick={() => void runReview()}><Play size={15} /> {busy === "review" ? "Reviewing…" : "Preview review"}</button>
        </div>
        <p className="helper">Preview review calls the answer model once and records provider usage.</p>
      </section>
      <section className="surface playground-results">
        {shown === null && <p className="helper">Run a retrieval preview to see how each component ranks chunks before fusion.</p>}
        {shown === "retrieval" && retrieval && <>
          <div className="surface-heading"><div><h2>Retrieval preview</h2><p className="helper">Score stage · {retrieval.score_stage}</p></div></div>
          <h3>Component rankings</h3>
          {rankingKeys.length ? <div className="table-wrap playground-rankings"><table><thead><tr><th>Rank</th>{rankingKeys.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>
            {Array.from({ length: rankingDepth }, (_item, index) => <tr key={index}><td>{index + 1}</td>{rankingKeys.map((key) => <td key={key}>{retrieval.component_rankings[key][index] ?? "—"}</td>)}</tr>)}
          </tbody></table></div> : <p className="helper">No component rankings were returned.</p>}
          <h3>Fused results · {retrieval.results.length}</h3>
          <div className="playground-evidence">
            {retrieval.results.map((hit) => <article className="evidence-hit" key={hit.chunk_id}><strong>{hit.citation}</strong><span>chunk {hit.chunk_id} · {hit.doc_id} · chars {hit.start_char}–{hit.end_char}</span><p>{hit.body}</p></article>)}
            {!retrieval.results.length && <p className="helper">No chunk passed the retrieval profile.</p>}
          </div>
        </>}
        {shown === "review" && review && <div className="playground-report">
          <div className="surface-heading"><div><h2>Review preview</h2><p className="helper">Report label</p></div><span className={`mode-badge ${review.label === "SUPPORTED" ? "live" : ""}`}>{review.label}</span></div>
          {review.failure ? <p className="notice error">{review.failure}</p> : <>
            {review.answer && <p>{review.answer}</p>}
            {review.citations.length > 0 && <>
              <h3>Citations · {review.citations.length}</h3>
              {review.citations.map((item, index) => <article className="evidence-hit" key={`${String(item.chunk_id ?? index)}`}><strong>{String(item.citation ?? item.doc_id ?? `Citation ${index + 1}`)}</strong><span>{item.chunk_id !== undefined ? `chunk ${String(item.chunk_id)} · ` : ""}{String(item.doc_id ?? "")}{item.start_char !== undefined ? ` · chars ${String(item.start_char)}–${String(item.end_char ?? "")}` : ""}</span></article>)}
            </>}
          </>}
        </div>}
      </section>
    </div>
  );
}
