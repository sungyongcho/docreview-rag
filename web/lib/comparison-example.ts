import type { PublishedSnapshot } from "./types";

/** Match the server's identity of the cases actually evaluated. */
export function snapshotDatasetIdentity(snapshot: PublishedSnapshot): string | null {
  const hash = snapshot.eval_result.config.evaluated_golden_sha256;
  return typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash) ? hash : null;
}
