"use client";
import { useI18n } from "@/lib/i18n";


import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { createPortal } from "react-dom";
import { ChevronRight, SlidersHorizontal } from "lucide-react";
import { Segmented } from "@/components/segmented";
import { RequestPreview, presetDescription } from "@/components/request-preview";
import { useRetainedPanelActive } from "@/components/retained-panel";
import type { CorpusScope, Readiness, RetrievalPreset, ReviewSessionProfile } from "@/lib/types";
import { applyRetrievalPreset, resolvedRetrievalProfile } from "@/lib/types";

export interface ComposerToolbarProps {
  engineControls?: ReactNode;
  query?: string;
  settingsOpen?: boolean;
  settingsTriggerRef?: Ref<HTMLButtonElement>;
  profile: ReviewSessionProfile;
  onChange: (update: Partial<ReviewSessionProfile>) => void;
  /** `capabilities.can_change_custom_retrieval`; a public build choosing Custom calls `onLocked` instead. */
  canUseCustom: boolean;
  onLocked: () => void;
  /** Opens the unified conversation editor at its Filters section. */
  onOpenSettings: () => void;
  /** Opens the current Custom retrieval editor without submitting a request. */
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
  if (corpus.database_connected !== true || corpus.schema_status !== "compatible" || typeof corpus.documents !== "number") return "Readiness not confirmed";
  if (corpus.documents === 0) return "Corpus empty";
  if ((corpus.pending_embeddings ?? 0) > 0) return "Embeddings pending";
  if (corpus.availability !== "ready" || typeof corpus.pending_embeddings !== "number" || typeof corpus.bm25_ready !== "boolean") return "Readiness not confirmed";
  return corpus.bm25_ready ? "Hybrid search ready" : "Vector search ready · BM25 unavailable";
}

/** Number of active session filters shown on the Filters chip. */
export function filterCount(profile: ReviewSessionProfile): number {
  return profile.issuers.length + profile.fiscal_years.length + profile.forms.length + profile.sections.length + profile.languages.length;
}

export type ComposerBannerKind = "empty" | "vector" | "answer-model" | "budget";

export interface ComposerBannerModel {
  kind: ComposerBannerKind;
  text: string;
  action?: "build" | "answer-model";
}

export interface ComposerBannerInput {
  readiness: Readiness | null;
  live: boolean;
  profile: ReviewSessionProfile;
  /** `ReleaseLimits.daily_cost_reset_at_utc` captured after a `daily_cost_limit` error, else null. */
  resetAt: string | null;
}

/** Picks the single banner the composer shows, highest-priority blocker first; null means the plain helper line. */
export function composerBanner({ readiness, live, profile, resetAt }: ComposerBannerInput): ComposerBannerModel | null {
  if (live && readiness?.corpus.documents === 0) {
    return { kind: "empty", text: "The corpus is empty. Build it first.", action: "build" };
  }
  if (resolvedRetrievalProfile(profile).strategy === "vector" && (readiness?.corpus.pending_embeddings ?? 0) > 0) {
    return { kind: "vector", text: "Vector-only retrieval is unavailable until embeddings are ready.", action: "build" };
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
      <span>{t(banner.text)}</span>
      {banner.action === "build" && <button className="inline-link" type="button" onClick={onOpenBuild}>{t("Open Build")}</button>}
      {banner.action === "answer-model" && <button className="inline-link" type="button" onClick={onOpenAnswerModel}>{t("Set up the answer model")}</button>}
    </p>
  );
}

