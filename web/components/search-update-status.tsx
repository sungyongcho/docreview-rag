"use client";

import { Check, CircleAlert, LoaderCircle, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { overallJobPercent } from "@/lib/pipeline";
import type { OperatorJob } from "@/lib/types";
import "./search-update-status.css";

export const SEARCH_UPDATE_KINDS = new Set(["ingest_manifest", "ingest_selected", "backfill_embeddings", "rebuild_bm25"]);
const LABELS: Record<string, string> = { ingest_manifest: "Parsing / chunking", ingest_selected: "Parsing / chunking", backfill_embeddings: "Embeddings", rebuild_bm25: "Lexical index (BM25)" };

/** Share actual overall progress between the header and the existing job notification. */
export function searchUpdateProgress(job: OperatorJob, t: (text: string) => string): string {
  const percent = overallJobPercent(job);
  return `${t(LABELS[job.kind] ?? job.kind)} · ${job.status === "queued" ? t("Waiting for active questions to finish") : percent === null ? t("In progress") : `${percent}%`}`;
}

/** A temporary header indicator explains the same server admission gate as the composer. */
export function SearchUpdateStatus({ updating, preparation, jobs, stale = false, blocked = false, onOpenJobs }: {
  updating: boolean; preparation: string | null; jobs: OperatorJob[]; stale?: boolean; blocked?: boolean; onOpenJobs?: (jobId?: string) => void;
}) {
  const { t } = useI18n();
  const [engaged, setEngaged] = useState(false);
  const [success, setSuccess] = useState(false);
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const relevant = jobs.filter(job => job.domain === "corpus" && SEARCH_UPDATE_KINDS.has(job.kind));
  const job = relevant.find(job => job.status === "running") ?? relevant.find(job => job.status === "queued");
  useEffect(() => {
    if (updating) { setEngaged(true); setSuccess(false); return; }
    if (!engaged || preparation || stale) return;
    setSuccess(true);
    const timer = window.setTimeout(() => { setSuccess(false); setEngaged(false); setOpen(false); setHover(false); }, 2500);
    return () => window.clearTimeout(timer);
  }, [updating, engaged, preparation, stale]);
  useEffect(() => { if (blocked) { setOpen(false); setHover(false); } }, [blocked]);
  useEffect(() => {
    if (!open && !hover) return;
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) { setOpen(false); setHover(false); } };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { trigger.current?.focus(); setOpen(false); setHover(false); } };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open, hover]);
  if (!updating && !engaged && !success) return null;
  const latest = [...relevant].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  const failed = !updating && preparation && latest && ["failed", "interrupted"].includes(latest.status);
  const tone = updating ? "working" : preparation || stale ? failed ? "failed" : "pending" : "complete";
  const label = updating ? "Search paused" : preparation || stale ? "Search preparation needed" : "Search ready";
  const Icon = updating ? LoaderCircle : tone === "complete" ? Check : CircleAlert;
  const detail = stale ? t("Checking current job progress…") : updating ? job ? searchUpdateProgress(job, t) : t("Updating search data…") : preparation ? t(preparation) : t("You can send a new question now.");
  const visible = !blocked && (open || hover);
  return <div className={`search-update-status ${tone}`} ref={root} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
    <button ref={trigger} className="search-update-trigger" type="button" disabled={blocked} aria-label={t(label)} aria-expanded={open} aria-controls={visible ? id : undefined} aria-describedby={visible && !open ? id : undefined} onFocus={() => setHover(true)} onBlur={event => { if (!root.current?.contains(event.relatedTarget)) setHover(false); }} onClick={() => setOpen(value => !value)}>
      <Icon size={17} aria-hidden="true" /><span>{t(label)}</span>
    </button>
    {visible && <div id={id} className="search-update-panel" role={open ? "dialog" : "tooltip"} aria-label={t(label)}>
      <header><strong>{t(label)}</strong>{open && <button type="button" className="icon-button" aria-label={t("Close")} onClick={() => { trigger.current?.focus(); setOpen(false); setHover(false); }}><X size={15} /></button>}</header>
      <p>{detail}</p>
      {updating && job && !stale && overallJobPercent(job) !== null && <progress aria-label={t("Overall progress")} max={100} value={overallJobPercent(job)!} />}
      {open && <><p className="helper">{t(updating ? "Existing answers can finish. New questions pause while search data is updated." : "Check the pipeline for the next required step.")}</p>{onOpenJobs && <button type="button" className="inline-link" onClick={() => { setOpen(false); setHover(false); onOpenJobs(job?.job_id ?? latest?.job_id); }}>{t("View jobs")}</button>}</>}
    </div>}
  </div>;
}
