import type { PublishedSnapshot } from "./types";

type Settings = Record<string, unknown>;

/** Match the server's identity of the cases actually evaluated. */
function snapshotDatasetIdentity(snapshot: PublishedSnapshot): string | null {
  const hash = snapshot.eval_result.config.evaluated_golden_sha256;
  return typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash) ? hash : null;
}

/** Read the retrieval settings recorded in the snapshot's evaluation configuration. */
function retrievalProfile(snapshot: PublishedSnapshot): Settings {
  const nested = snapshot.profile.retrieval_profile;
  return nested && typeof nested === "object" && !Array.isArray(nested) ? nested as Settings : {};
}

/** Serialize a JSON value with object keys sorted at every depth. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** Serialize the whole recorded configuration except the lexical ranker. */
function settingsBesidesRanker(snapshot: PublishedSnapshot): string {
  const { lexical_ranker: _ranker, ...retrieval } = retrievalProfile(snapshot);
  return canonical({ ...snapshot.profile, retrieval_profile: retrieval });
}

/** Find the public example: a DART Korean ts_rank_cd run at k=5 and the newest BM25 run
 *  that differs from it only in the lexical ranker, on the same evaluated cases and corpus.
 *  Labels are not consulted, so regenerated or renamed snapshots keep the example. */
export function comparisonExamplePair(snapshots: PublishedSnapshot[]): { baseline: PublishedSnapshot; candidate: PublishedSnapshot } | null {
  const newestFirst = snapshots
    .filter(row => row.public && row.status === "ready" && row.eval_result.suite === "dart-ko" && snapshotDatasetIdentity(row))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  for (const candidate of newestFirst.filter(row => retrievalProfile(row).lexical_ranker === "ts_rank_cd" && retrievalProfile(row).k === 5)) {
    const baseline = newestFirst.find(row => retrievalProfile(row).lexical_ranker === "bm25"
      && snapshotDatasetIdentity(row) === snapshotDatasetIdentity(candidate)
      && row.corpus_fingerprint === candidate.corpus_fingerprint
      && settingsBesidesRanker(row) === settingsBesidesRanker(candidate));
    if (baseline) return { baseline, candidate };
  }
  return null;
}
