"use client";
import { useI18n } from "@/lib/i18n";


import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { createPortal } from "react-dom";
import { ChevronRight, SlidersHorizontal, LoaderCircle } from "lucide-react";
import { RetrievalPresetSelect } from "./retrieval-preset-select";
import { presetDescription } from "@/components/request-preview";
import { useRetainedPanelActive } from "@/components/retained-panel";
import type { CorpusScope, Readiness, ReleaseLimits, RetrievalPreset, ReviewSessionDraft } from "@/lib/types";
import { getReleaseLimits } from "@/lib/api";
import { applyRetrievalPreset, resolvedRetrievalProfile } from "@/lib/types";
import { retrievalReadiness } from "@/lib/pipeline";
import type { OperatorJob } from "@/lib/types";

export interface ComposerToolbarProps {
  /** Refresh server usage after the active request ends; never decrement a local estimate. */
  requestPending?: boolean;
  /** A public catalog/scope blocker takes precedence over global index readiness. */
  publicScopeStatus?: string | null;
  engineControls?: ReactNode;
  query?: string;
  settingsOpen?: boolean;
  settingsTriggerRef?: Ref<HTMLButtonElement>;
  profile: ReviewSessionDraft;
  onChange: (update: Partial<ReviewSessionDraft>) => void;
  /** `capabilities.can_change_custom_retrieval`; a public build choosing Custom calls `onLocked` instead. */
  canUseCustom: boolean;
  onLocked: () => void;
  /** Opens the unified conversation editor at its Filters section. */
  onOpenSettings: () => void;
  /** Opens browser-local preset management without changing the conversation. */
  onOpenCustom?: () => void;
  readiness: Readiness | null;
  live: boolean;
  onOpenBuild: () => void;
}

const SCOPE_OPTIONS: Array<{ value: CorpusScope; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "sec", label: "SEC" },
  { value: "dart", label: "DART" },
];

/** Compact help works for pointer hover, keyboard focus, and touch toggles. */
function ControlHelp({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const active = useRetainedPanelActive();
  const visible = open && active;
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const trigger = useRef<HTMLButtonElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const pinned = useRef(false);
  const hovered = useRef(false);
  const id = useId();
  useEffect(() => {
    if (!visible) return;
    const align = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (rect) {
        const height = tooltip.current?.getBoundingClientRect().height ?? 0;
        const top = rect.top >= height + 20 ? rect.top - height - 8 : Math.min(rect.bottom + 8, window.innerHeight - height - 12);
        setPosition({ left: Math.max(12, Math.min(rect.left, window.innerWidth - 352)), top: Math.max(12, top) });
      }
    };
    const close = () => { pinned.current = false; setOpen(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); close(); } };
    const outside = (event: PointerEvent) => { if (!trigger.current?.contains(event.target as Node) && !tooltip.current?.contains(event.target as Node)) close(); };
    align();
    window.addEventListener("resize", align);
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", outside);
    return () => { window.removeEventListener("resize", align); document.removeEventListener("keydown", key); document.removeEventListener("pointerdown", outside); };
  }, [visible]);
  return <>
    <button ref={trigger} className="composer-control-help" type="button" aria-label={label} aria-expanded={visible} aria-describedby={visible ? id : undefined}
      onMouseEnter={() => { hovered.current = true; setOpen(true); }} onMouseLeave={(event) => { hovered.current = false; if (event.relatedTarget instanceof Node && tooltip.current?.contains(event.relatedTarget)) return; if (!pinned.current && document.activeElement !== trigger.current) setOpen(false); }}
      onFocus={() => setOpen(true)} onBlur={() => { if (!pinned.current && !hovered.current) setOpen(false); }} onClick={() => { pinned.current = !pinned.current; setOpen(pinned.current); }}>?</button>
    {visible && createPortal(<div ref={tooltip} id={id} role="tooltip" className="composer-help-tooltip" style={position} onMouseEnter={() => { hovered.current = true; }} onMouseLeave={() => { hovered.current = false; if (!pinned.current && document.activeElement !== trigger.current) setOpen(false); }}>{children}</div>, document.body)}
  </>;
}

