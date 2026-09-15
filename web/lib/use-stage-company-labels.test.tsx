import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getDocumentFacets, getPublishedDocumentFacets } from "./api";
import { useStageCompanyLabels } from "./use-stage-company-labels";
import type { DocumentFacets } from "./types";

vi.mock("./api", () => ({ getDocumentFacets: vi.fn(), getPublishedDocumentFacets: vi.fn() }));
afterEach(cleanup);
beforeEach(() => { vi.resetAllMocks(); });

/** Supply a complete existing facet response without synthesizing a new API shape. */
function facets(value: string, label: string): DocumentFacets {
  return { registries: [], issuers: [{ value, label, count: 1 }], years: [], languages: [], forms: [], sections: [], parse_statuses: [], embedding_statuses: [], snapshots: [] };
}

it("loads only an opened panel and reuses its registry-scoped catalog on reopening", async () => {
  vi.mocked(getDocumentFacets).mockResolvedValue(facets("NVDA", "NVDA · NVIDIA"));
  const { result, rerender } = renderHook(({ active }) => useStageCompanyLabels(active, "live", "sec"), { initialProps: { active: false } });
  expect(getDocumentFacets).not.toHaveBeenCalled();
  rerender({ active: true });
  await waitFor(() => expect(result.current.labels).toEqual({ "sec:NVDA": "NVDA · NVIDIA" }));
  expect(getDocumentFacets).toHaveBeenCalledWith("sec", expect.any(AbortSignal));
  rerender({ active: false }); rerender({ active: true });
  expect(getDocumentFacets).toHaveBeenCalledOnce(); expect(getPublishedDocumentFacets).not.toHaveBeenCalled();
});

it("separates registries and routes public views only through the published catalog", async () => {
  vi.mocked(getPublishedDocumentFacets).mockImplementation(async (registry) => registry === "sec" ? facets("NVDA", "NVIDIA") : facets("005930", "삼성전자"));
  const { result } = renderHook(() => useStageCompanyLabels(true, "published", "dart,sec"));
  await waitFor(() => expect(result.current.labels).toEqual({ "sec:NVDA": "NVIDIA", "dart:005930": "Samsung Electronics" }));
  expect(getDocumentFacets).not.toHaveBeenCalled();
});

it("discards late private results after switching to the published catalog", async () => {
  let resolveLive!: (value: DocumentFacets) => void;
  vi.mocked(getDocumentFacets).mockImplementation(() => new Promise((resolve) => { resolveLive = resolve; }));
  vi.mocked(getPublishedDocumentFacets).mockResolvedValue(facets("NVDA", "Public name"));
  const { result, rerender } = renderHook(({ mode }: { mode: "live" | "published" }) => useStageCompanyLabels(true, mode, "sec"), { initialProps: { mode: "live" } });
  rerender({ mode: "published" });
  await waitFor(() => expect(result.current.labels["sec:NVDA"]).toBe("Public name"));
  await act(async () => { resolveLive(facets("NVDA", "Private name")); });
  expect(result.current.labels["sec:NVDA"]).toBe("Public name");
});

it("signals lookup failure explicitly so the panel can show original codes with an explanation", async () => {
  vi.mocked(getPublishedDocumentFacets).mockRejectedValue(new Error("Catalog unavailable"));
  const { result } = renderHook(() => useStageCompanyLabels(true, "published", "sec"));
  await waitFor(() => expect(result.current.failed).toBe(true)); expect(result.current.labels).toEqual({});
});
