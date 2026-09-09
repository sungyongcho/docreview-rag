"use client";
import { ParameterHelp } from "./parameter-help";
import "./profile-fields.css";
import { useI18n } from "@/lib/i18n";


import { useId } from "react";
import type { RetrievalProfile } from "@/lib/types";

export interface ProfileFieldsProps {
  profile: RetrievalProfile;
  onChange: (profile: RetrievalProfile) => void;
  /** Help screen prefix, e.g. `measure.playground`; each field then carries `data-help="<prefix>.<field>"`. */
  helpPrefix?: string;
  /** Conversation requests have narrower fusion limits than experiments. */
  conversation?: boolean;
  /** Keep common search controls visible while placing tuning fields in a disclosure. */
  fields?: "all" | "core" | "advanced";
}

export function ProfileFields({ profile, onChange, helpPrefix, conversation = false, fields = "all" }: ProfileFieldsProps) {
  const { t, locale } = useI18n();
  const uid = useId();
  const fieldId = (name: string) => `${uid}-${name}`;
  function patch(update: Partial<RetrievalProfile>) { onChange({ ...profile, ...update }); }
  const help = (field: string) => (helpPrefix ? `${helpPrefix}.${field}` : undefined);
  const label = (name: string, description: string, field: string) => <span className="parameter-label"><label htmlFor={fieldId(field)}>{t(name)}</label><ParameterHelp label={name} text={description} /></span>;
  return <div className="profile-grid profile-fields">
    {fields !== "advanced" && <>
    <div className="parameter-field" data-help={help("strategy")}>{label("Strategy", "Choose semantic vector search, keyword search, or hybrid search combining both.", "strategy")}<select id={fieldId("strategy")} value={profile.strategy} onChange={(event) => patch({ strategy: event.target.value as RetrievalProfile["strategy"], lexical_ranker: event.target.value === "vector" ? null : profile.lexical_ranker ?? "ts_rank_cd" })}><option value="hybrid">{t("Hybrid")}</option><option value="vector">{t("Vector")}</option><option value="lexical">{t("Lexical")}</option></select></div>
    <div className="parameter-field" data-help={help("lexical_ranker")}>{label("Lexical", "Choose the keyword ranking method. BM25 exposes term-frequency and length tuning.", "lexical_ranker")}<select id={fieldId("lexical_ranker")} disabled={profile.strategy === "vector"} value={profile.lexical_ranker ?? "ts_rank_cd"} onChange={(event) => patch({ lexical_ranker: event.target.value as RetrievalProfile["lexical_ranker"] })}><option value="ts_rank_cd">{t("ts_rank_cd")}</option><option value="bm25">{t("BM25")}</option></select></div>
    <div className="parameter-field" data-help={help("k")}>{label("k", "Number of final evidence candidates. Increase for broader coverage, with more context and processing.", "k")}<input id={fieldId("k")} type="number" min={1} max={100} value={profile.k} onChange={(event) => patch({ k: Number(event.target.value) })} /></div>
    </>}
    {fields !== "core" && <>
    <details open className="parameter-group"><summary>{t("Candidates and rank fusion")}</summary><div className="profile-grid">
    <div className="parameter-field" data-help={help("candidate_k")}>{label("candidate_k", "Candidates retrieved before final selection. Keep at least k; increase when useful evidence is missed.", "candidate_k")}<input id={fieldId("candidate_k")} type="number" min={profile.k} max={500} value={profile.candidate_k} onChange={(event) => patch({ candidate_k: Number(event.target.value) })} /></div>
    <div className="parameter-field" data-help={help("rrf_k")}>{label("RRF k", "Hybrid rank-fusion smoothing. Larger values reduce the advantage of top-ranked results.", "rrf_k")}<input id={fieldId("rrf_k")} disabled={profile.strategy !== "hybrid"} type="number" min={1} max={conversation ? 10000 : undefined} value={profile.rrf_k} onChange={(event) => patch({ rrf_k: Number(event.target.value) })} /></div>
    </div></details><details open className="parameter-group"><summary>{t("BM25 tuning")}</summary><div className="profile-grid">
    <div className="parameter-field" data-help={help("bm25_k1")}>{label("BM25 k1", "Controls how quickly repeated terms stop adding score. Increase to give repeated matches more weight.", "bm25_k1")}<input id={fieldId("bm25_k1")} disabled={profile.strategy === "vector" || profile.lexical_ranker !== "bm25"} type="number" step="any" min="0" value={profile.bm25_k1} onChange={(event) => patch({ bm25_k1: Number(event.target.value) })} /></div>
    <div className="parameter-field" data-help={help("bm25_b")}>{label("BM25 b", "Document-length normalization from 0 to 1. Increase to penalize long chunks more strongly.", "bm25_b")}<input id={fieldId("bm25_b")} disabled={profile.strategy === "vector" || profile.lexical_ranker !== "bm25"} type="number" step="any" min="0" max="1" value={profile.bm25_b} onChange={(event) => patch({ bm25_b: Number(event.target.value) })} /></div>
    <div className="parameter-field" data-help={help("bm25_idf")}>{label("BM25 IDF", "Formula for rare-term weighting. Lucene is a practical default; Robertson allows negative weights for very common terms.", "bm25_idf")}<select id={fieldId("bm25_idf")} disabled={profile.strategy === "vector" || profile.lexical_ranker !== "bm25"} value={profile.bm25_idf} onChange={(event) => patch({ bm25_idf: event.target.value as RetrievalProfile["bm25_idf"] })}><option value="lucene">{t("Lucene")}</option><option value="robertson">{t("Robertson")}</option></select></div>
    </div></details><details open className="parameter-group"><summary>{t("Reranking and language")}</summary><div className="profile-grid">
    <div className="parameter-field" data-help={help("reranker")}>{label("Reranker", "Reorders hybrid candidates with a cross encoder. Use for relevance gains when extra latency is acceptable.", "reranker")}<select id={fieldId("reranker")} disabled={profile.strategy !== "hybrid"} value={profile.reranker ?? "none"} onChange={(event) => patch({ reranker: event.target.value === "none" ? null : "cross_encoder" })}><option value="none">{t("None")}</option><option value="cross_encoder">{t("Cross encoder")}</option></select></div>
    <div className="parameter-field checkbox" data-help={help("route_by_language")}><input id={fieldId("route_by_language")} type="checkbox" checked={profile.route_by_language} disabled={profile.strategy !== "hybrid"} onChange={(event) => patch({ route_by_language: event.target.checked })} />{label("Route by language", "Runs language-aware hybrid retrieval. Use when the corpus contains multiple languages.", "route_by_language")}</div>
    </div></details></>}
  </div>;
}
