"use client";

import { useEffect, useState } from "react";
import { getDocumentFacets, getPublishedDocumentFacets } from "./api";
import type { CompanyLabels } from "@/components/review-stage-value";

export type CompanyCatalogMode = "live" | "published";

/** Load names only for an opened scope panel, preserving registry and public/live boundaries. */
export function useStageCompanyLabels(active: boolean, mode: CompanyCatalogMode | undefined, registryKey: string) {
  const [result, setResult] = useState<{ key: string; labels: CompanyLabels; failed: boolean } | null>(null);
  const key = `${mode}:${registryKey}`;
  useEffect(() => {
    if (!active || !mode || result?.key === key) return;
    const controller = new AbortController();
    let current = true;
    const registries = registryKey.split(",").filter((value) => value === "sec" || value === "dart");
    const load = mode === "live" ? getDocumentFacets : getPublishedDocumentFacets;
    void Promise.all(registries.map(async (registry) => {
      const facets = await load(registry, controller.signal);
      if (!Array.isArray(facets.issuers) || facets.issuers.some((issuer) => typeof issuer.value !== "string" || (issuer.label != null && typeof issuer.label !== "string"))) throw new Error("Invalid company catalog");
      return facets.issuers.map((issuer) => [`${registry}:${issuer.value.toUpperCase()}`, issuer.label?.trim() || issuer.value] as const);
    })).then((groups) => { if (current) setResult({ key, labels: Object.fromEntries(groups.flat()), failed: false }); })
      .catch(() => { if (current && !controller.signal.aborted) setResult({ key, labels: {}, failed: true }); });
    return () => { current = false; controller.abort(); };
  }, [active, mode, registryKey, key, result?.key]);
  return result?.key === key ? { labels: result.labels, failed: result.failed } : { labels: {}, failed: false };
}
