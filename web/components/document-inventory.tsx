"use client";

import { useEffect, useState } from "react";

import { getAdminDocuments, getDocumentDetail, getDocumentFacets } from "@/lib/api";
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
  /** Documents shown until the live inventory loads, and the whole list in read-only mode. */
  fallbackDocuments: AdminDocument[];
}

export function DocumentInventory({ live, fallbackDocuments }: DocumentInventoryProps) {
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

  useEffect(() => {
    if (!live) setDocuments(fallbackDocuments);
  }, [live, fallbackDocuments]);
  useEffect(() => {
    if (!live) return;
    const timer = window.setTimeout(() => {
      const params = documentParams();
      void getAdminDocuments(params).then((page) => {
        setDocuments(page.documents);
        setDocumentTotal(page.total);
        setDocumentNextCursor(page.next_cursor);
      }).catch((reason) => notify(String(reason), "error", "documents"));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [live, documentQuery, documentRegistry, documentIssuer, documentYear, documentLanguage, documentForm, documentParseStatus, documentEmbeddingStatus, documentSnapshot, documentSort, documentDescending, notify]);
  useEffect(() => {
    if (live) void getDocumentFacets().then(setDocumentFacets).catch((reason) => notify(String(reason), "error", "document-facets"));
  }, [live, notify]);

  function documentParams(cursor?: string) {
    const params = new URLSearchParams({
      query: documentQuery,
      sort: documentSort,
      descending: String(documentDescending),
      limit: "50",
    });
    for (const [key, value] of [
      ["registry", documentRegistry],
      ["issuer", documentIssuer],
      ["fiscal_year", documentYear],
      ["language", documentLanguage],
      ["form", documentForm],
      ["parse_status", documentParseStatus],
      ["embedding_status", documentEmbeddingStatus],
      ["snapshot_id", documentSnapshot],
    ]) {
      if (value !== "all") params.set(key, value);
    }
    if (cursor) params.set("cursor", cursor);
    return params;
  }

  async function loadMoreDocuments() {
    if (!documentNextCursor) return;
    const params = documentParams(documentNextCursor);
    try {
      const page = await getAdminDocuments(params);
      setDocuments((current) => [...current, ...page.documents]);
      setDocumentNextCursor(page.next_cursor);
    } catch (reason) {
      notify(String(reason), "error", "documents-more");
    }
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

  const visibleDocuments = live ? documents : documents.filter((document) => (documentRegistry === "all" || document.registry === documentRegistry) && `${document.doc_id} ${document.issuer}`.toLowerCase().includes(documentQuery.toLowerCase())).toSorted((left, right) => String(left[documentSort as keyof AdminDocument] ?? "").localeCompare(String(right[documentSort as keyof AdminDocument] ?? ""), undefined, { numeric: true }));
  const documentGroups = groupDocuments(visibleDocuments, documentGroup);

  return <div className="document-workspace">
    <section className="surface document-inventory">
      <div className="document-inventory-heading">
        <div><h2>Document inventory</h2><p className="helper">Showing {visibleDocuments.length.toLocaleString()} of {(live ? documentTotal : visibleDocuments.length).toLocaleString()} filings</p></div>
        <button className="button ghost" type="button" onClick={resetDocumentFilters}>Reset filters</button>
      </div>
      <div className="document-filters">
        <label className="document-search">Search<input aria-label="Search documents" placeholder="Document, issuer, or stock code" value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} /></label>
        <FacetSelect label="Registry" value={documentRegistry} allLabel="All registries" facets={documentFacets.registries} onChange={setDocumentRegistry} />
        <FacetSelect label="Company" value={documentIssuer} allLabel="All companies" facets={documentFacets.issuers} onChange={setDocumentIssuer} />
        <FacetSelect label="Fiscal year" value={documentYear} allLabel="All years" facets={documentFacets.years} onChange={setDocumentYear} />
        <FacetSelect label="Language" value={documentLanguage} allLabel="All languages" facets={documentFacets.languages} onChange={setDocumentLanguage} />
        <FacetSelect label="Form" value={documentForm} allLabel="All forms" facets={documentFacets.forms} onChange={setDocumentForm} />
        <FacetSelect label="Parse status" value={documentParseStatus} allLabel="All parse states" facets={documentFacets.parse_statuses} onChange={setDocumentParseStatus} />
        <FacetSelect label="Embedding" value={documentEmbeddingStatus} allLabel="All embedding states" facets={documentFacets.embedding_statuses} onChange={(value) => setDocumentEmbeddingStatus(value as "all" | DocumentEmbeddingStatus)} />
        <FacetSelect label="Snapshot membership" value={documentSnapshot} allLabel="All snapshots" facets={documentFacets.snapshots} onChange={setDocumentSnapshot} />
        <label>Group by<select aria-label="Group documents" value={documentGroup} onChange={(event) => setDocumentGroup(event.target.value as DocumentGroup)}><option value="none">No grouping</option><option value="registry">Registry</option><option value="issuer">Company</option><option value="fiscal_year">Fiscal year</option></select></label>
        <label>Sort by<select aria-label="Sort documents" value={documentSort} onChange={(event) => setDocumentSort(event.target.value)}><option value="doc_id">Document</option><option value="issuer">Issuer</option><option value="fiscal_year">Year</option><option value="filing_date">Filing date</option><option value="chunk_count">Chunks</option><option value="embedding_coverage">Embedding coverage</option></select></label>
        <label>Direction<select aria-label="Sort direction" value={documentDescending ? "descending" : "ascending"} onChange={(event) => setDocumentDescending(event.target.value === "descending")}><option value="ascending">Ascending</option><option value="descending">Descending</option></select></label>
      </div>
      <div className="document-table-scroll"><table><thead><tr><th>Document</th><th>Registry</th><th>Issuer</th><th>Year</th><th>Filed</th><th>Form</th><th>Language</th><th>Chunks</th><th>Embedding</th><th>Snapshots</th><th>Status</th></tr></thead>{documentGroups.map(([groupLabel, rows]) => <tbody key={groupLabel || "all"}>{groupLabel && <tr className="document-group-row"><th colSpan={11}>{groupLabel}<span>{rows.length} filings</span></th></tr>}{rows.map((document) => { const embedded = document.embedded_chunks ?? 0; const chunks = document.chunk_count ?? 0; const coverage = chunks > 0 ? Math.round(embedded / chunks * 100) : 0; return <tr key={document.doc_id} className={documentDetail?.document.doc_id === document.doc_id ? "selected" : ""}><td><button className="row-detail" type="button" disabled={!live} onClick={() => live && void getDocumentDetail(document.doc_id).then(setDocumentDetail).catch((reason) => notify(String(reason), "error", "document-detail"))}>{document.doc_id}</button></td><td>{document.registry.toUpperCase()}</td><td>{document.issuer}</td><td>{document.fiscal_year}</td><td>{document.filing_date || "—"}</td><td>{document.form || "—"}</td><td>{document.language}</td><td>{chunks.toLocaleString()}</td><td><span className={`coverage-badge ${document.embedding_status ?? "missing"}`}>{coverage}%</span><small>{embedded.toLocaleString()}/{chunks.toLocaleString()}</small></td><td>{(document.snapshot_count ?? 0).toLocaleString()}</td><td>{document.parse_status}</td></tr>; })}</tbody>)}</table></div>
      {!visibleDocuments.length && <p className="helper document-empty">No documents match these filters.</p>}
      {documentNextCursor && <button className="button document-load-more" type="button" onClick={() => void loadMoreDocuments()}>Load next 50</button>}
    </section>
    <DocumentDetailPanel detail={documentDetail} />
  </div>;
}

function FacetSelect({ label, value, allLabel, facets, onChange }: { label: string; value: string; allLabel: string; facets: DocumentFacets["registries"]; onChange: (value: string) => void }) {
  return <label>{label}<select aria-label={`Filter ${label.toLowerCase()}`} value={value} onChange={(event) => onChange(event.target.value)}><option value="all">{allLabel}</option>{facets.map((facet) => <option key={facet.value} value={facet.value}>{facet.label ?? facet.value} ({facet.count})</option>)}</select></label>;
}

function groupDocuments(documents: AdminDocument[], group: DocumentGroup): Array<[string, AdminDocument[]]> {
  if (group === "none") return [["", documents]];
  const grouped = new Map<string, AdminDocument[]>();
  for (const document of documents) {
    const value = String(document[group]);
    const label = group === "registry"
      ? `Registry · ${value.toUpperCase()}`
      : group === "issuer"
      ? `Company · ${value}`
      : `Fiscal year · ${value}`;
    grouped.set(label, [...(grouped.get(label) ?? []), document]);
  }
  return [...grouped.entries()].toSorted(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }));
}

function formatBytes(value: number): string {
  if (value < 1_000) return `${value} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(1)} KB`;
  return `${(value / 1_000_000).toFixed(1)} MB`;
}

function DocumentDetailPanel({ detail }: { detail: DocumentDetail | null }) {
  if (!detail) return <section className="surface document-detail"><h2>Document details</h2><p className="helper">Select a document to inspect filing identity, section distribution, embedding coverage, snapshot revisions, and source-cited chunks.</p></section>;
  const { document } = detail;
  const missing = Math.max(document.chunk_count - detail.embedded_chunks, 0);
  const coverage = document.chunk_count > 0 ? Math.round(detail.embedded_chunks / document.chunk_count * 100) : 0;
  return <section className="surface document-detail">
    <header className="document-detail-heading"><div><p className="eyebrow">{document.registry.toUpperCase()} · {document.language.toUpperCase()}</p><h2>{document.doc_id}</h2><p>{document.issuer} · FY{document.fiscal_year} · {document.form}</p></div><span className={`coverage-badge ${missing === 0 ? "complete" : detail.embedded_chunks > 0 ? "partial" : "missing"}`}>{coverage}% embedded</span></header>
    <section className="document-detail-section"><h3>Filing identity</h3><dl className="document-meta-grid"><div><dt>Issuer identity</dt><dd>{document.issuer_id}</dd></div><div><dt>Filing identity</dt><dd>{document.filing_id}</dd></div><div><dt>Filed</dt><dd>{document.filing_date}</dd></div><div><dt>Report period</dt><dd>{document.report_period}</dd></div><div><dt>Source size</dt><dd>{formatBytes(document.source_length)}</dd></div><div><dt>Parse status</dt><dd>{document.parse_status}</dd></div><div className="wide"><dt>Source</dt><dd><a href={document.source_url} target="_blank" rel="noreferrer">{document.source_url}</a></dd></div><div className="wide"><dt>Source SHA-256</dt><dd><code>{document.source_sha256}</code></dd></div></dl></section>
    <section className="document-detail-section"><h3>Chunk & index coverage</h3><div className="document-stat-grid"><div><span>Total chunks</span><strong>{document.chunk_count.toLocaleString()}</strong></div><div><span>Text / table</span><strong>{detail.text_chunks.toLocaleString()} / {detail.table_chunks.toLocaleString()}</strong></div><div><span>Embedded</span><strong>{detail.embedded_chunks.toLocaleString()}</strong></div><div><span>Missing vectors</span><strong className={missing > 0 ? "negative" : "positive"}>{missing.toLocaleString()}</strong></div></div></section>
    <section className="document-detail-section"><h3>Section distribution</h3>{detail.item_counts.length ? <div className="document-section-list">{detail.item_counts.map((item) => <div key={item.item}><span>{item.item}</span><strong>{item.count.toLocaleString()}</strong><progress max={document.chunk_count || 1} value={item.count} /></div>)}</div> : <p className="helper">No section identities were recorded.</p>}</section>
    <section className="document-detail-section"><h3>Embedding identities</h3>{detail.embedding_identities.length ? <div className="embedding-list">{detail.embedding_identities.map((identity) => <article key={`${identity.provider}:${identity.model}:${identity.dimensions}`}><strong>{identity.provider} · {identity.model}</strong><p>{identity.dimensions} dimensions · {identity.count.toLocaleString()} chunks</p></article>)}</div> : <p className="helper">No persisted embedding identity is available.</p>}</section>
    <section className="document-detail-section"><h3>Index revisions & snapshot membership</h3>{detail.snapshot_memberships.length ? <div className="snapshot-memberships">{detail.snapshot_memberships.map((snapshot) => <article key={snapshot.snapshot_id}><div><strong>Revision #{snapshot.snapshot_id} · {snapshot.label}</strong><p>{snapshot.status} · {snapshot.public ? "published" : "private"} · {new Date(snapshot.created_at).toLocaleString()}</p></div></article>)}</div> : <p className="helper">This filing is not frozen in an evaluation snapshot yet.</p>}</section>
    <section className="document-detail-section"><h3>Source-cited chunk previews</h3><div className="chunk-preview-list">{detail.chunks.map((chunk) => <article key={chunk.chunk_id}><header><strong>Chunk {chunk.chunk_id} · ordinal {chunk.ordinal}</strong><span>{chunk.span}</span></header><p className="chunk-citation">{chunk.citation}</p><p>{chunk.body}</p><code>{chunk.source_sha256}</code></article>)}</div></section>
  </section>;
}
