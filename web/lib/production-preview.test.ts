import { afterEach, expect, it, vi } from "vitest";
import { browserStorage, enterProductionPreview, exitProductionPreview, presentationFetch, previewState, PREVIEW_STORAGE_PREFIX } from "./production-preview";
import { getProductionPreviewReadiness, getPublishedDocumentFacets, retrieveEvidence, saveLocalLLMConnection, streamReview } from "./api";
import { loadConversations, saveConversations, exportBrowserSettings, importBrowserSettings, validateBrowserSettings, browserResetStores, configureBrowserStorage } from "./storage";
import { DEFAULT_SESSION_PROFILE } from "./types";

afterEach(() => { configureBrowserStorage(undefined); exitProductionPreview(); vi.unstubAllGlobals(); localStorage.clear(); });

it("persists preview history and layout separately from DEV across reentry", () => {
  const conversation = { id: "private", title: "Private DEV history", createdAt: "2026-09-05", updatedAt: "2026-09-05", messages: [], profile: DEFAULT_SESSION_PROFILE };
  saveConversations([conversation]);
  localStorage.setItem("docreview:layout:documents", "488");
  const original = localStorage.getItem("docreview:conversations:v2");
  expect(enterProductionPreview("document")).toBe(true);
  expect(loadConversations()).toEqual([]);
  expect(browserStorage().getItem("docreview:layout:documents")).toBeNull();
  saveConversations([{ ...conversation, id: "preview", title: "Preview only" }]);
  browserStorage().setItem("docreview:layout:documents", "360");
  expect(localStorage.getItem("docreview:conversations:v2")).toBe(original);
  expect(Object.keys(localStorage).some(key => key.startsWith(PREVIEW_STORAGE_PREFIX))).toBe(true);
  exitProductionPreview();
  expect(loadConversations()).toEqual([conversation]);
  expect(browserStorage().getItem("docreview:layout:documents")).toBe("488");
  enterProductionPreview("document");
  expect(loadConversations()[0].id).toBe("preview");
  expect(browserStorage().getItem("docreview:layout:documents")).toBe("360");
});

