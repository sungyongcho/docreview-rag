import { translate, type Locale } from "./i18n";
import type { GoldenRevision, GoldenSuite, RetrievalProfile, PublishedSnapshot } from "./types";

/** Read only objects that can hold persisted evaluation metadata. */
export function evaluationRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export interface EvaluationDatasetIdentity {
  key: string;
  filename: string | null;
  hash: string | null;
  builtin: boolean;
}

/** Prefer recorded names; resolve old records only through their explicit catalog identity. */
export function evaluationDataset(suite: string, fileId: number | null | undefined, config: unknown, suites: GoldenSuite[], files: GoldenRevision[]): EvaluationDatasetIdentity {
  const value = evaluationRecord(config);
  const provenance = evaluationRecord(value.golden_provenance);
  const identity = evaluationRecord(value.admin_identity);
  const id = provenance.golden_revision_id ?? identity.golden_revision_id ?? fileId;
  const builtin = typeof id !== "number";
  const storedName = provenance.filename;
  const hash = provenance.golden_sha256 ?? identity.golden_sha256 ?? value.golden_sha256;
  return {
    key: typeof provenance.dataset_id === "string" ? provenance.dataset_id : builtin ? `builtin:${suite}` : `file:${id}`,
    filename: typeof storedName === "string" && storedName ? storedName : builtin ? suites.find(item => item.suite_id === suite)?.filename ?? null : files.find(item => item.revision_id === id)?.filename ?? null,
    hash: typeof hash === "string" && hash ? hash : null,
    builtin,
  };
}

/** Format the actual arm configuration; never invent a matrix arm from the job defaults. */
export function evaluationSettings(config: unknown, locale: Locale, fallback?: RetrievalProfile): string {
  const root = evaluationRecord(config);
  const nested = evaluationRecord(root.retrieval_profile);
  const profile = Object.keys(nested).length ? nested : typeof root.strategy === "string" ? root : fallback;
  if (!profile) return translate(locale, "Settings not recorded");
  const parts: string[] = [];
  if (typeof profile.strategy === "string") parts.push(translate(locale, profile.strategy));
  if (typeof profile.lexical_ranker === "string") parts.push(profile.lexical_ranker);
  if (typeof profile.k === "number") parts.push(`k ${profile.k}`);
  if (typeof profile.reranker === "string") parts.push(translate(locale, profile.reranker.replaceAll("_", " ")));
  if ("target_tokens" in profile && typeof profile.target_tokens === "number") parts.push(`${profile.target_tokens} ${translate(locale, "tokens")}`);
  return parts.join(" · ") || translate(locale, "Settings not recorded");
}


/** Use the dataset identity in selectors, keeping run labels in result cards. */
export function publishedDatasetLabel(snapshot: PublishedSnapshot, locale: Locale): string {
  const provenance = evaluationRecord(snapshot.eval_result.config.golden_provenance);
  const filename = typeof provenance.filename === "string" ? provenance.filename : snapshot.label;
  const kind = provenance.kind === "builtin" ? "Built-in" : "Published";
  return `${snapshot.suite_title ?? snapshot.eval_result.suite} · ${filename} (${translate(locale, kind)})`;
}
