import { afterEach, expect, it, vi } from "vitest";
import { browserStorage, enterProductionPreview, exitProductionPreview, presentationFetch, previewState } from "./production-preview";
import { getProductionPreviewReadiness, getPublishedDocumentFacets, saveLocalLLMConnection, streamReview } from "./api";
import { loadConversations, saveConversations } from "./storage";
import { DEFAULT_SESSION_PROFILE } from "./types";

afterEach(() => { exitProductionPreview(); vi.unstubAllGlobals(); localStorage.clear(); });

it("isolates preview history, defaults, and writes from persistent DEV storage", () => {
  const conversation = { id: "private", title: "Private DEV history", createdAt: "2026-09-05", updatedAt: "2026-09-05", messages: [], profile: DEFAULT_SESSION_PROFILE };
  saveConversations([conversation]);
  localStorage.setItem("docreview:layout:documents", "488");
  const original = JSON.stringify(localStorage);
  expect(enterProductionPreview("document")).toBe(true);
  expect(loadConversations()).toEqual([]);
  expect(browserStorage().getItem("docreview:layout:documents")).toBeNull();
  saveConversations([{ ...conversation, id: "preview", title: "Preview only" }]);
  browserStorage().setItem("docreview:layout:documents", "360");
  expect(JSON.stringify(localStorage)).toBe(original);
  exitProductionPreview();
  expect(loadConversations()).toEqual([conversation]);
  expect(browserStorage().getItem("docreview:layout:documents")).toBe("488");
});

it("permits only public metadata GETs and never dispatches writes or generation", async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ issuers: [] })));
  vi.stubGlobal("fetch", fetch);
  enterProductionPreview("document");
  await getPublishedDocumentFacets("dart");
  expect(String(fetch.mock.calls[0][0])).toContain("/public/documents/facets?registry=dart");
  expect(new Headers(fetch.mock.calls[0][1]?.headers).get("X-DocReview-Public")).toBe("true");
  await expect(presentationFetch("/docreview-rag-agent/api/admin/documents")).rejects.toMatchObject({ name: "AbortError" });
  await expect(presentationFetch("/docreview-rag-agent/api/ready")).rejects.toMatchObject({ name: "AbortError" });
  await expect(presentationFetch("http://operator.test/jobs", {}, true)).rejects.toMatchObject({ name: "AbortError" });
  await expect(saveLocalLLMConnection("http://localhost:11434", "ollama")).rejects.toMatchObject({ name: "AbortError" });
  await expect(streamReview("Do not send", DEFAULT_SESSION_PROFILE, null, [], vi.fn())).rejects.toMatchObject({ name: "AbortError" });
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("refuses preview entry while an existing mutation is in flight", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
  const pending = presentationFetch("/docreview-rag-agent/api/admin/local-llm/select", { method: "POST" });
  expect(enterProductionPreview()).toBe(false);
  expect(previewState().mode).toBe("normal");
  finish(new Response("{}"));
  await pending;
  expect(enterProductionPreview()).toBe(true);
});

it("aborts pending DEV reads, blocks hidden reads, and resumes finite reads on exit", async () => {
  let firstSignal: AbortSignal | undefined;
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    if (fetch.mock.calls.length > 1) return Promise.resolve(new Response("{}"));
    firstSignal = init?.signal as AbortSignal;
    return new Promise<Response>((_resolve, reject) => firstSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
  });
  vi.stubGlobal("fetch", fetch);
  const pending = presentationFetch("/docreview-rag-agent/api/admin/documents");
  enterProductionPreview();
  expect(firstSignal?.aborted).toBe(true);
  await expect(presentationFetch("/docreview-rag-agent/api/admin/jobs")).rejects.toMatchObject({ name: "AbortError" });
  expect(fetch).toHaveBeenCalledTimes(1);
  exitProductionPreview();
  await pending;
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("derives preview counts from the actual public catalog and leaves uncollected facts null", async () => {
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ documents: [], total: 0, next_cursor: null })));
  vi.stubGlobal("fetch", fetch);
  enterProductionPreview("document");
  const result = await getProductionPreviewReadiness();
  expect(result.corpus).toMatchObject({ documents: 0, chunks: null, embedded_chunks: null, database_connected: null, schema_status: null, writable: false });
  expect(result.review_enabled).toBe(false);
  expect(result.models).toEqual({});
  expect(String(fetch.mock.calls[0][0])).toContain("/public/documents?limit=1");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps a preview frame isolated after a same-origin document reload", async () => {
  const previousName = window.name;
  const previousPath = window.location.pathname + window.location.search;
  localStorage.setItem("docreview:conversations:v2", "private history");
  window.name = "docreview-production-preview";
  window.history.replaceState({}, "", "/docreview-rag-agent/production-preview/?locale=en");
  vi.resetModules();
  const reloaded = await import("./production-preview");
  try {
    expect(reloaded.previewState().mode).toBe("document");
    expect(reloaded.browserStorage().getItem("docreview:conversations:v2")).toBeNull();
    expect(reloaded.browserStorage().getItem("docreview.locale")).toBe("en");
    await expect(reloaded.presentationFetch("/docreview-rag-agent/api/admin/documents")).rejects.toMatchObject({ name: "AbortError" });
  } finally {
    reloaded.exitProductionPreview();
    window.name = previousName;
    window.history.replaceState({}, "", previousPath);
  }
});
