"use client";
import { translate, useI18n, type Locale } from "@/lib/i18n";


import { ArrowLeft, RefreshCw } from "lucide-react";

import { JobHistoryControls } from "./job-history-controls";
import { useMasterDetail } from "@/components/use-master-detail";
import { MasterDetailDivider } from "@/components/master-detail-divider";
import styles from "./master-detail.module.css";
import { useEffect, useRef, useState } from "react";

import type { OperatorJob, OperatorJobBoard } from "@/lib/types";
import { overallJobPercent } from "@/lib/pipeline";

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

/**
 * Turn a stored job error code into a sentence.
 *
 * The codes the worker writes are either a fixed name or a lowercased exception class,
 * so a reader meets strings like `httpstatuserror`. The raw code stays in the detail list
 * beside this sentence, because that is what is searchable in logs and issues.
 */
export function jobErrorSummary(code: string | null | undefined, locale: Locale = "en"): string | null {
  if (!code) return null;
  switch (code) {
    case "process_restarted":
      return translate(locale, "Interrupted by an application restart. Nothing is resumed automatically; retry it.");
    case "worker_error":
      return translate(locale, "The job worker failed before the job could record its own error.");
    case "postcondition_failed":
      return translate(locale, "The job ran but its result did not satisfy the check that follows it.");
    case "cancelled":
      return translate(locale, "Cancelled by an operator.");
    default:
      return translate(locale, "Stopped by an unexpected {code} raised inside the job.", { code });
  }
}

export function elapsedLabel(job: Pick<OperatorJob, "started_at" | "finished_at">, locale: Locale = "en"): string {
  if (!job.started_at) return translate(locale, "Not started");
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(job.started_at).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? translate(locale, "{minutes}m {seconds}s", { minutes, seconds: seconds % 60 }) : translate(locale, "{seconds}s", { seconds });
}

/** Format download bytes with decimal units matching the displayed transfer speed. */
function downloadSize(bytes: number, locale: Locale): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = bytes > 0 ? Math.min(Math.floor(Math.log10(bytes) / 3), units.length - 1) : 0;
  return `${(bytes / 1000 ** index).toLocaleString(locale, { maximumFractionDigits: index ? 1 : 0 })} ${units[index]}`;
}

/** Measure download bytes between server samples; reset on item changes and retries. */
function useDownloadRate(job: OperatorJob): number | null {
  const [rate, setRate] = useState<number | null>(null);
  const sample = useRef<{ key: string; bytes: number; time: number } | null>(null);
  const stage = job.progress_stage ?? job.stage;
  const active = job.status === "running" && ["acquire_edgar", "acquire_dart"].includes(job.kind)
    && ["issuer_index", "download"].includes(stage) && job.detail_current != null;
  const key = JSON.stringify([job.job_id, stage, job.current, job.message]);
  useEffect(() => {
    const bytes = job.detail_current;
    const time = Date.parse(job.updated_at);
    if (!active || bytes == null || !Number.isFinite(time)) {
      sample.current = null;
      setRate(null);
      return;
    }
    const previous = sample.current;
    if (!previous || previous.key !== key || bytes < previous.bytes || time < previous.time) {
      setRate(null);
    } else if (time > previous.time) {
      setRate((bytes - previous.bytes) * 1000 / (time - previous.time));
    }
    sample.current = { key, bytes, time };
    // Polling can stop producing samples while the transfer stalls.
    const timer = window.setTimeout(() => setRate(0), 5000);
    return () => window.clearTimeout(timer);
  }, [active, key, job.detail_current, job.updated_at]);
  return active ? rate : null;
}

