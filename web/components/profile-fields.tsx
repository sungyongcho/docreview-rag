"use client";
import { useI18n } from "@/lib/i18n";


import type { RetrievalProfile } from "@/lib/types";

export interface ProfileFieldsProps {
  profile: RetrievalProfile;
  onChange: (profile: RetrievalProfile) => void;
  /** Help screen prefix, e.g. `measure.playground`; each field then carries `data-help="<prefix>.<field>"`. */
  helpPrefix?: string;
  /** Conversation requests have narrower candidate and fusion limits than experiments. */
  conversation?: boolean;
  /** Keep common search controls visible while placing tuning fields in a disclosure. */
  fields?: "all" | "core" | "advanced";
}

export function ProfileFields({ profile, onChange, helpPrefix, conversation = false, fields = "all" }: ProfileFieldsProps) {
  const { t, locale } = useI18n();
  function patch(update: Partial<RetrievalProfile>) { onChange({ ...profile, ...update }); }
  const help = (field: string) => (helpPrefix ? `${helpPrefix}.${field}` : undefined);
  return <div className="profile-grid">
    {fields !== "advanced" && <>
    <label data-help={help("strategy")}>{t("Strategy")}<select value={profile.strategy} onChange={(event) => patch({ strategy: event.target.value as RetrievalProfile["strategy"], lexical_ranker: event.target.value === "vector" ? null : profile.lexical_ranker ?? "ts_rank_cd" })}><option value="hybrid">{t("Hybrid")}</option><option value="vector">{t("Vector")}</option><option value="lexical">{t("Lexical")}</option></select></label>
    <label data-help={help("lexical_ranker")}>{t("Lexical")}<select disabled={profile.strategy === "vector"} value={profile.lexical_ranker ?? "ts_rank_cd"} onChange={(event) => patch({ lexical_ranker: event.target.value as RetrievalProfile["lexical_ranker"] })}><option value="ts_rank_cd">{t("ts_rank_cd")}</option><option value="bm25">{t("BM25")}</option></select></label>
    <label data-help={help("k")}>{t("k")}<input type="number" min={1} max={100} value={profile.k} onChange={(event) => patch({ k: Number(event.target.value) })} /></label>
    </>}
    {fields !== "core" && <>
    <label data-help={help("candidate_k")}>{t("candidate_k")}<input type="number" min={profile.k} max={conversation ? 100 : 500} value={profile.candidate_k} onChange={(event) => patch({ candidate_k: Number(event.target.value) })} /></label>
    <label data-help={help("rrf_k")}>{t("RRF k")}<input type="number" min={1} max={conversation ? 10000 : undefined} value={profile.rrf_k} onChange={(event) => patch({ rrf_k: Number(event.target.value) })} /></label>
    <label data-help={help("bm25_k1")}>{t("BM25 k1")}<input type="number" step="0.1" min="0.1" value={profile.bm25_k1} onChange={(event) => patch({ bm25_k1: Number(event.target.value) })} /></label>
    <label data-help={help("bm25_b")}>{t("BM25 b")}<input type="number" step="0.05" min="0" max="1" value={profile.bm25_b} onChange={(event) => patch({ bm25_b: Number(event.target.value) })} /></label>
    <label data-help={help("bm25_idf")}>{t("BM25 IDF")}<select value={profile.bm25_idf} onChange={(event) => patch({ bm25_idf: event.target.value as RetrievalProfile["bm25_idf"] })}><option value="lucene">{t("Lucene")}</option><option value="robertson">{t("Robertson")}</option></select></label>
    <label data-help={help("reranker")}>{t("Reranker")}<select disabled={profile.strategy !== "hybrid"} value={profile.reranker ?? "none"} onChange={(event) => patch({ reranker: event.target.value === "none" ? null : "cross_encoder" })}><option value="none">{t("None")}</option><option value="cross_encoder">{t("Cross encoder")}</option></select></label>
    <label className="checkbox" data-help={help("route_by_language")}><input type="checkbox" checked={profile.route_by_language} disabled={profile.strategy !== "hybrid"} onChange={(event) => patch({ route_by_language: event.target.checked })} />{t("Route by language")}</label>
    </>}
  </div>;
}
