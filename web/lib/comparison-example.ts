import type { SnapshotComparison, PublishedSnapshot } from "./types";

/** The existing 2-of-3 versus 3-of-3 teaching example, never a measured server run. */
export const COMPARISON_EXAMPLE: Pick<SnapshotComparison, "metrics" | "cases"> = {
  metrics: [
    { name: "hit_rate_at_k", baseline: 2 / 3, candidate: 1, delta: 1 / 3 },
    { name: "mrr", baseline: 0.5, candidate: 5 / 6, delta: 1 / 3 },
  ],
  cases: [
    { case_id: "example-1", baseline_question: "Find the reported revenue.", candidate_question: "Find the reported revenue.", baseline_rank: 1, candidate_rank: 1, rank_delta: 0, transition: "stable_hit" },
    { case_id: "example-2", baseline_question: "Find the memory business risk factors.", candidate_question: "Find the memory business risk factors.", baseline_rank: 2, candidate_rank: 1, rank_delta: -1, transition: "stable_hit" },
    { case_id: "example-3", baseline_question: "Find the explanation of capital expenditure.", candidate_question: "Find the explanation of capital expenditure.", baseline_rank: null, candidate_rank: 2, rank_delta: null, transition: "miss_to_hit" },
  ],
};

/** Match the server's explicit revision or recorded canonical golden hash. */
export function snapshotDatasetIdentity(snapshot: PublishedSnapshot): string | null {
  if (snapshot.golden_revision_id != null) return `revision:${snapshot.golden_revision_id}`;
  const config = snapshot.eval_result.config;
  const admin = config.admin_identity;
  const hash = admin && typeof admin === "object" && "golden_sha256" in admin ? admin.golden_sha256 : config.golden_sha256;
  return typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash) ? hash : null;
}