export function JobProgress({ job }: { job: OperatorJob }) {
  const { t, locale } = useI18n();
  const overall = overallJobPercent(job);
  const rate = useDownloadRate(job);
  const stage = job.progress_stage ?? job.stage;
  const itemPercent = job.detail_current != null && job.detail_total != null && job.detail_total > 0
    ? Math.min(100, Math.max(0, Math.round(job.detail_current / job.detail_total * 100)))
    : null;
  const indeterminate = job.status === "running" && ["schema", "documents", "bm25"].includes(stage) && job.total === 1;
  const percent = !indeterminate && job.total && job.total > 0
    ? Math.min(100, Math.round((job.current / job.total) * 100))
    : null;
  const itemIsBytes = ["acquire_edgar", "acquire_dart"].includes(job.kind)
    && ["issuer_index", "download"].includes(stage);
  const itemLabel = (value: number) => itemIsBytes ? downloadSize(value, locale)
    : t("{count} items", { count: value.toLocaleString(locale) });
  const acquisition = ["acquire_edgar", "acquire_dart"].includes(job.kind);
  const stageLabel = acquisition && stage === "issuer_index" ? t("DART company directory download")
    : acquisition && stage === "discover" ? t("SEC filing lookup")
    : acquisition && stage === "select" ? t("DART annual report lookup")
    : acquisition && stage === "download" ? t("Original report download") : t(stage);
  const message = acquisition && stage === "issuer_index" ? t("All DART companies · company code directory")
    : job.message === "Discovering EDGAR filings" ? t("Resolving SEC company identifiers") : job.message;
  const itemIdentity = itemIsBytes && stage === "download" && job.detail_current != null && job.detail_total != null;
  const hasItemTotal = job.detail_current != null && job.detail_total != null;
  const speed = rate !== null ? <span className="job-progress-metric">{t("Download speed")}: {(rate / (rate >= 1_000_000 ? 1_000_000 : 1000)).toLocaleString(locale, { maximumFractionDigits: 1 })} {rate >= 1_000_000 ? "MB/s" : "KB/s"}</span> : null;
  return <div className="job-progress">
    <div><span className="job-progress-label"><span>{t("Overall progress")}</span><span className="job-progress-metric">{t("Elapsed")}: {elapsedLabel(job, locale)}</span></span><strong>{job.stage_index != null && job.stage_count != null ? t("Stage {current} / {total}", { current: job.stage_index, total: job.stage_count }) + " · " : ""}{overall === null ? t("Progress not reported") : `${overall}%`}</strong></div>
    {overall !== null && <progress aria-label={t("Overall progress")} max={100} value={overall} />}
    <div><span>{t("Current stage")} · {stageLabel}</span><strong>{indeterminate ? t("In progress") : job.total == null ? t("In progress") : t("{p0} / {p1}{p2}", { p0: job.current.toLocaleString(locale), p1: job.total.toLocaleString(locale), p2: percent === null ? "" : ` · ${percent}%` })}</strong></div>
    <p className="helper job-progress-meta">{!itemIdentity && <span>{message}</span>}{job.stage_started_at && <span className="job-progress-metric">{t("Stage elapsed")}: {elapsedLabel({ started_at: job.stage_started_at, finished_at: job.finished_at }, locale)}</span>}{!hasItemTotal && speed}</p>
    {job.detail_current != null && job.detail_total != null && <><div><span className="job-progress-label"><span>{t("Current item")}{itemIdentity ? ` · ${message}` : ""}</span>{speed}</span><strong>{itemLabel(job.detail_current)} / {itemLabel(job.detail_total)}{itemPercent === null ? "" : ` · ${itemPercent}%`}</strong></div><progress aria-label={t("Current item")} max={Math.max(job.detail_total, 1)} value={Math.min(job.detail_current, job.detail_total)} /></>}
  </div>;
}