/** Identify the global corpus separately from the selected question filters. */
export function readinessChipLabel(readiness: Readiness | null, live: boolean): string {
  if (!live) return "Published corpus";
  const corpus = readiness?.corpus;
  return corpus?.database_connected === true && corpus.schema_status === "compatible" && typeof corpus.documents === "number"
    ? `Corpus total · ${corpus.documents.toLocaleString()} filings`
    : "Corpus total";
}

/** Unknown index and database states never imply that hybrid retrieval is ready. */
export function readinessStatusLabel(readiness: Readiness | null): string {
  if (!readiness) return "Checking corpus…";
  const corpus = readiness.corpus;
  if (corpus.availability === "not_applicable") return "Readiness not reported";
  if (corpus.availability === "unavailable" || corpus.database_connected === false || (typeof corpus.schema_status === "string" && corpus.schema_status !== "compatible")) return "Corpus unavailable";
  if (corpus.database_connected === true && corpus.schema_status === "compatible" && corpus.documents === null && corpus.availability === "ready" && typeof corpus.bm25_ready === "boolean") return corpus.bm25_ready ? "Hybrid search ready" : "Vector search ready · BM25 unavailable";
  if (corpus.database_connected !== true || corpus.schema_status !== "compatible" || typeof corpus.documents !== "number") return "Readiness not confirmed";
  if (corpus.documents === 0) return "Corpus empty";
  if ((corpus.pending_embeddings ?? 0) > 0) return "Embeddings pending";
  if (corpus.availability !== "ready" || typeof corpus.pending_embeddings !== "number" || typeof corpus.bm25_ready !== "boolean") return "Readiness not confirmed";
  return corpus.bm25_ready ? "Hybrid search ready" : "Vector search ready · BM25 unavailable";
}

/** Number of active session filters shown on the Filters chip. */
export function filterCount(profile: ReviewSessionDraft): number {
  return profile.doc_ids.length + profile.registries.length + profile.issuers.length + profile.fiscal_years.length + profile.forms.length + profile.sections.length + profile.languages.length;
}

export type ComposerBannerKind = "updating" | "empty" | "preparation" | "answer-model" | "budget";

export interface ComposerBannerModel {
  kind: ComposerBannerKind;
  text: string;
  action?: "build" | "answer-model";
  step?: 2 | 3 | 4;
}

export interface ComposerBannerInput {
  readiness: Readiness | null;
  live: boolean;
  profile: ReviewSessionDraft;
  /** `ReleaseLimits.daily_cost_reset_at_utc` captured after a `daily_cost_limit` error, else null. */
  resetAt: string | null;
  jobs?: OperatorJob[];
}

/** Picks the single banner the composer shows, highest-priority blocker first; null means the plain helper line. */
export function composerBanner({ readiness, live, profile, resetAt, jobs = [] }: ComposerBannerInput): ComposerBannerModel | null {
  if (readiness?.corpus.updating) return { kind: "updating", text: "Search data is updating. Existing answers can finish; new questions will be available after preparation." };
  if (live && readiness?.corpus.documents === 0) {
    return { kind: "empty", text: "The corpus is empty. Build it first.", action: "build" };
  }
  // Public readiness deliberately hides corpus counts; its ready status remains authoritative.
  if (readiness?.mode === "runtime" && readiness.corpus.availability !== "not_applicable"
    && (live || readiness.corpus.availability !== "ready")) {
    const requirement = retrievalReadiness(readiness.corpus, resolvedRetrievalProfile(profile).strategy, jobs);
    if (requirement.status !== "done") return live ? { kind: "preparation", text: requirement.hint, action: "build", step: requirement.blockedBy === "embeddings" ? 3 : requirement.blockedBy === "lexical" ? 4 : 2 } : { kind: "preparation", text: "Published search is not ready yet.", action: "build" };
  }
  if (readiness?.mode === "runtime" && readiness.review_enabled === false) {
    return {
      kind: "answer-model",
      text: "Answer model is off — evidence only. Questions return retrieved filing evidence without a generated answer.",
      action: "answer-model",
    };
  }
  if (resetAt) {
    return { kind: "budget", text: `Daily answer budget is used up. Evidence still loads; answers resume at ${new Date(resetAt).toLocaleString()}.` };
  }
  return null;
}

