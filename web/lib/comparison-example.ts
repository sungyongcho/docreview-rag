import type { PublishedSnapshot } from "./types";

/** Match the server's explicit revision or recorded canonical golden hash. */
export function snapshotDatasetIdentity(snapshot: PublishedSnapshot): string | null {
  if (snapshot.golden_revision_id != null) return `revision:${snapshot.golden_revision_id}`;
  const config = snapshot.eval_result.config;
  const admin = config.admin_identity;
  const hash = admin && typeof admin === "object" && "golden_sha256" in admin ? admin.golden_sha256 : config.golden_sha256;
  return typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash) ? hash : null;
}
