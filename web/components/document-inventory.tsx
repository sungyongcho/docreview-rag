"use client";
import { useI18n } from "@/lib/i18n";


import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, SlidersHorizontal, X } from "lucide-react";

import { useMasterDetail } from "@/components/use-master-detail";
import { MasterDetailDivider } from "@/components/master-detail-divider";
import "./document-identity.css";
import styles from "./master-detail.module.css";

import { getAdminDocuments, getDocumentDetail, getDocumentFacets, getPublishedDocuments, getPublishedDocumentDetail, getPublishedDocumentFacets } from "@/lib/api";
import { companyLabel } from "@/lib/company-labels";
import type { AdminDocument, DocumentDetail, DocumentEmbeddingStatus, DocumentFacets } from "@/lib/types";
import { useNotifications } from "@/components/notifications";

const EMPTY_DOCUMENT_FACETS: DocumentFacets = {
  registries: [],
  issuers: [],
  years: [],
  languages: [],
  forms: [],
  parse_statuses: [],
  embedding_statuses: [],
  snapshots: [],
};

type DocumentGroup = "none" | "registry" | "issuer" | "fiscal_year";

interface DocumentInventoryProps {
  live: boolean;
  /** Initial inventory supplied by the enclosing workspace. */
  fallbackDocuments: AdminDocument[];
  onOpenPipeline?: (stage?: string) => void;
  onOpenJobs?: () => void;
}

