import { afterEach, expect, it, vi } from "vitest";
import { renderHook, waitFor, act, cleanup } from "@testing-library/react";
import { usePublishedCorpus } from "./use-published-corpus";
const page = vi.hoisted(() => vi.fn());
vi.mock("./api", () => ({ getPublishedDocuments: page }));
afterEach(() => { cleanup(); page.mockReset(); });
const document = { doc_id: "NVDA-2024", registry: "sec", issuer: "NVDA", fiscal_year: 2024, chunk_count: 10, embedded_chunks: 10 };

it("distinguishes empty success from a failed page and retains the last complete catalog", async () => {
  page.mockResolvedValueOnce({ documents: [document], next_cursor: null });
  const hook = renderHook(() => usePublishedCorpus(true));
  await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  expect(hook.result.current.documents).toHaveLength(1);
  page.mockResolvedValueOnce({ documents: [], next_cursor: "second" }).mockRejectedValueOnce(new Error("offline"));
  act(() => hook.result.current.refresh());
  await waitFor(() => expect(hook.result.current.status).toBe("error"));
  expect(hook.result.current.documents).toHaveLength(1);
  page.mockResolvedValueOnce({ documents: [], next_cursor: null });
  act(() => hook.result.current.refresh());
  await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  expect(hook.result.current.documents).toEqual([]);
});
it("rejects repeated cursors rather than returning partial success", async () => {
  page.mockResolvedValue({ documents: [document], next_cursor: "loop" });
  const hook = renderHook(() => usePublishedCorpus(true));
  await waitFor(() => expect(hook.result.current.status).toBe("error"));
  expect(hook.result.current.documents).toEqual([]);
  expect(page).toHaveBeenCalledTimes(2);
});