export interface ComposerBannerProps {
  banner: ComposerBannerModel | null;
  onOpenBuild: () => void;
  /** Deep link to Build › step 6 (answer model). */
  onOpenAnswerModel: () => void;
}

export function ComposerBanner({ banner, onOpenBuild, onOpenAnswerModel }: ComposerBannerProps) {
  const { t, locale } = useI18n();
  if (!banner) return null;
  return (
    <p className={`composer-banner ${banner.kind}`} role="status">
      {banner.kind === "updating" && <LoaderCircle size={14} aria-hidden="true" />}
      <span>{t(banner.text)}</span>
      {banner.action === "build" && <button className="inline-link" type="button" onClick={onOpenBuild}>{t("Open Build")}</button>}
      {banner.action === "answer-model" && <button className="inline-link" type="button" onClick={onOpenAnswerModel}>{t("Set up the answer model")}</button>}
    </p>
  );
}

export function ComposerToolbar({ publicScopeStatus, profile, query = "", onChange, canUseCustom, onLocked, onOpenSettings, onOpenCustom, readiness, live, onOpenBuild, engineControls, settingsOpen = false, settingsTriggerRef, requestPending = false }: ComposerToolbarProps) {
  const { t, locale } = useI18n();
  const filters = filterCount(profile);
  const preset = presetDescription(profile, profile.retrieval_preset);
  const effective = resolvedRetrievalProfile(profile);
  const corpusLabel = readinessChipLabel(readiness, live);
  const corpusCount = live && corpusLabel.startsWith("Corpus total · ") ? readiness?.corpus.documents : undefined;
  const readinessStatus = !live && publicScopeStatus ? publicScopeStatus : readinessStatusLabel(readiness);
  // A public surface has one answer model; show it with the chat allowances where DEV shows the engine picker.
  const publicModel = !live && !engineControls ? readiness?.active_review_model ?? null : null;
  const showRemainingUsage = Boolean(publicModel && readiness?.environment === "prod" && readiness.mode === "runtime");
  const [limits, setLimits] = useState<ReleaseLimits | null>(null);
  const [limitsFailed, setLimitsFailed] = useState(false);
  const active = useRetainedPanelActive();
  useEffect(() => {
    if (!showRemainingUsage || !active) return;
    setLimits(null); setLimitsFailed(false);
    if (requestPending) return;
    let cancelled = false;
    let inFlight = false;
    const refresh = async () => {
      if (document.visibilityState === "hidden" || inFlight) return;
      inFlight = true;
      try {
        const value = await getReleaseLimits();
        if (![value.remaining_minute, value.remaining_day, value.per_minute, value.per_day].every((count) => Number.isFinite(count) && count >= 0)) throw new Error("Invalid request allowance");
        if (!cancelled) { setLimits(value); setLimitsFailed(false); }
      } catch {
        if (!cancelled) { setLimits(null); setLimitsFailed(true); }
      } finally { inFlight = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [showRemainingUsage, publicModel, active, requestPending]);
  const modelControls = publicModel && <div className="composer-model-control composer-engine-field">
    <span className="composer-control-label">{t("Answer model")}<ControlHelp label={t("About chat limits")}>
      <p>{t("Questions on this website call OpenAI on the server. Model choice and per-call caps are fixed here; DEV mode adds local models.")}</p>
      {showRemainingUsage && limits && <p>{t("{minute} questions per minute · {day} per day · shared daily budget ${cost}", { minute: limits.per_minute, day: limits.per_day, cost: limits.daily_cost_usd })}</p>}
      {showRemainingUsage && limits && <p>{t("Per call: up to {input} input tokens, {output} output tokens, ${cost}", { input: limits.max_input_tokens.toLocaleString(locale), output: limits.max_output_tokens.toLocaleString(locale), cost: limits.max_cost_usd })}</p>}
      {showRemainingUsage && <p>{t("Remaining request counts are shared by your IP address. Shared cost limits may also restrict availability. Counts refresh after a request and while this view is open.")}</p>}
    </ControlHelp></span>
    <span className="chip composer-model-chip" title={publicModel}>{publicModel}</span>
    {showRemainingUsage ? <span className={`composer-control-description composer-allowance${limits && (limits.remaining_minute === 0 || limits.remaining_day === 0) ? " exhausted" : ""}`} role="status" aria-live="polite">{limits ? <><span>{t("Remaining")}</span><span>{t("Minute {remaining}/{limit}", { remaining: limits.remaining_minute, limit: limits.per_minute })}</span><span>{t("Day {remaining}/{limit}", { remaining: limits.remaining_day, limit: limits.per_day })}</span></> : t(requestPending ? "Usage updates after this request" : limitsFailed ? "Remaining usage unavailable" : "Checking remaining usage…")}</span> : <span className="composer-control-description">{t("OpenAI · fixed model")}</span>}
  </div>;


  return (
    <div className="composer-toolbar composer-toolbar-aligned">
      <div className={`chip-group composer-toolbar-primary${engineControls || modelControls ? " has-engine" : ""}`}>
        <div className="composer-scope-control"><span className="composer-control-label">{t("Corpus scope")}<ControlHelp label={t("About corpus scope")}><p><strong>{t("Auto")}</strong> — {t("Auto chooses SEC or DART from the question and filters. The server result appears in progress.")}</p><p><strong>SEC</strong> — {t("Search SEC filings from U.S. registrants.")}</p><p><strong>DART</strong> — {t("Search Korean DART filings.")}</p></ControlHelp></span><div className="lab-tabs composer-scope-tabs" role="group" aria-label={t("Corpus scope")} data-help="review.scope">{SCOPE_OPTIONS.map((option) => <button key={option.value} type="button" aria-pressed={profile.corpus_scope === option.value} onClick={() => onChange({ corpus_scope: option.value })}>{t(option.label)}</button>)}</div><p className="composer-control-description">{t(profile.corpus_scope === "auto" ? "Automatic source routing" : profile.corpus_scope === "sec" ? "U.S. SEC filings" : "Korean DART filings")}</p></div>
        {engineControls}{modelControls}
        <div className="composer-preset-control"><div className="composer-control-label"><label htmlFor="composer-retrieval-preset">{t("Retrieval preset")}</label><ControlHelp label={t("About retrieval presets")}><p>{t(preset.purpose)}</p><code>{preset.settings}</code><p>{t("Open Settings and preview to inspect the next request.")}</p></ControlHelp></div><RetrievalPresetSelect id="composer-retrieval-preset" profile={profile} editable={canUseCustom} onChange={onChange} onManage={onOpenCustom} onLocked={onLocked} /><p className="composer-control-description">{effective.strategy} · k {effective.k} · {t("Candidates")} {effective.candidate_k}</p></div>
        <div className="composer-toolbar-actions"><button ref={settingsTriggerRef} className="chip composer-settings-trigger" type="button" title={t("Settings and preview")} data-help="review.rag" aria-haspopup="dialog" aria-expanded={settingsOpen} onClick={onOpenSettings}><SlidersHorizontal size={18} aria-hidden="true" /><span className="composer-settings-label">{filters > 0 ? t("Settings and preview · {p0}", { p0: filters }) : t("Settings and preview")}</span></button>
        {profile.snapshot_id !== null && (
          <span className="chip snapshot" data-help="review.snapshot">{t("Snapshot #")}{profile.snapshot_id}
            <button type="button" aria-label={t("Clear snapshot")} onClick={() => onChange({ snapshot_id: null, applied_from_evaluation: null })}>×</button>
          </span>
        )}

        </div>
      </div>
      <div className="composer-toolbar-secondary">
        <div className="composer-corpus-readiness">
          <button className="composer-readiness-facts" type="button" data-help="review.readiness" title={t("Open Build to inspect corpus readiness")} onClick={onOpenBuild}><span>{typeof corpusCount === "number" ? t("Corpus total · {count} filings", { count: corpusCount.toLocaleString(locale) }) : t(corpusLabel)}</span><small className={readinessStatus === "Hybrid search ready" ? "confirmed" : ""}>{t(readinessStatus)}</small><ChevronRight size={13} aria-hidden="true" /></button>
          <span className="composer-key-hint">{t("Enter sends · Shift+Enter adds a line")}</span>
        </div>
      </div>
    </div>
  );
}