export function DocumentInventory({ live, fallbackDocuments, onOpenPipeline, onOpenJobs }: DocumentInventoryProps) {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [documents, setDocuments] = useState<AdminDocument[]>(fallbackDocuments);
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentRegistry, setDocumentRegistry] = useState("all");
  const [documentIssuer, setDocumentIssuer] = useState("all");
  const [documentYear, setDocumentYear] = useState("all");
  const [documentLanguage, setDocumentLanguage] = useState("all");
  const [documentForm, setDocumentForm] = useState("all");
  const [documentParseStatus, setDocumentParseStatus] = useState("all");
  const [documentEmbeddingStatus, setDocumentEmbeddingStatus] = useState<"all" | DocumentEmbeddingStatus>("all");
  const [documentSnapshot, setDocumentSnapshot] = useState("all");
  const [documentSort, setDocumentSort] = useState("doc_id");
  const [documentDescending, setDocumentDescending] = useState(false);
  const [documentGroup, setDocumentGroup] = useState<DocumentGroup>("none");
  const [documentDetail, setDocumentDetail] = useState<DocumentDetail | null>(null);
  const [documentFacets, setDocumentFacets] = useState<DocumentFacets>(EMPTY_DOCUMENT_FACETS);
  const [documentTotal, setDocumentTotal] = useState(0);
  const [documentNextCursor, setDocumentNextCursor] = useState<string | null>(null);

  const [facetError, setFacetError] = useState<string | null>(null);
  const [facetRefresh, setFacetRefresh] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [detailRefresh, setDetailRefresh] = useState(0);
  const requestGeneration = useRef(0);
  const layout = useMasterDetail({ storageKey: "docreview:layout:documents" });
  const queryKey = useMemo(() => {
    const params = new URLSearchParams({ query: documentQuery, sort: documentSort, descending: String(documentDescending), limit: "50" });
    for (const [key, value] of [
      ["registry", documentRegistry], ["issuer", documentIssuer], ["fiscal_year", documentYear],
      ["language", documentLanguage], ["form", documentForm], ["parse_status", documentParseStatus],
      ["embedding_status", documentEmbeddingStatus], ["snapshot_id", documentSnapshot],
    ]) if (value !== "all") params.set(key, value);
    return params.toString();
  }, [documentQuery, documentRegistry, documentIssuer, documentYear, documentLanguage, documentForm, documentParseStatus, documentEmbeddingStatus, documentSnapshot, documentSort, documentDescending]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    setLoading(true);
    setLoadingMore(false);
    setListError(null);
    setDocumentNextCursor(null);
    const timer = window.setTimeout(() => {
      const getPage = live ? getAdminDocuments : getPublishedDocuments;
      void getPage(new URLSearchParams(queryKey)).then((page) => {
        if (generation !== requestGeneration.current) return;
        setDocuments(page.documents);
        setDocumentTotal(page.total);
        setDocumentNextCursor(page.next_cursor);
      }).catch((reason) => {
        if (generation !== requestGeneration.current) return;
        setDocuments([]);
        setDocumentTotal(0);
        setListError(String(reason));
      }).finally(() => {
        if (generation === requestGeneration.current) setLoading(false);
      });
    }, 200);
    return () => { window.clearTimeout(timer); ++requestGeneration.current; };
  }, [live, queryKey, refresh]);

  useEffect(() => {
    let current = true;
    setDocumentFacets(EMPTY_DOCUMENT_FACETS);
    setFacetError(null);
    void (live ? getDocumentFacets : getPublishedDocumentFacets)().then((facets) => {
      if (!isDocumentFacets(facets)) throw new Error("Invalid document filter response");
      if (current) setDocumentFacets(facets);
    }).catch((reason) => {
      if (current) { setFacetError(String(reason)); notify(String(reason), "error", "document-facets"); }
    });
    return () => { current = false; };
  }, [live, notify, facetRefresh]);

  useEffect(() => {
    let current = true;
    setDocumentDetail(null);
    setDetailError(null);
    if (!selectedId) return;
    setDetailLoading(true);
    void (live ? getDocumentDetail : getPublishedDocumentDetail)(selectedId).then((detail) => {
      if (current) setDocumentDetail(detail);
    }).catch((reason) => { if (current) setDetailError(String(reason)); }).finally(() => {
      if (current) setDetailLoading(false);
    });
    return () => { current = false; };
  }, [selectedId, live, detailRefresh]);

  async function loadMoreDocuments() {
    if (!documentNextCursor || loadingMore || loading) return;
    const generation = requestGeneration.current;
    const params = new URLSearchParams(queryKey);
    params.set("cursor", documentNextCursor);
    setLoadingMore(true);
    setListError(null);
    try {
      const page = await (live ? getAdminDocuments : getPublishedDocuments)(params);
      if (generation !== requestGeneration.current) return;
      setDocuments((current) => {
        const ids = new Set(current.map((document) => document.doc_id));
        return [...current, ...page.documents.filter((document) => !ids.has(document.doc_id))];
      });
      setDocumentNextCursor(page.next_cursor);
    } catch (reason) {
      if (generation === requestGeneration.current) setListError(String(reason));
    } finally {
      if (generation === requestGeneration.current) setLoadingMore(false);
    }
  }

  function selectDocument(docId: string) {
    if (docId !== selectedId) {
      setDocumentDetail(null);
      setDetailError(null);
      setDetailLoading(true);
      setSelectedId(docId);
    }
    layout.openDetail();
  }

  function resetDocumentFilters() {
    setDocumentQuery("");
    setDocumentRegistry("all");
    setDocumentIssuer("all");
    setDocumentYear("all");
    setDocumentLanguage("all");
    setDocumentForm("all");
    setDocumentParseStatus("all");
    setDocumentEmbeddingStatus("all");
    setDocumentSnapshot("all");
    setDocumentSort("doc_id");
    setDocumentDescending(false);
    setDocumentGroup("none");
  }

  const visibleDocuments = loading ? [] : documents;
  const documentGroups = groupDocuments(visibleDocuments, documentGroup, t);
  const selectedExcluded = selectedId !== null && !loading && !listError && !documents.some((document) => document.doc_id === selectedId);
  const showDetail = selectedId !== null && layout.detailOpen;
  const compact = showDetail && !layout.narrow;
  const activeFilters = [
    { label: t("Search"), value: documentQuery, remove: () => setDocumentQuery("") },
    { label: t("Company"), value: documentIssuer, displayValue: documentFacets.issuers.find((facet) => facet.value === documentIssuer)?.label ?? companyLabel(documentIssuer, documents.find((document) => document.issuer === documentIssuer)?.issuer_name), remove: () => setDocumentIssuer("all") },
    { label: t("Fiscal year"), value: documentYear, remove: () => setDocumentYear("all") },
    { label: t("Registry"), value: documentRegistry, remove: () => setDocumentRegistry("all") },
    { label: t("Language"), value: documentLanguage, remove: () => setDocumentLanguage("all") },
    { label: t("Form"), value: documentForm, remove: () => setDocumentForm("all") },
    { label: t("Parse status"), value: documentParseStatus, remove: () => setDocumentParseStatus("all") },
    { label: t("Embedding"), value: documentEmbeddingStatus, remove: () => setDocumentEmbeddingStatus("all") },
    { label: t("Snapshot membership"), value: documentSnapshot, remove: () => setDocumentSnapshot("all") },
  ].filter(({ value }) => value !== "all" && value !== "");

  return <div ref={layout.workspaceRef} style={layout.splitStyle} className={`document-workspace ${styles.workspace} ${compact ? styles.split : ""}`} data-detail-open={showDetail}>
    <section id={layout.listPanelId} data-help="build.documents.list" className={`surface document-inventory ${styles.listPanel} ${compact ? styles.compact : ""}`} hidden={showDetail && layout.narrow}>
      <div className={styles.heading}>
        <div><h2>{t("Document inventory")}</h2><p className="helper">{t("Showing {shown} of {total} filings", { shown: visibleDocuments.length.toLocaleString(locale), total: documentTotal.toLocaleString(locale) })}</p></div>
        {activeFilters.length > 0 && <button className="button ghost" type="button" onClick={resetDocumentFilters}>{t("Reset filters")}</button>}
      </div>
      <div className={styles.toolbar} data-help="build.documents.filters">
        <label>{t("Search")}<input aria-label={t("Search documents")} placeholder={t("Document, issuer, or stock code")} value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} /></label>
        <FacetSelect label={t("Company")} value={documentIssuer} allLabel="All companies" facets={documentFacets.issuers} onChange={setDocumentIssuer} />
        <FacetSelect label={t("Fiscal year")} value={documentYear} allLabel="All years" facets={documentFacets.years} onChange={setDocumentYear} />
        <button className="button" type="button" aria-expanded={filtersOpen} aria-controls="document-advanced-filters" onClick={() => setFiltersOpen(!filtersOpen)}><SlidersHorizontal size={15} />{t("Filters")}{activeFilters.length > 0 ? ` · ${activeFilters.length}` : ""}</button>
      </div>
      {activeFilters.length > 0 && <div className={styles.chips} aria-label={t("Applied filters")}>{activeFilters.map((filter) => <button type="button" key={filter.label} aria-label={t("Remove filter: {label}", { label: filter.label })} onClick={filter.remove}>{filter.label}: {t(filter.displayValue ?? filter.value)}<X size={12} /></button>)}</div>}
      {facetError && <div className={styles.error} role="alert"><p>{t("Could not load document filters.")}</p><p>{facetError}</p><button className="button" type="button" onClick={() => setFacetRefresh((value) => value + 1)}>{t("Retry filters")}</button></div>}
      {filtersOpen && <div id="document-advanced-filters" className={styles.advanced}>
        <FacetSelect label={t("Registry")} value={documentRegistry} allLabel="All registries" facets={documentFacets.registries} onChange={setDocumentRegistry} />
        <FacetSelect label={t("Language")} value={documentLanguage} allLabel="All languages" facets={documentFacets.languages} onChange={setDocumentLanguage} />
        <FacetSelect label={t("Form")} value={documentForm} allLabel="All forms" facets={documentFacets.forms} onChange={setDocumentForm} />
        <FacetSelect label={t("Parse status")} value={documentParseStatus} translateValues allLabel="All parse states" facets={documentFacets.parse_statuses} onChange={setDocumentParseStatus} />
        <FacetSelect label={t("Embedding")} value={documentEmbeddingStatus} translateValues allLabel="All embedding states" facets={documentFacets.embedding_statuses} onChange={(value) => setDocumentEmbeddingStatus(value as "all" | DocumentEmbeddingStatus)} />
        <FacetSelect label={t("Snapshot membership")} value={documentSnapshot} allLabel="All snapshots" facets={documentFacets.snapshots} onChange={setDocumentSnapshot} />
        <label>{t("Group by")}<select aria-label={t("Group documents")} value={documentGroup} onChange={(event) => setDocumentGroup(event.target.value as DocumentGroup)}><option value="none">{t("No grouping")}</option><option value="registry">{t("Registry")}</option><option value="issuer">{t("Company")}</option><option value="fiscal_year">{t("Fiscal year")}</option></select></label>
        <label>{t("Sort by")}<select aria-label={t("Sort documents")} value={documentSort} onChange={(event) => setDocumentSort(event.target.value)}><option value="doc_id">{t("Document")}</option><option value="issuer">{t("Issuer")}</option><option value="fiscal_year">{t("Year")}</option><option value="filing_date">{t("Filing date")}</option><option value="chunk_count">{t("Chunks")}</option><option value="embedding_coverage">{t("Embedding coverage")}</option></select></label>
        <label>{t("Direction")}<select aria-label={t("Sort direction")} value={documentDescending ? "descending" : "ascending"} onChange={(event) => setDocumentDescending(event.target.value === "descending")}><option value="ascending">{t("Ascending")}</option><option value="descending">{t("Descending")}</option></select></label>
      </div>}
      <div ref={layout.listRef} className={styles.list} aria-busy={loading || loadingMore}>
        {loading ? <p className={styles.status} role="status">{t("Loading documents…")}</p> : <div role="table" aria-label={t("Document inventory")}>
          <div className={styles.columnLabels} role="row"><span role="columnheader">{t("Document")}</span><span role="columnheader">{t("Company / year")}</span><span role="columnheader">{t("Readiness")}</span><span role="columnheader">{t("Chunks")}</span></div>
          {documentGroups.map(([groupLabel, rows]) => <div role="rowgroup" key={groupLabel || "all"}>
            {groupLabel && <div className={styles.group}>{groupLabel}<span>{t("{count} filings", { count: rows.length.toLocaleString(locale) })}</span></div>}
            {rows.map((document) => {
              const chunks = document.chunk_count ?? 0;
              const coverage = chunks > 0 ? Math.round((document.embedded_chunks ?? 0) / chunks * 100) : 0;
              return <div key={document.doc_id} role="row" aria-selected={selectedId === document.doc_id} className={styles.documentRow} onClick={() => selectDocument(document.doc_id)}>
                <div role="cell"><button className={styles.title} type="button" onClick={(event) => { event.stopPropagation(); selectDocument(document.doc_id); }}>{document.doc_id}</button><small>{document.registry.toUpperCase()} · {document.form}</small></div>
                <div role="cell"><span>{companyLabel(document.issuer, document.issuer_name)}</span><small>{t("FY {year}", { year: document.fiscal_year })}</small></div>
                <div role="cell"><span className={`coverage-badge ${document.embedding_status ?? "missing"}`}>{t(document.embedding_status === "complete" && chunks > 0 ? "Embedded" : document.parse_status)}</span><small>{t("{coverage}% embedded", { coverage })}</small></div>
                <span role="cell" className={styles.count}>{chunks.toLocaleString(locale)}</span>
              </div>;
            })}
          </div>)}
        </div>}
        {!loading && !visibleDocuments.length && !listError && <p className={styles.status}>{t("No documents match these filters.")}</p>}
        {listError && <div className={styles.error} role="alert"><p>{t("Could not load documents.")}</p><p>{listError}</p><button className="button" type="button" onClick={() => documentNextCursor ? void loadMoreDocuments() : setRefresh((value) => value + 1)}>{t("Retry")}</button></div>}
        {documentNextCursor && !listError && <button className="button document-load-more" type="button" disabled={loadingMore} onClick={() => void loadMoreDocuments()}>{t(loadingMore ? "Loading documents…" : "Load next 50")}</button>}
      </div>
    </section>
    {compact && <MasterDetailDivider label={t("Resize document panels")} controls={layout.listPanelId} resize={layout.resize} />}
    {showDetail && <div className={styles.detailWrap} data-help="build.documents.detail">
      <button className="button ghost" type="button" onClick={layout.closeDetail}><ArrowLeft size={15} />{t("Back to documents")}</button>
      {selectedExcluded ? <section className="surface" role="status"><h2>{t("Document outside current filters")}</h2><p className="helper">{t("The selected document is not in these results. Clear filters or choose another document.")}</p><button className="button" type="button" onClick={() => { resetDocumentFilters(); layout.closeDetail(); }}>{t("Reset filters")}</button></section>
        : detailLoading ? <section className="surface" role="status">{t("Loading document details…")}</section>
        : detailError ? <section className="surface" role="alert"><h2>{t("Could not load document details.")}</h2><p className="helper">{detailError}</p><button className="button" type="button" onClick={() => setDetailRefresh((value) => value + 1)}>{t("Retry")}</button></section>
        : documentDetail && <DocumentDetailPanel detail={documentDetail} onOpenPipeline={live ? onOpenPipeline : undefined} onOpenJobs={live ? onOpenJobs : undefined} />}
    </div>}
  </div>;
}

