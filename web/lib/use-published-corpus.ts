"use client";
import { useCallback, useEffect, useState } from "react";
import { getPublishedDocuments } from "./api";
import { portfolioDocuments, type PublishedDocument } from "./published-scope";

export interface PublishedCorpus {
  documents: PublishedDocument[];
  status: "loading" | "ready" | "error";
  refresh: () => void;
}

/** Collect the filtered published inventory before applying the fixed portfolio boundary. */
export async function loadPublishedPortfolio(filters = new URLSearchParams()): Promise<PublishedDocument[]> {
  const rows: PublishedDocument[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams(filters);
    params.set("limit", "100");
    params.delete("cursor");
    if (cursor) params.set("cursor", cursor);
    const page = await getPublishedDocuments(params);
    rows.push(...page.documents);
    cursor = page.next_cursor;
    if (cursor && seen.has(cursor)) throw new Error("Repeated published document cursor");
    if (cursor) seen.add(cursor);
  } while (cursor);
  return portfolioDocuments(rows);
}

/** Load public pages atomically; never turn a failed or partial listing into an empty corpus. */
export function usePublishedCorpus(enabled: boolean): PublishedCorpus {
  const [documents, setDocuments] = useState<PublishedDocument[]>([]);
  const [status, setStatus] = useState<PublishedCorpus["status"]>("loading");
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setStatus("loading");
    async function load() {
      const rows = await loadPublishedPortfolio();
      if (!cancelled) { setDocuments(rows); setStatus("ready"); }
    }
    void load().catch(() => { if (!cancelled) setStatus("error"); });
    return () => { cancelled = true; };
  }, [enabled, revision]);
  return { documents, status, refresh };
}
