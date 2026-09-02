"use client";

import type { RetrievalProfile } from "@/lib/types";

export function ProfileFields({ profile, onChange }: { profile: RetrievalProfile; onChange: (profile: RetrievalProfile) => void }) {
  function patch(update: Partial<RetrievalProfile>) { onChange({ ...profile, ...update }); }
  return <div className="profile-grid">
    <label>Strategy<select value={profile.strategy} onChange={(event) => patch({ strategy: event.target.value as RetrievalProfile["strategy"], lexical_ranker: event.target.value === "vector" ? null : profile.lexical_ranker ?? "ts_rank_cd" })}><option value="hybrid">Hybrid</option><option value="vector">Vector</option><option value="lexical">Lexical</option></select></label>
    <label>Lexical<select disabled={profile.strategy === "vector"} value={profile.lexical_ranker ?? "ts_rank_cd"} onChange={(event) => patch({ lexical_ranker: event.target.value as RetrievalProfile["lexical_ranker"] })}><option value="ts_rank_cd">ts_rank_cd</option><option value="bm25">BM25</option></select></label>
    <label>k<input type="number" min={1} max={100} value={profile.k} onChange={(event) => patch({ k: Number(event.target.value) })} /></label>
    <label>candidate_k<input type="number" min={profile.k} max={500} value={profile.candidate_k} onChange={(event) => patch({ candidate_k: Number(event.target.value) })} /></label>
    <label>RRF k<input type="number" min={1} value={profile.rrf_k} onChange={(event) => patch({ rrf_k: Number(event.target.value) })} /></label>
    <label>BM25 k1<input type="number" step="0.1" min="0.1" value={profile.bm25_k1} onChange={(event) => patch({ bm25_k1: Number(event.target.value) })} /></label>
    <label>BM25 b<input type="number" step="0.05" min="0" max="1" value={profile.bm25_b} onChange={(event) => patch({ bm25_b: Number(event.target.value) })} /></label>
    <label>BM25 IDF<select value={profile.bm25_idf} onChange={(event) => patch({ bm25_idf: event.target.value as RetrievalProfile["bm25_idf"] })}><option value="lucene">Lucene</option><option value="robertson">Robertson</option></select></label>
    <label>Reranker<select disabled={profile.strategy !== "hybrid"} value={profile.reranker ?? "none"} onChange={(event) => patch({ reranker: event.target.value === "none" ? null : "cross_encoder" })}><option value="none">None</option><option value="cross_encoder">Cross encoder</option></select></label>
    <label className="checkbox"><input type="checkbox" checked={profile.route_by_language} disabled={profile.strategy !== "hybrid"} onChange={(event) => patch({ route_by_language: event.target.checked })} /> Route by language</label>
  </div>;
}