/** Reject incompatible facet responses explicitly instead of crashing a mounted workspace. */
function isDocumentFacets(value: unknown): value is DocumentFacets {
  if (value === null || typeof value !== "object") return false;
  return Object.keys(EMPTY_DOCUMENT_FACETS).every((key) => {
    const entries = (value as Record<string, unknown>)[key];
    return Array.isArray(entries) && entries.every((entry) => entry !== null && typeof entry === "object" && typeof entry.value === "string" && typeof entry.count === "number");
  });
}

function FacetSelect({ label, value, allLabel, facets, onChange, translateValues = false }: { translateValues?: boolean; label: string; value: string; allLabel: string; facets: DocumentFacets["registries"]; onChange: (value: string) => void }) {
  const { t, locale } = useI18n();
  return <label>{t(label)}<select aria-label={t("Filter {p0}", { p0: label.toLowerCase() })} value={value} onChange={(event) => onChange(event.target.value)}><option value="all">{t(allLabel)}</option>{facets.map((facet) => <option key={facet.value} value={facet.value}>{translateValues ? t(facet.label ?? facet.value) : facet.label ?? facet.value} ({facet.count.toLocaleString(locale)})</option>)}</select></label>;
}

function groupDocuments(documents: AdminDocument[], group: DocumentGroup, labelFor: (key: string) => string): Array<[string, AdminDocument[]]> {
  if (group === "none") return [["", documents]];
  const grouped = new Map<string, AdminDocument[]>();
  for (const document of documents) {
    const value = String(document[group]);
    grouped.set(value, [...(grouped.get(value) ?? []), document]);
  }
  return [...grouped.entries()].map(([value, rows]): [string, AdminDocument[]] => {
    const label = group === "registry"
      ? `${labelFor("Registry")} · ${value.toUpperCase()}`
      : group === "issuer"
      ? `${labelFor("Company")} · ${companyLabel(value, rows.find((document) => document.issuer_name?.trim())?.issuer_name)}`
      : `${labelFor("Fiscal year")} · ${value}`;
    return [label, rows];
  }).toSorted(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }));
}

