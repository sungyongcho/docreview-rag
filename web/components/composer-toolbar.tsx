"use client";

import { Segmented } from "@/components/segmented";
import type { CorpusScope, Readiness, RetrievalPreset, ReviewSessionProfile } from "@/lib/types";
import { applyRetrievalPreset, resolvedRetrievalProfile } from "@/lib/types";

export interface ComposerToolbarProps {
  profile: ReviewSessionProfile;
  onChange: (update: Partial<ReviewSessionProfile>) => void;
  /** `capabilities.can_change_custom_retrieval`; a public build choosing Custom calls `onLocked` instead. */
  canUseCustom: boolean;
  onLocked: () => void;
  /** Opens Settings › Review session. */
  onOpenFilters: () => void;
  readiness: Readiness | null;
  live: boolean;
  onOpenBuild: () => void;
}

const SCOPE_OPTIONS: Array<{ value: CorpusScope; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "sec", label: "SEC" },
  { value: "dart", label: "DART" },
];

/** Readiness chip text: read-only first, then the corpus counters in the order the Build pipeline fills them. */
export function readinessChipLabel(readiness: Readiness | null, live: boolean): string {
  if (!live) return "Read-only corpus";
  if (!readiness) return "Checking corpus…";
  const { documents, pending_embeddings, bm25_ready } = readiness.corpus;
  if (documents === 0) return "Corpus empty";
  if ((pending_embeddings ?? 0) > 0) return "Embeddings pending · lexical only";
  if (documents === null) return "Corpus unavailable";
  return `${documents.toLocaleString()} filings · ${bm25_ready === false ? "vector only" : "hybrid ready"}`;
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
  if (!banner) return null;
  return (
    <p className={`composer-banner ${banner.kind}`} role="status">
      <span>{banner.text}</span>
      {banner.action === "build" && <button className="inline-link" type="button" onClick={onOpenBuild}>Open Build</button>}
      {banner.action === "answer-model" && <button className="inline-link" type="button" onClick={onOpenAnswerModel}>Set up the answer model</button>}
    </p>
  );
}

export function ComposerToolbar({ profile, onChange, canUseCustom, onLocked, onOpenFilters, readiness, live, onOpenBuild }: ComposerToolbarProps) {
  const filters = filterCount(profile);

  function choosePreset(value: RetrievalPreset) {
    if (value === "custom" && !canUseCustom) {
      onLocked();
      return;
    }
    onChange(applyRetrievalPreset(profile, value));
  }

  return (
    <div className="composer-toolbar">
      <div className="chip-group">
        <Segmented label="Corpus scope" options={SCOPE_OPTIONS} value={profile.corpus_scope} onChange={(value) => onChange({ corpus_scope: value })} />
        <select className="chip" aria-label="Retrieval preset" value={profile.retrieval_preset} onChange={(event) => choosePreset(event.target.value as RetrievalPreset)}>
          <option value="balanced">Balanced</option>
          <option value="korean">Korean</option>
          <option value="accuracy">Accuracy</option>
          {(canUseCustom || profile.retrieval_preset === "custom") && <option value="custom">Custom</option>}
        </select>
        <button className="chip" type="button" onClick={onOpenFilters}>{filters > 0 ? `Filters · ${filters}` : "Filters"}</button>
        {profile.snapshot_id !== null && (
          <span className="chip snapshot">
            Snapshot #{profile.snapshot_id}
            <button type="button" aria-label="Clear snapshot" onClick={() => onChange({ snapshot_id: null, applied_from_evaluation: null })}>×</button>
          </span>
        )}
      </div>
      <button className="chip readiness" type="button" onClick={onOpenBuild}>{readinessChipLabel(readiness, live)}</button>
    </div>
  );
}