export function JobActivityPanel({ board, loading, onOpenJobs }: { board: OperatorJobBoard; loading: boolean; onOpenJobs: () => void }) {
  const { t, locale } = useI18n();
  const active = board.jobs.find((job) => job.status === "running") ?? null;
  const queued = board.jobs.filter((job) => job.status === "queued").toSorted((left, right) => (left.queue_position ?? 0) - (right.queue_position ?? 0));
  const latest = board.jobs.find((job) => ["succeeded", "failed", "interrupted", "cancelled"].includes(job.status)) ?? null;
  return <section className="surface job-activity"><div className="surface-heading"><div><h2>{t("Job activity")}</h2><p className="helper">{t("Persistent corpus and evaluation queue")}</p></div><button className="button" type="button" onClick={onOpenJobs}>{t("View all jobs")}</button></div>{loading && !board.jobs.length ? <p className="helper">{t("Loading job activity…")}</p> : active ? <article className="active-job"><div className="job-title"><div><strong>{t(jobCopy(active).label)}</strong><p>{t(jobCopy(active).purpose)}</p></div><span className={`job-status ${active.status}`}>{t(active.status)}</span></div><JobProgress job={active} /><p className="helper">{t("Started")}{" "}{active.started_at ? new Date(active.started_at).toLocaleTimeString(locale === "ko" ? "ko-KR" : "en-US") : "—"}{t("· elapsed")}{" "}{elapsedLabel(active, locale)}</p></article> : <p className="helper">{t("No job is running.")}{latest ? t(" Latest: {p0} · {p1}.", { p0: t(jobCopy(latest).label), p1: t(latest.status) }) : ""}</p>}{queued.length > 0 && <div className="queued-jobs"><strong>{t("Queued ·")}{" "}{queued.length}</strong>{queued.slice(0, 3).map((job) => <span key={job.job_id}>#{job.queue_position} {t(jobCopy(job).label)}</span>)}</div>}</section>;
}

/** Keep job selection explicit and expose only actions supported by its current state. */
export function JobCenter({ board, loading, stale = false, onRetry, onCancel, onRefresh, onOpenResult, onOpenPipeline, historyEnabled = false, focusJobId }: { focusJobId?: string; board: OperatorJobBoard; loading: boolean; stale?: boolean; onRetry: (jobId: string) => void; onCancel: (jobId: string) => void; onRefresh: () => void; onOpenResult: (resultId: number) => void; onOpenPipeline?: (stage: string) => void; historyEnabled?: boolean }) {
  const { t, locale } = useI18n();
  const [domain, setDomain] = useState<"all" | OperatorJob["domain"]>("all");
  const [group, setGroup] = useState<"all" | "active" | "queued" | "history" | "failed">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const layout = useMasterDetail({ storageKey: "docreview:layout:jobs" });
  useEffect(() => {
    if (!focusJobId) return;setDomain("all");setGroup("all");setSelectedId(focusJobId);layout.openDetail();
  }, [focusJobId]);
  const visible = board.jobs.filter((job) => {
    if (domain !== "all" && job.domain !== domain) return false;
    if (group === "active" && job.status !== "running") return false;
    if (group === "failed" && !["failed", "interrupted"].includes(job.status)) return false;
    if (group === "queued" && job.status !== "queued") return false;
    if (group === "history" && ["queued", "running"].includes(job.status)) return false;
    return true;
  });
  const selected = visible.find((job) => job.job_id === selectedId) ?? null;
  const excluded = selectedId !== null && selected === null;
  const showDetail = selectedId !== null && layout.detailOpen;
  const compact = showDetail && !layout.narrow;
  const resultId = selected?.status === "succeeded" && typeof selected.result_refs.result_id === "number" ? selected.result_refs.result_id : null;
  const originatingStage = selected?.domain === "corpus" ? ({ acquire_edgar: "filings", acquire_dart: "filings", ingest_manifest: "index", backfill_embeddings: "embeddings", rebuild_bm25: "lexical" } as Record<string, string>)[selected.kind] : undefined;
  const dateLocale = locale === "ko" ? "ko-KR" : "en-US";

  return <div ref={layout.workspaceRef} style={layout.splitStyle} className={`job-center ${styles.workspace} ${compact ? styles.split : ""}`} data-help="build.jobs.center" data-detail-open={showDetail}>
    <section id={layout.listPanelId} className={`surface ${styles.listPanel} ${compact ? styles.compact : ""}`} hidden={showDetail && layout.narrow}>
      <div className={styles.heading}><div><h2>{t("Job Center")}</h2><p className="helper">{t("{active} active · {queued} queued", { active: board.active_count.toLocaleString(locale), queued: board.queued_count.toLocaleString(locale) })}</p></div><div className="action-row">{historyEnabled && <JobHistoryControls onChanged={onRefresh} />}<button className="button" type="button" disabled={loading} onClick={onRefresh}><RefreshCw size={14} />{t("Refresh")}</button></div></div>
      {stale && <p className={styles.status} role="status">{t(board.jobs.length ? "Job activity may be out of date. Retrying…" : "Job activity could not be loaded. Retrying…")}</p>}
      <nav className={`lab-tabs workflow-tabs measure-tab-strip ${styles.jobsFilters}`} aria-label={t("Job filters")}>
        <div className="measure-tab-group" role="group" aria-label={t("Job domain")}>{(["all", "corpus", "evaluation"] as const).map((value) => <button key={value} type="button" aria-pressed={domain === value} onClick={() => setDomain(value)}>{t(value)}</button>)}</div>
        <div className="measure-tab-group measure-management-group" role="group" aria-label={t("Job status")}><span className="measure-management-caption" aria-hidden="true">{t("Status")}</span>{(["all", "active", "queued", "failed", "history"] as const).map((value) => <button key={value} type="button" aria-pressed={group === value} onClick={() => setGroup(value)}>{t(value)}</button>)}</div>
      </nav>
      <div ref={layout.listRef} className={styles.list} aria-busy={loading}>
        <div className={styles.jobColumnLabels} aria-hidden="true"><span>{t("Job")}</span><span>{t("Target")}</span><span>{t("Status")}</span><span>{t("Progress")}</span><span>{t("Started")}</span></div>
        {loading && !board.jobs.length && <p className={styles.status} role="status">{t("Loading job activity…")}</p>}
        {visible.map((job) => <button className={`job-list-row ${styles.jobRow}`} type="button" key={job.job_id} aria-pressed={selectedId === job.job_id} onClick={() => { setSelectedId(job.job_id); layout.openDetail(); }}>
          <span><strong>{t(jobCopy(job).label)}</strong><small>{job.queue_position ? t("Queue #{p0} · ", { p0: job.queue_position }) : ""}{t(job.progress_stage ?? job.stage)}</small></span>
          <span className={styles.jobTarget}>{jobTarget(job) ?? t(job.domain)}</span>
          <span className={`job-status ${job.status}`}>{t(job.status)}</span>
          <span className={styles.jobProgress}>{overallJobPercent(job) === null ? "—" : t("{p0}%", { p0: overallJobPercent(job)! })}</span>
          <time dateTime={job.created_at}>{new Date(job.created_at).toLocaleDateString(dateLocale, { month: "short", day: "numeric" })}<small>{new Date(job.created_at).toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" })}</small></time>
        </button>)}
        {!loading && !visible.length && <p className={styles.status}>{t("No jobs match this filter.")}</p>}
      </div>
    </section>
    {compact && <MasterDetailDivider label={t("Resize job panels")} controls={layout.listPanelId} resize={layout.resize} />}
    {showDetail && <div className={styles.detailWrap}>
      <button className="button ghost" type="button" onClick={layout.closeDetail}><ArrowLeft size={15} />{t("Back to jobs")}</button>
      {excluded ? <section className="surface" role="status"><h2>{t("Job outside current filters")}</h2><p className="helper">{t("The selected job is not in these results. Change filters or choose another job.")}</p><button className="button" type="button" onClick={() => { setDomain("all"); setGroup("all"); layout.closeDetail(); }}>{t("Reset filters")}</button></section> : selected && <section className="surface job-detail">
        <div className="job-title"><div><p className="eyebrow">{t("Job details")}</p><h2>{t(jobCopy(selected).label)}</h2><p>{t(jobCopy(selected).purpose)}</p></div><span className={`job-status ${selected.status}`}>{t(selected.status)}</span></div>
        <section className="document-detail-section"><h3>{t("Actual progress")}</h3><JobProgress job={selected} /><dl className="status-list"><div><dt>{t("Created")}</dt><dd>{new Date(selected.created_at).toLocaleString(dateLocale)}</dd></div><div><dt>{t("Started")}</dt><dd>{selected.started_at ? new Date(selected.started_at).toLocaleString(dateLocale) : "—"}</dd></div><div><dt>{t("Finished")}</dt><dd>{selected.finished_at ? new Date(selected.finished_at).toLocaleString(dateLocale) : "—"}</dd></div><div><dt>{t("Elapsed")}</dt><dd>{elapsedLabel(selected, locale)}</dd></div><div><dt>{t("Last update")}</dt><dd>{new Date(selected.updated_at).toLocaleString(dateLocale)}</dd></div></dl></section>
        {selected.error_code && <section className="document-detail-section"><h3>{t("Error")}</h3><p className="job-error">{jobErrorSummary(selected.error_code, locale)}</p><code>{selected.error_code}</code></section>}
        <section className="document-detail-section"><h3>{t("Request options")}</h3>{Object.keys(selected.request).length > 0 ? <dl className={styles.request}>{Object.entries(selected.request).map(([key, value]) => <div key={key}><dt>{t(key.replaceAll("_", " "))}</dt><dd><pre className={styles.codeValue}><code>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</code></pre></dd></div>)}</dl> : <p className="helper">{t("No request options were recorded.")}</p>}</section>
        {(resultId !== null || Object.keys(selected.result_refs).length > 0) && <section className="document-detail-section"><h3>{t("Results")}</h3><dl className={styles.request}>{Object.entries(selected.result_refs).map(([key, value]) => <div key={key}><dt>{t(key.replaceAll("_", " "))}</dt><dd><pre className={styles.codeValue}><code>{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</code></pre></dd></div>)}</dl></section>}
        <div className="action-row">
          {onOpenPipeline && originatingStage && <button className="button" type="button" onClick={() => onOpenPipeline(originatingStage)}>{t("Open originating step")}</button>}
          {resultId !== null && <button className="button primary" type="button" onClick={() => onOpenResult(resultId)}>{t("View result #")}{resultId}</button>}
          {selected.can_retry && ["failed", "interrupted"].includes(selected.status) && <button className="button primary" type="button" onClick={() => onRetry(selected.job_id)}>{t("Retry as new job")}</button>}
          {selected.can_cancel && ["queued", "running"].includes(selected.status) && <button className="button danger-button" type="button" onClick={() => onCancel(selected.job_id)}>{t("Cancel job")}</button>}
        </div>
        <details><summary>{t("Request and results")}</summary><pre>{JSON.stringify({ job_id: selected.job_id, request: selected.request, result_refs: selected.result_refs }, null, 2)}</pre></details>
      </section>}
    </div>}
  </div>;
}

/** Read a concise target from the persisted request without inventing missing provenance. */
function jobTarget(job: OperatorJob): string | null {
  for (const key of ["doc_id", "identifiers", "tickers", "stock_codes", "suite_id", "snapshot_id", "manifest"]) {
    const value = job.request[key];
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value) && value.length) return value.map(String).join(", ");
  }
  return null;
}