/** Format calendar dates in UTC so the filing day stays unchanged across time zones. */
function formatFilingDate(value: string | null | undefined, locale: string): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { timeZone: "UTC" }).format(date);
}

function formatBytes(value: number, locale: string): string {
  if (value < 1_000) return `${value.toLocaleString(locale)} B`;
  if (value < 1_000_000) return `${(value / 1_000).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} KB`;
  return `${(value / 1_000_000).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} MB`;
}

function DocumentDetailPanel({ detail, onOpenPipeline, onOpenJobs }: { detail: DocumentDetail; onOpenPipeline?: (stage?: string) => void; onOpenJobs?: () => void }) {
  const { t, locale } = useI18n();
  const { document } = detail;
  const company = document.issuer_name?.trim() || document.issuer || document.doc_id;
  const missing = Math.max(document.chunk_count - detail.embedded_chunks, 0);
  const coverage = document.chunk_count > 0 ? Math.round(detail.embedded_chunks / document.chunk_count * 100) : 0;
  return <section className="surface document-detail">
    <header className="document-detail-heading"><div className="document-identity"><p className="eyebrow">{document.registry.toUpperCase()} · {document.language.toUpperCase()}</p><div className="document-company-line"><h2 className="document-company">{company}</h2><span className="document-fiscal-year" aria-label={`${t("Fiscal year")}: ${document.fiscal_year}`}>{t("FY {year}", { year: document.fiscal_year })}</span></div><p className="document-identifier"><code>{document.doc_id}</code><span>{document.issuer} · {document.form}</span></p></div><span className={`coverage-badge ${document.chunk_count > 0 && missing === 0 ? "complete" : detail.embedded_chunks > 0 ? "partial" : "missing"}`}>{t("{coverage}% embedded", { coverage })}</span></header>
    <section className="document-detail-section"><h3>{t("Original filing")}</h3><dl className="document-meta-grid"><div><dt>{t("Issuer identity")}</dt><dd>{document.issuer_id}</dd></div><div><dt>{t("Filing identity")}</dt><dd>{document.filing_id}</dd></div><div><dt>{t("Filed")}</dt><dd>{formatFilingDate(document.filing_date, locale)}</dd></div><div><dt>{t("Report period")}</dt><dd>{formatFilingDate(document.report_period, locale)}</dd></div><div><dt>{t("Source size")}</dt><dd>{formatBytes(document.source_length, locale)}</dd></div><div><dt>{t("Parse status")}</dt><dd>{t(document.parse_status)}</dd></div><div className="wide"><dt>{t("Source")}</dt><dd>{/^https?:\/\//i.test(document.source_url) ? <a href={document.source_url} target="_blank" rel="noreferrer">{t("Open original filing")}</a> : "—"}</dd></div><div className="wide"><dt>{t("Source SHA-256")}</dt><dd><code>{document.source_sha256}</code></dd></div></dl></section>
    <section className="document-detail-section"><h3>{t("Chunks & search readiness")}</h3><div className="document-stat-grid"><div><span>{t("Total chunks")}</span><strong>{document.chunk_count.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}</strong></div><div><span>{t("Text / table")}</span><strong>{detail.text_chunks.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")} / {detail.table_chunks.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}</strong></div><div><span>{t("Embedded")}</span><strong>{detail.embedded_chunks.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}</strong></div><div><span>{t("Missing vectors")}</span><strong className={missing > 0 ? "negative" : "positive"}>{missing.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}</strong></div></div></section>
    <section className="document-detail-section"><h3>{t("Section distribution")}</h3>{detail.item_counts.length ? <div className="document-section-list">{detail.item_counts.map((item) => <div key={item.item}><span>{item.item}</span><strong>{item.count.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}</strong><progress max={document.chunk_count || 1} value={item.count} /></div>)}</div> : <p className="helper">{t("No section identities were recorded.")}</p>}</section>
    <section className="document-detail-section"><h3>{t("Embedding identities")}</h3>{detail.embedding_identities.length ? <div className="embedding-list">{detail.embedding_identities.map((identity) => <article key={`${identity.provider}:${identity.model}:${identity.dimensions}`}><strong>{identity.provider} · {identity.model}</strong><p>{t("{dimensions} dimensions · {count} chunks", { dimensions: identity.dimensions.toLocaleString(locale), count: identity.count.toLocaleString(locale) })}</p></article>)}</div> : <p className="helper">{t("No persisted embedding identity is available.")}</p>}</section>
    <section className="document-detail-section"><h3>{t("Index revisions & snapshot membership")}</h3>{detail.snapshot_memberships.length ? <div className="snapshot-memberships">{detail.snapshot_memberships.map((snapshot) => <article key={snapshot.snapshot_id}><div><strong>{t("Revision #")}{snapshot.snapshot_id} · {snapshot.label}</strong><p>{t(snapshot.status)} · {snapshot.public ? t("published") : t("private")} · {new Date(snapshot.created_at).toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}</p></div></article>)}</div> : <p className="helper">{t("This filing is not frozen in an evaluation snapshot yet.")}</p>}</section>
    {(onOpenPipeline || onOpenJobs) && <section className={`document-detail-section ${styles.next}`}><h3>{t("Related work & next step")}</h3><p>{t(document.chunk_count === 0 ? "Parse this filing to prepare searchable chunks." : missing > 0 ? "Some chunks need embeddings before semantic search is ready." : "All chunks have embeddings. Review index readiness in the pipeline.")}</p><div className="action-row">{onOpenPipeline && <button className="button" type="button" onClick={() => onOpenPipeline(document.chunk_count === 0 ? "index" : missing > 0 ? "embeddings" : "lexical")}>{t("Next step")}</button>}{onOpenJobs && <button className="button" type="button" onClick={onOpenJobs}>{t("Open Jobs")}</button>}</div></section>}
    <section className="document-detail-section"><h3>{t("Source-cited chunk previews")}</h3><div className="chunk-preview-list">{detail.chunks.map((chunk) => <article key={chunk.chunk_id}><header><strong>{t("Chunk {id} · ordinal {ordinal}", { id: chunk.chunk_id, ordinal: chunk.ordinal })}</strong><span>{chunk.span}</span></header><p className="chunk-citation">{chunk.citation}</p><p>{chunk.body}</p><code>{chunk.source_sha256}</code></article>)}</div></section>
  </section>;
}