export function ComposerToolbar({ profile, query = "", onChange, canUseCustom, onLocked, onOpenSettings, onOpenCustom, readiness, live, onOpenBuild, engineControls, settingsOpen = false, settingsTriggerRef }: ComposerToolbarProps) {
  const { t, locale } = useI18n();
  const filters = filterCount(profile);
  const preset = presetDescription(profile, profile.retrieval_preset);
  const effective = resolvedRetrievalProfile(profile);
  const corpusLabel = readinessChipLabel(readiness, live);
  const corpusCount = live && corpusLabel.startsWith("Corpus total · ") ? readiness?.corpus.documents : undefined;
  const readinessStatus = readinessStatusLabel(readiness);

  function choosePreset(value: RetrievalPreset) {
    if (value === "custom" && !canUseCustom) {
      onLocked();
      return;
    }
    onChange(applyRetrievalPreset(profile, value));
    if (value === "custom") onOpenCustom?.();
  }

  return (
    <div className="composer-toolbar composer-toolbar-aligned">
      <div className="chip-group composer-toolbar-primary">
        <div className="composer-scope-control"><span className="composer-control-label">{t("Corpus scope")}<ControlHelp label={t("About corpus scope")}><p><strong>{t("Auto")}</strong> — {t("Auto chooses SEC or DART from the question and filters. The server result appears in progress.")}</p><p><strong>SEC</strong> — {t("Search SEC filings from U.S. registrants.")}</p><p><strong>DART</strong> — {t("Search Korean DART filings.")}</p></ControlHelp></span><Segmented label={t("Corpus scope")} helpId="review.scope" options={SCOPE_OPTIONS} value={profile.corpus_scope} onChange={(value) => onChange({ corpus_scope: value })} /><p className="composer-control-description">{t(profile.corpus_scope === "auto" ? "Automatic source routing" : profile.corpus_scope === "sec" ? "U.S. SEC filings" : "Korean DART filings")}</p></div>
        {engineControls}
        <div className="composer-preset-control"><div className="composer-control-label"><label htmlFor="composer-retrieval-preset">{t("Retrieval preset")}</label><ControlHelp label={t("About retrieval presets")}><p>{t(preset.purpose)}</p><code>{preset.settings}</code><p>{t("Open request preview to compare all presets.")}</p></ControlHelp></div><select id="composer-retrieval-preset" className="chip" aria-label={t("Retrieval preset")} data-help="review.preset" value={profile.retrieval_preset} onChange={(event) => choosePreset(event.target.value as RetrievalPreset)}>
          <option value="balanced">{t("Balanced")}</option>
          <option value="korean">{t("Korean")}</option>
          <option value="accuracy">{t("Accuracy")}</option>
          {(canUseCustom || profile.retrieval_preset === "custom") && <option value="custom">{t("Custom")}</option>}
        </select><p className="composer-control-description">{effective.strategy} · k {effective.k} · {t("Candidates")} {effective.candidate_k}</p></div>
        <div className="composer-toolbar-actions"><button ref={settingsTriggerRef} className="chip" type="button" data-help="review.rag" aria-haspopup="dialog" aria-expanded={settingsOpen} onClick={onOpenSettings}><SlidersHorizontal size={16} aria-hidden="true" />{filters > 0 ? t("Review settings · {p0}", { p0: filters }) : t("Review settings")}</button>
        {profile.snapshot_id !== null && (
          <span className="chip snapshot" data-help="review.snapshot">{t("Snapshot #")}{profile.snapshot_id}
            <button type="button" aria-label={t("Clear snapshot")} onClick={() => onChange({ snapshot_id: null, applied_from_evaluation: null })}>×</button>
          </span>
        )}
        <RequestPreview profile={profile} query={query} />
        </div>
      </div>
      <div className="composer-toolbar-secondary">
        <div className="composer-corpus-readiness">
          <div className="composer-readiness-facts"><span>{typeof corpusCount === "number" ? t("Corpus total · {count} filings", { count: corpusCount.toLocaleString(locale) }) : t(corpusLabel)}</span><small className={readinessStatus === "Hybrid search ready" ? "confirmed" : ""}>{t(readinessStatus)}</small></div>
          <button className="button ghost corpus-readiness-action" type="button" data-help="review.readiness" onClick={onOpenBuild}>{t("View corpus readiness")}<ChevronRight size={14} aria-hidden="true" /></button>
        </div>
      </div>
    </div>
  );
}
