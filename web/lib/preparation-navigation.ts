import type { Readiness } from "./types";

export type PreparationTarget = 1 | 2 | 3 | 4 | "setup";

/** Use current structured readiness, never error-message substring guesses. */
export function preparationTarget(readiness?: Readiness | null): PreparationTarget {
  const corpus = readiness?.corpus;
  if (!corpus || corpus.database_connected !== true || !["compatible", "ok"].includes(corpus.schema_status ?? "")) return "setup";
  if (corpus.documents === 0 || corpus.chunks === 0) return 2;
  if (corpus.documents === null || corpus.chunks === null) return "setup";
  if (corpus.pending_embeddings !== null && corpus.pending_embeddings > 0) return 3;
  if (corpus.pending_embeddings === null) return "setup";
  if (corpus.bm25_ready === false) return 4;
  return "setup";
}

/** A typed missing artifact leads to acquisition; other failures require diagnosis. */
export function preparationErrorTarget(code?: string | null): PreparationTarget {
  return code === "source_missing" || code === "sourcemissingerror" ? 1 : "setup";
}
