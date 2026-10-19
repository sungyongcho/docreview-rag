import type { PublishedSnapshot } from "./types";

/** Match the server's identity of the cases actually evaluated. */
function snapshotDatasetIdentity(snapshot: PublishedSnapshot): string | null {
  const hash = snapshot.eval_result.config.evaluated_golden_sha256;
  return typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash) ? hash : null;
}

/** Serialize every retrieval setting except the lexical ranker, independent of key order. */
function settingsBesidesRanker(snapshot: PublishedSnapshot): string {
  return JSON.stringify(Object.entries(snapshot.profile).filter(([key]) => key !== "lexical_ranker").sort(([a], [b]) => a.localeCompare(b)));
}

/** Find the public example: a DART Korean ts_rank_cd run at k=5 and the newest BM25 run
 *  that differs from it only in the lexical ranker, on the same evaluated cases and corpus.
 *  Labels are not consulted, so regenerated or renamed snapshots keep the example. */
export function comparisonExamplePair(snapshots: PublishedSnapshot[]): { baseline: PublishedSnapshot; candidate: PublishedSnapshot } | null {
  const newestFirst = snapshots
    .filter(row => row.public && row.status === "ready" && row.eval_result.suite === "dart-ko" && snapshotDatasetIdentity(row))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  for (const candidate of newestFirst.filter(row => row.profile.lexical_ranker === "ts_rank_cd" && row.profile.k === 5)) {
    const baseline = newestFirst.find(row => row.profile.lexical_ranker === "bm25"
      && snapshotDatasetIdentity(row) === snapshotDatasetIdentity(candidate)
      && row.corpus_fingerprint === candidate.corpus_fingerprint
      && settingsBesidesRanker(row) === settingsBesidesRanker(candidate));
    if (baseline) return { baseline, candidate };
  }
  return null;
}