it("dispatches public reads and real retrieval/review requests with the public header only", async () => {
  const fetch = vi.fn(async (url: RequestInfo | URL, _init?: RequestInit) => String(url).endsWith("/review/stream")
    ? new Response('event: report\ndata: {"status":"ok"}\n\nevent: done\ndata: {}\n\n', { headers: { "content-type": "text/event-stream" } })
    : new Response(JSON.stringify({ issuers: [], corpus: { documents: 18 }, review_enabled: true })));
  vi.stubGlobal("fetch", fetch);
  enterProductionPreview("document");
  await getPublishedDocumentFacets("dart");
  await getProductionPreviewReadiness();
  await retrieveEvidence("Actual public question", DEFAULT_SESSION_PROFILE);
  await presentationFetch("/docreview-rag-agent/api/review", { method: "POST", body: "{}" });
  await expect(streamReview("Actual public question", DEFAULT_SESSION_PROFILE, null, [], vi.fn())).resolves.toEqual({ status: "ok" });
  expect(fetch.mock.calls.map(([url]) => new URL(String(url), window.location.origin).pathname)).toEqual([
    "/docreview-rag-agent/api/public/documents/facets", "/docreview-rag-agent/api/ready", "/docreview-rag-agent/api/retrieve", "/docreview-rag-agent/api/review", "/docreview-rag-agent/api/review/stream",
  ]);
  for (const [, init] of fetch.mock.calls) expect(new Headers(init?.headers).get("X-DocReview-Public")).toBe("true");
  expect(JSON.parse(String(fetch.mock.calls[2][1]?.body)).query).toBe("Actual public question");
  for (const [url, method] of [["/admin/documents", "GET"], ["/admin/evaluations", "POST"], ["/ingest", "POST"], ["/public/documents", "DELETE"]]) {
    await expect(presentationFetch(`/docreview-rag-agent/api${url}`, { method })).rejects.toMatchObject({ name: "AbortError" });
  }
  await expect(presentationFetch("http://operator.test/jobs", {}, true)).rejects.toMatchObject({ name: "AbortError" });
  await expect(saveLocalLLMConnection("http://localhost:11434", "ollama")).rejects.toMatchObject({ name: "AbortError" });
  expect(fetch).toHaveBeenCalledTimes(5);
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

it("uses the actual readiness response without synthesizing public corpus facts", async () => {
  const readiness = { corpus: { documents: 18, chunks: 432, embedded_chunks: 400, writable: false }, review_enabled: true, models: { agent: { default: "test-model" } } };
  const fetch = vi.fn(async (_url: RequestInfo | URL) => new Response(JSON.stringify(readiness)));
  vi.stubGlobal("fetch", fetch);
  enterProductionPreview("document");
  expect(await getProductionPreviewReadiness()).toEqual(readiness);
  expect(String(fetch.mock.calls[0][0])).toContain("/ready");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps a preview frame isolated after a same-origin document reload", async () => {
  const previousName = window.name;
  const previousPath = window.location.pathname + window.location.search;
  localStorage.setItem("docreview:conversations:v2", "private history");
  localStorage.setItem("docreview.locale", "en");
  localStorage.setItem("docreview:theme", "dark");
  const previewConversation = { id: "preview-empty", title: "Empty selection", createdAt: "2026-09-05", updatedAt: "2026-09-05", messages: [], profile: DEFAULT_SESSION_PROFILE, publishedScope: [] };
  enterProductionPreview("document");
  saveConversations([previewConversation]);
  exitProductionPreview();
  const previewRecord = localStorage.getItem(PREVIEW_STORAGE_PREFIX + "docreview:conversations:v2");
  window.name = "docreview-production-preview";
  window.history.replaceState({}, "", "/docreview-rag-agent/production-preview/");
  vi.resetModules();
  const reloaded = await import("./production-preview");
  try {
    expect(reloaded.previewState().mode).toBe("document");
    expect(reloaded.browserStorage().getItem("docreview:conversations:v2")).toBe(previewRecord);
    const storage = await import("./storage");
    expect(storage.loadConversations()[0].publishedScope).toEqual([]);
    expect(reloaded.browserStorage().getItem("docreview:theme")).toBe("dark");
    reloaded.browserStorage().setItem("docreview:theme", "light");
    expect(localStorage.getItem("docreview:theme")).toBe("light");
    expect(reloaded.browserStorage().getItem("docreview.locale")).toBe("en");
    reloaded.browserStorage().setItem("docreview.locale", "ko");
    reloaded.browserStorage().setItem("docreview:conversations:v2", "preview history");
    expect(localStorage.getItem("docreview.locale")).toBe("ko");
    expect(localStorage.getItem("docreview:conversations:v2")).toBe("private history");
    await expect(reloaded.presentationFetch("/docreview-rag-agent/api/admin/documents")).rejects.toMatchObject({ name: "AbortError" });
  } finally {
    reloaded.exitProductionPreview();
    window.name = previousName;
    window.history.replaceState({}, "", previousPath);
    localStorage.removeItem("docreview.locale");
  }
});

it("re-arms the read deadline for a read resumed after a preview that outlasts it", async () => {
  vi.useFakeTimers();
  try {
    const signals: AbortSignal[] = [];
    const fetch = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
      const signal = init?.signal as AbortSignal;
      signals.push(signal);
      signal.addEventListener("abort", () => reject(signal.reason));
      if (signals.length === 2) setTimeout(() => resolve(new Response("{}")), 1_000);
    }));
    vi.stubGlobal("fetch", fetch);
    const pending = presentationFetch("/docreview-rag-agent/api/admin/documents", { timeoutMs: 5_000 });
    enterProductionPreview();
    await vi.advanceTimersByTimeAsync(20_000);
    exitProductionPreview();
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(pending).resolves.toBeInstanceOf(Response);
    expect(signals).toHaveLength(2);
    expect(signals[1].aborted).toBe(false);
  } finally {
    vi.useRealTimers();
  }
});

it("validates imports and scopes preview export, restore, and clear to its namespace", () => {
  const dev = { id: "dev", title: "DEV", createdAt: "2026-09-05", updatedAt: "2026-09-05", messages: [], profile: DEFAULT_SESSION_PROFILE };
  saveConversations([dev]);
  const devRecord = localStorage.getItem("docreview:conversations:v2");
  localStorage.setItem("docreview.locale", "en");
  localStorage.setItem("docreview:theme", "dark");
  localStorage.setItem("unrelated", "keep");
  enterProductionPreview("document");
  configureBrowserStorage("prod");
  saveConversations([{ ...dev, id: "preview", publishedScope: [] }]);
  const exported = exportBrowserSettings();
  expect(exported).not.toContain('"id": "dev"');
  expect(() => validateBrowserSettings(JSON.stringify({ format: "docreview-browser-storage", version: 1, entries: [{ key: "admin-token", version: 0, value: "secret" }] }))).toThrow();
  expect(importBrowserSettings(exported, false)).toBe(false);
  saveConversations([]);
  expect(importBrowserSettings(exported, true)).toBe(true);
  expect(loadConversations()[0]).toMatchObject({ id: "preview", publishedScope: [] });
  for (const store of browserResetStores()) store.clear();
  expect(browserStorage().getItem("docreview:conversations:v2")).toBeNull();
  expect(localStorage.getItem("docreview:conversations:v2")).toBe(devRecord);
  expect(localStorage.getItem("docreview.locale")).toBe("en");
  expect(localStorage.getItem("docreview:theme")).toBe("dark");
  expect(localStorage.getItem("unrelated")).toBe("keep");
});
