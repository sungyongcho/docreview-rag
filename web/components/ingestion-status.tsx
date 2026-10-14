"use client";

import type { CorpusDocument } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import "./ingestion-status.css";

export type IngestionStatus = CorpusDocument["ingestion_status"];

export const INGESTION_STATUS_LABELS: Record<IngestionStatus, string> = {
  not_ingested: "Not ingested",
  current: "Matches local source",
  stale: "Reingestion needed",
  unknown: "Source match unknown",
};

export const INGESTION_STATUS_DESCRIPTIONS: Record<IngestionStatus, string> = {
  not_ingested: "This source has not been ingested. Select it in Parse & chunk to prepare document chunks.",
  current: "The ingested document matches the stored source and its metadata. Embeddings and BM25 readiness are checked separately.",
  stale: "The stored source or metadata differs from the ingested version. Existing search results may still use the previous version. Run Parse & chunk for this source to update it.",
  unknown: "The source match could not be checked. Check source availability and database access before assuming the ingested version is current.",
};

/** Display the server's source comparison separately from search-index readiness. */
export function IngestionStatusBadge({ status }: { status: IngestionStatus }) {
  const { t } = useI18n();
  return <span className={`ingestion-status ${status}`} title={t(INGESTION_STATUS_DESCRIPTIONS[status])}>{t(INGESTION_STATUS_LABELS[status])}</span>;
}
