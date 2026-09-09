"use client";

import { useEffect, useMemo, useState } from "react";
import { MessageSquare } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { getPublishedDocuments } from "@/lib/api";
import type { CorpusDocument, ReviewSessionDraft } from "@/lib/types";
import { DevLockedButton } from "./dev-locked-button";

export type ScopeFilters = Pick<ReviewSessionDraft, "registries" | "issuers" | "fiscal_years">;

interface CompanyRow { registry: string; issuer: string; name: string; years: number[]; }

/** Group the published documents into one company row per registry with its fiscal years. */
function companyRows(documents: CorpusDocument[]): CompanyRow[] {
  const rows = new Map<string, CompanyRow>();
  for (const document of documents) {
    const key = `${document.registry}:${document.issuer}`;
    const row = rows.get(key) ?? { registry: document.registry, issuer: document.issuer, name: document.issuer_name ?? document.issuer, years: [] };
    if (!row.years.includes(document.fiscal_year)) row.years.push(document.fiscal_year);
    rows.set(key, row);
  }
  return [...rows.values()].map((row) => ({ ...row, years: row.years.sort() })).sort((a, b) => a.registry.localeCompare(b.registry) || a.name.localeCompare(b.name));
}

/**
 * The read-only face of the Filings stage: the corpus a public server already holds, with the
 * company × year grid acting as a question scope instead of a download basket.
 */
export function PublishedCorpusScope({ documents, onAskScope }: { documents: CorpusDocument[]; onAskScope?: (filters: ScopeFilters) => void }) {
  const { t, locale } = useI18n();
  // `null` while loading; `undefined` when the public listing is unreachable (a canned bundle keeps its fixtures).
  const [published, setPublished] = useState<CorpusDocument[] | null | undefined>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => {
    let cancelled = false;
    // The public listing pages at 100; a published corpus is small, so follow the cursor a few times at most.
    (async () => {
      const collected: CorpusDocument[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < 10; page += 1) {
        const params = new URLSearchParams({ limit: "100" });
        if (cursor) params.set("cursor", cursor);
        const result = await getPublishedDocuments(params);
        collected.push(...result.documents);
        cursor = result.next_cursor;
        if (!cursor) break;
      }
      if (!cancelled) setPublished(collected);
    })().catch(() => { if (!cancelled) setPublished(undefined); });
    return () => { cancelled = true; };
  }, []);
  const rows = useMemo(() => companyRows(published === undefined ? documents : published ?? []), [published, documents]);
  const key = (row: CompanyRow, year: number) => `${row.registry}:${row.issuer}:${year}`;
  function toggle(row: CompanyRow, year: number) {
    setSelected((current) => { const next = new Set(current); const id = key(row, year); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  }
  const filters = useMemo<ScopeFilters>(() => {
    const registries = new Set<string>(); const issuers = new Set<string>(); const years = new Set<number>();
    for (const row of rows) for (const year of row.years) if (selected.has(key(row, year))) { registries.add(row.registry); issuers.add(row.issuer); years.add(year); }
    return { registries: [...registries], issuers: [...issuers], fiscal_years: [...years].sort() };
  }, [rows, selected]);
  const count = selected.size;
  return <section className="source-matrix published-corpus-scope" aria-label={t("Published corpus")}>
    <p className="helper">{t("This server holds the built-in company range. Click a year to scope your next question; adding companies or years runs in DEV mode.")}</p>
    {!rows.length && <p className="helper">{published === null ? t("Loading published corpus…") : t("No published filings yet. They appear here once the operator publishes a snapshot.")}</p>}
    {rows.length > 0 && <div className="published-corpus-grid" role="group" aria-label={t("Company and fiscal-year selection")}>
      {rows.map((row) => <div className="published-corpus-row" key={`${row.registry}:${row.issuer}`}>
        <div className="published-corpus-company"><strong>{row.name}</strong><span>{row.registry.toUpperCase()} · {row.issuer}</span></div>
        <div className="published-corpus-years">{row.years.map((year) => <button type="button" key={year} className="chip" aria-pressed={selected.has(key(row, year))} onClick={() => toggle(row, year)}>FY{year}</button>)}</div>
      </div>)}
    </div>}
    <div className="source-sync-actions">
      <button type="button" className="button primary" disabled={!count || !onAskScope} onClick={() => onAskScope?.(filters)}><MessageSquare size={15} aria-hidden="true" />{count ? t("Ask about {count} selected filings", { count: count.toLocaleString(locale) }) : t("Ask about the whole corpus")}</button>
      <DevLockedButton reason="corpus">{t("Sync selection")}</DevLockedButton>
    </div>
  </section>;
}
