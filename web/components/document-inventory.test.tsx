import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminDocument, AdminDocumentPage, DocumentDetail } from "@/lib/types";
import { DocumentInventory } from "./document-inventory";
import { I18nProvider } from "@/lib/i18n";

const api = vi.hoisted(() => ({
  getAdminDocuments: vi.fn(), getDocumentDetail: vi.fn(), getDocumentFacets: vi.fn(),
  getPublishedDocuments: vi.fn(), getPublishedDocumentDetail: vi.fn(), getPublishedDocumentFacets: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

/** Supply an independently identifiable filing for selection and stale-response checks. */
function filing(docId: string): AdminDocument {
  return {
    doc_id: docId, registry: "sec", language: "en", issuer: "NVDA", issuer_name: `Issuer ${docId}`, issuer_id: docId,
    fiscal_year: 2024, form: "10-K", filing_date: "2026-01-01", report_period: "2025-12-31", filing_id: docId,
    source_url: `https://example.com/${docId}`, parse_status: "parsed", source_length: 1000, source_sha256: "abc",
    chunk_count: 4, embedded_chunks: 4, text_chunks: 3, table_chunks: 1, embedding_status: "complete", snapshot_count: 1,
  };
}

/** Keep the detail body unique so a late response cannot pass as the current filing. */
function detail(docId: string): DocumentDetail {
  return {
    document: filing(docId), chunks: [], text_chunks: 3, table_chunks: 1, embedded_chunks: 4,
    item_counts: [], embedding_identities: [], snapshot_memberships: [],
  };
}

/** Allow a test to resolve requests in a different order from their initiation. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const facets = { registries: [{ value: "sec", label: "SEC", count: 2 }], issuers: [], years: [], languages: [], forms: [], sections: [], parse_statuses: [], embedding_statuses: [], snapshots: [] };
const page = (ids: string[], cursor: string | null = null): AdminDocumentPage => ({ documents: ids.map(filing), total: ids.length, next_cursor: cursor });

beforeEach(() => {
  vi.clearAllMocks();
  api.getAdminDocuments.mockResolvedValue(page(["doc-a", "doc-b"]));
  api.getPublishedDocuments.mockResolvedValue(page(["doc-a"]));
  api.getDocumentFacets.mockResolvedValue(facets);
  api.getPublishedDocumentFacets.mockResolvedValue(facets);
  api.getDocumentDetail.mockImplementation(async (id: string) => detail(id));
  api.getPublishedDocumentDetail.mockImplementation(async (id: string) => detail(id));
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("DocumentInventory", () => {
  it.each([true, false])("localizes Korean companies across detail, rows, facets and groups without changing filters (live=%s)", async (live) => {
    localStorage.clear(); localStorage.setItem("docreview.locale", "en");
    const document = { ...filing("samsung-2024"), registry: "dart", language: "ko", issuer: "005930", issuer_name: "삼성전자" };
    const getPage = live ? api.getAdminDocuments : api.getPublishedDocuments;
    getPage.mockResolvedValue({ documents: [document], total: 1, next_cursor: null });
    (live ? api.getDocumentFacets : api.getPublishedDocumentFacets).mockResolvedValue({ ...facets, issuers: [{ value: "005930", label: "005930 · 삼성전자", count: 1 }] });
    (live ? api.getDocumentDetail : api.getPublishedDocumentDetail).mockResolvedValue({ ...detail(document.doc_id), document });
    render(<I18nProvider><DocumentInventory live={live} fallbackDocuments={[]} /></I18nProvider>);
    expect(await screen.findByRole("option", { name: "005930 · Samsung Electronics (1)" })).toHaveValue("005930");
    expect(within(await screen.findByRole("row", { name: /samsung-2024/ })).getByText("005930 · Samsung Electronics")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Group documents" }), { target: { value: "issuer" } });
    expect(screen.getByText("Company · 005930 · Samsung Electronics")).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter company" }), { target: { value: "005930" } });
    await waitFor(() => expect(getPage.mock.calls.at(-1)?.[0].get("issuer")).toBe("005930"));
    expect(screen.getByRole("button", { name: "Remove filter: Company" })).toHaveTextContent("Samsung Electronics");
    fireEvent.click(await screen.findByRole("button", { name: document.doc_id }));
    expect(await screen.findByRole("heading", { name: "Samsung Electronics" })).toBeVisible();
    fireEvent(window, new StorageEvent("storage", { key: "docreview.locale", newValue: "ko" }));
    expect(await screen.findByRole("heading", { name: "삼성전자" })).toBeVisible();
    expect(document.issuer_name).toBe("삼성전자");
  });

  it.each([true, false])("shows company names in the list, detail, groups and facets while filtering by code (live=%s)", async (live) => {
    const namedDocument = { ...filing("nvda-2024"), issuer: "NVDA", issuer_name: "NVIDIA" };
    const earlierDocument = { ...filing("nvda-2023"), issuer: "NVDA", fiscal_year: 2024 };
    const companyPage = { documents: [namedDocument, earlierDocument], total: 2, next_cursor: null };
    const getPage = live ? api.getAdminDocuments : api.getPublishedDocuments;
    getPage.mockResolvedValue(companyPage);
    (live ? api.getDocumentFacets : api.getPublishedDocumentFacets).mockResolvedValue({
      ...facets, issuers: [{ value: "NVDA", label: "NVDA · NVIDIA", count: 2 }],
    });
    (live ? api.getDocumentDetail : api.getPublishedDocumentDetail).mockResolvedValue({
      ...detail("nvda-2024"), document: namedDocument,
    });
    render(<DocumentInventory live={live} fallbackDocuments={[]} />);
    expect(await screen.findByRole("option", { name: "NVDA · NVIDIA (2)" })).toHaveValue("NVDA");
    expect(within(await screen.findByRole("row", { name: /nvda-2024/ })).getByText("NVDA · NVIDIA")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Group documents" }), { target: { value: "issuer" } });
    const companyGroup = screen.getByText("Company · NVDA · NVIDIA");
    expect(companyGroup).toHaveTextContent("2 filings");
    expect(screen.queryByText("Company · NVDA", { exact: true })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "nvda-2024" }));
    const heading = await screen.findByRole("heading", { name: "NVIDIA" });
    const identity = heading.closest("header")!;
    expect(within(identity).getByLabelText("Fiscal year: 2024")).toHaveTextContent("FY 2024");
    expect(within(identity).getByText("nvda-2024")).toBeInTheDocument();
    expect(within(identity).getByText("NVDA · 10-K")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter company" }), { target: { value: "NVDA" } });
    expect(screen.getByRole("button", { name: "Remove filter: Company" })).toHaveTextContent("Company: NVDA · NVIDIA");
    await waitFor(() => expect(getPage).toHaveBeenCalledTimes(2));
    const params = getPage.mock.calls[1][0] as URLSearchParams;
    expect(params.get("issuer")).toBe("NVDA");
    expect(params.has("issuer_name")).toBe(false);
    expect(params.toString()).not.toContain("Apple");
  });

  it("keeps an unknown company code unchanged across the list, detail and filters", async () => {
    const unknownDocument = { ...filing("unknown-2025"), issuer: "ZZZZ", issuer_name: null };
    api.getAdminDocuments.mockResolvedValue({ documents: [unknownDocument], total: 1, next_cursor: null });
    api.getDocumentFacets.mockResolvedValue({ ...facets, issuers: [{ value: "ZZZZ", label: null, count: 1 }] });
    api.getDocumentDetail.mockResolvedValue({ ...detail("unknown-2025"), document: unknownDocument });
    render(<DocumentInventory live fallbackDocuments={[]} />);
    expect(await screen.findByRole("option", { name: "ZZZZ (1)" })).toHaveValue("ZZZZ");
    expect(within(await screen.findByRole("row", { name: /unknown-2025/ })).getByText("ZZZZ", { exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "unknown-2025" }));
    expect(await screen.findByRole("heading", { name: "ZZZZ" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Filter company" }), { target: { value: "ZZZZ" } });
    expect(screen.getByRole("button", { name: "Remove filter: Company" })).toHaveTextContent("Company: ZZZZ");
  });

  it("starts with a full-width inventory, opens the title and row, and exposes removable filters", async () => {
    render(<DocumentInventory live fallbackDocuments={[]} />);
    expect(document.querySelector(".document-detail")).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Filter registry" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    await screen.findByRole("option", { name: "SEC (2)" });
    fireEvent.change(screen.getByRole("combobox", { name: "Filter registry" }), { target: { value: "sec" } });
    expect(screen.getByRole("button", { name: "Remove filter: Registry" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove filter: Registry" }));
    expect(screen.getByRole("combobox", { name: "Filter registry" })).toHaveValue("all");
    fireEvent.click(await screen.findByRole("button", { name: "doc-a" }));
    expect(await screen.findByRole("heading", { name: "Issuer doc-a" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("row", { name: /doc-b/ }));
    expect(await screen.findByRole("heading", { name: "Issuer doc-b" })).toBeInTheDocument();
  });

  it("ignores a late list response after a new search", async () => {
    const old = deferred<AdminDocumentPage>();
    api.getAdminDocuments.mockReturnValueOnce(old.promise).mockResolvedValueOnce(page(["latest"]));
    render(<DocumentInventory live fallbackDocuments={[]} />);
    await waitFor(() => expect(api.getAdminDocuments).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("textbox", { name: "Search documents" }), { target: { value: "latest" } });
    expect(await screen.findByRole("button", { name: "latest" })).toBeInTheDocument();
    await act(async () => old.resolve(page(["obsolete"])));
    expect(screen.queryByRole("button", { name: "obsolete" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "latest" })).toBeInTheDocument();
  });

  it.each(["success", "failure"])("prevents a late detail %s from replacing the current selection", async (outcome) => {
    const first = deferred<DocumentDetail>();
    api.getDocumentDetail.mockReturnValueOnce(first.promise).mockResolvedValueOnce(detail("doc-b"));
    render(<DocumentInventory live fallbackDocuments={[]} />);
    fireEvent.click(await screen.findByRole("button", { name: "doc-a" }));
    expect(screen.getByText("Loading document details…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "doc-b" }));
    expect(await screen.findByRole("heading", { name: "Issuer doc-b" })).toBeInTheDocument();
    await act(async () => { if (outcome === "success") first.resolve(detail("doc-a")); else first.reject(new Error("obsolete failure")); });
    expect(screen.queryByText("obsolete failure")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Issuer doc-b" })).toBeInTheDocument();
  });

  it("does not append an old next page into a new query", async () => {
    const next = deferred<AdminDocumentPage>();
    api.getAdminDocuments.mockResolvedValueOnce(page(["doc-a"], "cursor-2")).mockReturnValueOnce(next.promise).mockResolvedValueOnce(page(["new-query"]));
    render(<DocumentInventory live fallbackDocuments={[]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Load next 50" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search documents" }), { target: { value: "new-query" } });
    expect(await screen.findByRole("button", { name: "new-query" })).toBeInTheDocument();
    await act(async () => next.resolve(page(["old-next-page"])));
    expect(screen.queryByRole("button", { name: "old-next-page" })).not.toBeInTheDocument();
  });

  it("replaces stale details with an explicit error or filtered-out state", async () => {
    api.getDocumentDetail.mockResolvedValueOnce(detail("doc-a")).mockRejectedValueOnce(new Error("detail unavailable"));
    render(<DocumentInventory live fallbackDocuments={[]} />);
    fireEvent.click(await screen.findByRole("button", { name: "doc-a" }));
    expect(await screen.findByRole("heading", { name: "Issuer doc-a" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "doc-b" }));
    expect(await screen.findByText(/detail unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Issuer doc-a" })).not.toBeInTheDocument();
    api.getAdminDocuments.mockResolvedValueOnce(page([]));
    fireEvent.change(screen.getByRole("textbox", { name: "Search documents" }), { target: { value: "missing" } });
    expect(await screen.findByRole("heading", { name: "Document outside current filters" })).toBeInTheDocument();
  });

  it("restores search, scroll and selected row after the single-pane detail view", async () => {
    vi.stubGlobal("ResizeObserver", class {
      constructor(private callback: ResizeObserverCallback) {}
      observe(target: Element) { this.callback([{ contentRect: { width: 900 }, target } as ResizeObserverEntry], this as unknown as ResizeObserver); }
      disconnect() {}
    });
    render(<DocumentInventory live fallbackDocuments={[]} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search documents" }), { target: { value: "doc" } });
    const rowButton = await screen.findByRole("button", { name: "doc-a" });
    const scroller = document.querySelector('[aria-busy="false"]') as HTMLElement;
    scroller.scrollTop = 150;
    fireEvent.click(rowButton);
    expect(await screen.findByRole("heading", { name: "Issuer doc-a" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Search documents" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to documents" }));
    expect(screen.getByRole("textbox", { name: "Search documents" })).toHaveValue("doc");
    expect(scroller.scrollTop).toBe(150);
    expect(screen.getByRole("row", { name: /doc-a/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("heading", { name: "Issuer doc-a" })).not.toBeInTheDocument();
  });

  it("reports malformed facets without crashing and retries the filter request", async () => {
    api.getDocumentFacets.mockResolvedValueOnce({}).mockResolvedValueOnce(facets);
    render(<DocumentInventory live fallbackDocuments={[]} />);
    expect(await screen.findByText("Could not load document filters.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "doc-a" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry filters" }));
    await waitFor(() => expect(screen.queryByText("Could not load document filters.")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(await screen.findByRole("option", { name: "SEC (2)" })).toBeInTheDocument();
  });

  it("uses only public reads for visitors and hides operator actions", async () => {
    render(<DocumentInventory live={false} fallbackDocuments={[]} onOpenPipeline={vi.fn()} onOpenJobs={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "doc-a" }));
    expect(await screen.findByRole("heading", { name: "Issuer doc-a" })).toBeInTheDocument();
    expect(api.getAdminDocuments).not.toHaveBeenCalled();
    expect(api.getDocumentDetail).not.toHaveBeenCalled();
    expect(api.getDocumentFacets).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Open Jobs" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open originating step" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open original filing" })).toHaveAttribute("href", "https://example.com/doc-a");
  });
});

it.each(["filters", "documents", "details"] as const)("offers pipeline inspection for %s failures while preserving retry", async (failure) => {
  const inspect = vi.fn();
  if (failure === "filters") api.getDocumentFacets.mockRejectedValueOnce(new Error("Filters unavailable"));
  if (failure === "documents") api.getAdminDocuments.mockRejectedValueOnce(new Error("Documents unavailable"));
  if (failure === "details") api.getDocumentDetail.mockRejectedValueOnce(new Error("Details unavailable"));
  render(<DocumentInventory live fallbackDocuments={[]} onInspectPipeline={inspect} />);
  if (failure === "details") fireEvent.click(await screen.findByRole("button", { name: "doc-a" }));
  fireEvent.click(await screen.findByRole("button", { name: "Inspect this step" }));
  expect(inspect).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: failure === "filters" ? "Retry filters" : "Retry" })).toBeEnabled();
});


it("refreshes retained inventory on activation and corpus completion without resetting filters", async () => {
  api.getAdminDocuments.mockResolvedValue(page([]));
  const view = render(<DocumentInventory live active={false} refreshRevision="" fallbackDocuments={[]} />);
  expect(api.getAdminDocuments).not.toHaveBeenCalled();
  view.rerender(<DocumentInventory live active refreshRevision="" fallbackDocuments={[]} />);
  await waitFor(() => expect(api.getAdminDocuments).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("Search"), { target: { value: "NVDA" } });
  await waitFor(() => expect(api.getAdminDocuments).toHaveBeenCalledTimes(2));
  api.getAdminDocuments.mockResolvedValue(page(["doc-after-ingest"]));
  view.rerender(<DocumentInventory live active refreshRevision="ingest:succeeded" fallbackDocuments={[]} />);
  expect(await screen.findByRole("button", { name: "doc-after-ingest" })).toBeVisible();
  expect(screen.getByLabelText("Search")).toHaveValue("NVDA");
  expect(api.getAdminDocuments.mock.calls.at(-1)?.[0].get("query")).toBe("NVDA");
  view.rerender(<DocumentInventory live active={false} refreshRevision="ingest:succeeded" fallbackDocuments={[]} />);
  api.getAdminDocuments.mockResolvedValue(page(["doc-after-return"]));
  view.rerender(<DocumentInventory live active refreshRevision="ingest:succeeded" fallbackDocuments={[]} />);
  expect(await screen.findByRole("button", { name: "doc-after-return" })).toBeVisible();
});
