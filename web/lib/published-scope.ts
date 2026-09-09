import type { AdminDocumentPage, ReviewSessionDraft, PublicTarget } from "./types";

export type PublishedDocument = AdminDocumentPage["documents"][number];
/** Fixed fiscal years from the tested default acquisition draft, not calendar years. */
export const PORTFOLIO_FILINGS = [
  { registry: "sec", issuer: "NVDA", first: 2019, last: 2024 },
  { registry: "sec", issuer: "AMD", first: 2019, last: 2024 },
  { registry: "dart", issuer: "005930", first: 2022, last: 2024 },
  { registry: "dart", issuer: "000660", first: 2022, last: 2024 },
] as const;

/** Include only published identities inside the fixed 18 company/year pairs. */
export function portfolioDocuments(documents: PublishedDocument[]): PublishedDocument[] {
  return [...new Map(documents.filter((doc) => PORTFOLIO_FILINGS.some((target) =>
    doc.registry === target.registry && doc.issuer === target.issuer && doc.fiscal_year >= target.first && doc.fiscal_year <= target.last
  )).map((doc) => [doc.doc_id, doc])).values()];
}

/** Keep exact saved document identities; undefined is the legacy whole-corpus choice. */
export function selectedPublishedDocuments(documents: PublishedDocument[], ids: string[] | undefined): PublishedDocument[] {
  return ids === undefined ? documents : documents.filter((doc) => ids.includes(doc.doc_id));
}

/** Resolve the tab and manual dimensions without expanding a sparse document selection. */
export function effectivePublishedProfile(profile: ReviewSessionDraft, documents: PublishedDocument[], ids: string[] | undefined): ReviewSessionDraft {
  const selected = selectedPublishedDocuments(documents, ids).filter((doc) =>
    (profile.corpus_scope === "auto" || doc.registry === profile.corpus_scope)
    && (!profile.registries.length || profile.registries.includes(doc.registry))
    && (!profile.issuers.length || profile.issuers.includes(doc.issuer))
    && (!profile.fiscal_years.length || profile.fiscal_years.includes(doc.fiscal_year))
    && (!profile.doc_ids.length || profile.doc_ids.includes(doc.doc_id)));
  // Exact IDs carry the selection. Issuer filters must not conflict with a SEC/DART tab.
  const whole = selected.length === documents.length && profile.corpus_scope === "auto";
  return { ...profile, doc_ids: selected.map((doc) => doc.doc_id),
    registries: whole ? [] : [...new Set(selected.map((doc) => doc.registry))],
    issuers: whole ? [] : [...new Set(selected.map((doc) => doc.issuer))],
    fiscal_years: whole ? [] : [...new Set(selected.map((doc) => doc.fiscal_year))] };
}

/** Summarize the real selected document rows, keeping unknown embedding coverage unknown. */
export function publishedScopeStats(documents: PublishedDocument[], ids: string[]) {
  const selected = documents.filter((doc) => ids.includes(doc.doc_id));
  const embedded = selected.every((doc) => typeof doc.embedded_chunks === "number")
    ? selected.reduce((sum, doc) => sum + doc.embedded_chunks!, 0) : null;
  const chunks = selected.reduce((sum, doc) => sum + doc.chunk_count, 0);
  return { filings: selected.length, total: documents.length, chunks, embedded, pending: embedded === null ? null : Math.max(0, chunks - embedded) };
}


/** Persist browser intent without pretending that unpublished targets have document IDs. */
export function createPublicTargets(documents: PublishedDocument[], pairs: PublicTarget[]): PublicTarget[] {
  return [...new Map(pairs.filter((pair) => PORTFOLIO_FILINGS.some((row) => row.registry === pair.registry && row.issuer === pair.issuer && pair.year >= row.first && pair.year <= row.last)).map((pair) => {
    const ids = documents.filter((doc) => doc.registry === pair.registry && doc.issuer === pair.issuer && doc.fiscal_year === pair.year).map((doc) => doc.doc_id);
    const target: PublicTarget = { registry: pair.registry, issuer: pair.issuer, year: pair.year, ...(ids.length ? { document_ids: ids } : {}) };
    return [`${pair.registry}:${pair.issuer}:${pair.year}`, target] as const;
  })).values()];
}

/** Only actual published IDs can enter a request; legacy saved selections remain supported. */
export function publicTargetIds(documents: PublishedDocument[], targets: PublicTarget[] | undefined, legacy?: string[]): string[] | undefined {
  if (targets === undefined) return legacy;
  return [...new Set(targets.flatMap((target) => target.document_ids ?? documents.filter((doc) => doc.registry === target.registry && doc.issuer === target.issuer && doc.fiscal_year === target.year).map((doc) => doc.doc_id)))];
}

/** Bind newly available targets once; do not replace previously selected document identities. */
export function pinPublicTargets(documents: PublishedDocument[], targets: PublicTarget[]): PublicTarget[] {
  const next = targets.map((target) => {
    if (target.document_ids !== undefined) return target;
    const ids = publicTargetIds(documents, [target])!;
    return ids.length ? { ...target, document_ids: ids } : target;
  });
  return next.some((target, index) => target !== targets[index]) ? next : targets;
}
