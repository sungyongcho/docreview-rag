"use client";
import { useI18n } from "@/lib/i18n";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile, type ReviewSessionDraft } from "@/lib/types";

const FIELDS = [
  ["strategy", "Search strategy", "Chooses vector, keyword, or combined retrieval."],
  ["k", "Results", "Maximum evidence hits returned after ranking."],
  ["candidate_k", "Candidates", "Candidates retrieved before final selection. Keep at least k; increase when useful evidence is missed."],
  ["lexical_ranker", "Keyword ranking", "Ranks keyword matches when keyword or hybrid retrieval is selected."],
  ["route_by_language", "Language routing", "Uses language-aware retrieval across the selected filing corpus."],
  ["rrf_k", "Rank fusion constant", "Controls how rank positions contribute when combining search lists."],
  ["reranker", "Reranker", "Reorders hybrid candidates with a cross encoder. Use for relevance gains when extra latency is acceptable."],
] as const;

/** Derive preset values and differences from the canonical request profiles. */
export function RetrievalPresetExplanation({ profile }: { profile: ReviewSessionDraft }) {
  const { t } = useI18n();
  const effective = resolvedRetrievalProfile(profile);
  const baseline = resolvedRetrievalProfile({ ...DEFAULT_SESSION_PROFILE, retrieval_preset: "balanced" });
  function display(value: unknown) { return typeof value === "boolean" ? t(value ? "Enabled" : "Disabled") : value == null ? t("None") : String(value); }
  return <details><summary>{t("Preset parameters and changes")}</summary><p className="helper">{t("Values are compared with Balanced. Wider retrieval can add latency; it does not guarantee a more accurate answer.")}</p><dl className="request-facts">{FIELDS.map(([key, label, description]) => {
    const inactive = (key === "rrf_k" || key === "reranker") && effective.strategy !== "hybrid" || key === "lexical_ranker" && effective.strategy === "vector";
    return <div key={key}><dt>{t(label)} (<code>{key}</code>)<p className="helper">{t(description)}</p></dt><dd>{effective[key] !== baseline[key] ? `${display(baseline[key])} → ` : ""}{display(effective[key])}{inactive && <p className="helper">{t("Not used by this search strategy.")}</p>}</dd></div>;
  })}</dl></details>;
}
