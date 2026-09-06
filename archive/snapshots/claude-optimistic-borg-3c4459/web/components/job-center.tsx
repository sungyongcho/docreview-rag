"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import type { OperatorJob, OperatorJobBoard } from "@/lib/types";

export const JOB_COPY: Record<string, { label: string; purpose: string }> = {
  acquire_edgar: { label: "Acquire SEC filings", purpose: "Download missing EDGAR filings into the corpus." },
  acquire_dart: { label: "Acquire DART filings", purpose: "Download missing Korean business reports." },
  ingest_manifest: { label: "Ingest manifest", purpose: "Parse filings and replace the active retrieval corpus." },
  backfill_embeddings: { label: "Backfill embeddings", purpose: "Persist missing vectors for semantic retrieval." },
  rebuild_bm25: { label: "Rebuild BM25", purpose: "Recompute lexical term and document statistics." },
  quick: { label: "Quick evaluation", purpose: "Measure one profile against the current live index." },
  matrix: { label: "Matrix evaluation", purpose: "Compare isolated chunking and retrieval arms." },
};

export function jobCopy(job: OperatorJob) {
  return JOB_COPY[job.kind] ?? {
    label: job.kind.replaceAll("_", " "),
    purpose: "Run one persisted operator task.",
  };
}

export function elapsedLabel(job: OperatorJob): string {
  if (!job.started_at) return "Not started";
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(job.started_at).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

export function JobProgress({ job }: { job: OperatorJob }) {
  const percent = job.total && job.total > 0
    ? Math.min(100, Math.round((job.current / job.total) * 100))
    : null;
  return <div className="job-progress"><div><span>{job.stage}</span><strong>{job.total === null ? job.current : `${job.current.toLocaleString()} / ${job.total.toLocaleString()}${percent === null ? "" : ` · ${percent}%`}`}</strong></div>{job.total !== null && <progress max={Math.max(job.total, 1)} value={Math.min(job.current, job.total)} />}{job.detail_total !== null && <><div><span>Current item</span><strong>{job.detail_current ?? 0} / {job.detail_total}</strong></div><progress max={Math.max(job.detail_total, 1)} value={Math.min(job.detail_current ?? 0, job.detail_total)} /></>}</div>;
}

export function JobActivityPanel({ board, loading, onOpenJobs }: { board: OperatorJobBoard; loading: boolean; onOpenJobs: () => void }) {
  const active = board.jobs.find((job) => job.status === "running") ?? null;
  const queued = board.jobs.filter((job) => job.status === "queued").toSorted((left, right) => (left.queue_position ?? 0) - (right.queue_position ?? 0));
  const latest = board.jobs.find((job) => ["succeeded", "failed", "interrupted", "cancelled"].includes(job.status)) ?? null;
  return <section className="surface job-activity"><div className="surface-heading"><div><h2>Job activity</h2><p className="helper">Persistent corpus and evaluation queue</p></div><button className="button" type="button" onClick={onOpenJobs}>View all jobs</button></div>{loading && !board.jobs.length ? <p className="helper">Loading job activity…</p> : active ? <article className="active-job"><div className="job-title"><div><strong>{jobCopy(active).label}</strong><p>{jobCopy(active).purpose}</p></div><span className={`job-status ${active.status}`}>{active.status}</span></div><JobProgress job={active} /><p className="helper">{active.message}</p><p className="helper">Started {active.started_at ? new Date(active.started_at).toLocaleTimeString() : "—"} · elapsed {elapsedLabel(active)}</p></article> : <p className="helper">No job is running.{latest ? ` Latest: ${jobCopy(latest).label} · ${latest.status}.` : ""}</p>}{queued.length > 0 && <div className="queued-jobs"><strong>Queued · {queued.length}</strong>{queued.slice(0, 3).map((job) => <span key={job.job_id}>#{job.queue_position} {jobCopy(job).label}</span>)}</div>}</section>;
}

export function JobCenter({ board, loading, onRetry, onCancel, onRefresh, onOpenResult }: { board: OperatorJobBoard; loading: boolean; onRetry: (jobId: string) => void; onCancel: (jobId: string) => void; onRefresh: () => void; onOpenResult: (resultId: number) => void }) {
  const [domain, setDomain] = useState<"all" | OperatorJob["domain"]>("all");
  const [group, setGroup] = useState<"all" | "active" | "queued" | "history">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const visible = board.jobs.filter((job) => {
    if (domain !== "all" && job.domain !== domain) return false;
    if (group === "active" && job.status !== "running") return false;
    if (group === "queued" && job.status !== "queued") return false;
    if (group === "history" && ["queued", "running"].includes(job.status)) return false;
    return true;
  });
  const selected = board.jobs.find((job) => job.job_id === selectedId) ?? visible[0] ?? null;
  const resultId = typeof selected?.result_refs.result_id === "number" ? selected.result_refs.result_id : null;
  return <div className="job-center"><section className="surface"><div className="surface-heading"><div><h2>Job Center</h2><p className="helper">{board.active_count} active · {board.queued_count} queued</p></div><button className="button" type="button" disabled={loading} onClick={onRefresh}><RefreshCw size={14} /> Refresh</button></div><div className="job-filters"><div>{(["all", "corpus", "evaluation"] as const).map((value) => <button key={value} type="button" aria-pressed={domain === value} onClick={() => setDomain(value)}>{value}</button>)}</div><div>{(["all", "active", "queued", "history"] as const).map((value) => <button key={value} type="button" aria-pressed={group === value} onClick={() => setGroup(value)}>{value}</button>)}</div></div><div className="job-list">{visible.map((job) => <button className="job-list-row" type="button" key={job.job_id} aria-pressed={selected?.job_id === job.job_id} onClick={() => setSelectedId(job.job_id)}><span className={`job-status ${job.status}`}>{job.status}</span><div><strong>{jobCopy(job).label}</strong><p>{job.queue_position ? `Queue #${job.queue_position} · ` : ""}{job.message}</p></div><span>{job.total === null ? job.stage : `${Math.min(100, Math.round(job.current / Math.max(job.total, 1) * 100))}%`}</span></button>)}</div>{!visible.length && <p className="helper">No jobs match this filter.</p>}</section><section className="surface job-detail"><h2>Job details</h2>{selected ? <><div className="job-title"><div><strong>{jobCopy(selected).label}</strong><p>{jobCopy(selected).purpose}</p></div><span className={`job-status ${selected.status}`}>{selected.status}</span></div><JobProgress job={selected} /><dl className="status-list"><div><dt>Domain</dt><dd>{selected.domain}</dd></div><div><dt>Created</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div><div><dt>Started</dt><dd>{selected.started_at ? new Date(selected.started_at).toLocaleString() : "—"}</dd></div><div><dt>Finished</dt><dd>{selected.finished_at ? new Date(selected.finished_at).toLocaleString() : "—"}</dd></div><div><dt>Elapsed</dt><dd>{elapsedLabel(selected)}</dd></div><div><dt>Error</dt><dd>{selected.error_code ?? "—"}</dd></div></dl><p>{selected.message}</p><div className="action-row">{resultId !== null && <button className="button" type="button" onClick={() => onOpenResult(resultId)}>View result #{resultId}</button>}{selected.can_retry && <button className="button" type="button" onClick={() => onRetry(selected.job_id)}>Retry as new job</button>}{selected.can_cancel && <button className="button danger-button" type="button" onClick={() => onCancel(selected.job_id)}>Cancel job</button>}</div><details><summary>Request and results</summary><pre>{JSON.stringify({ request: selected.request, result_refs: selected.result_refs }, null, 2)}</pre></details></> : <p className="helper">Select a job to inspect its progress and provenance.</p>}</section></div>;
}
