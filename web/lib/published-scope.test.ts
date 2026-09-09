import { describe, expect, it } from "vitest";
import { DEFAULT_SESSION_PROFILE } from "./types";
import { portfolioDocuments, effectivePublishedProfile, createPublicTargets, publicTargetIds, pinPublicTargets, publishedScopeStats, PORTFOLIO_FILINGS, type PublishedDocument } from "./published-scope";

/** Minimal real-shaped inventory row; tests vary identity and coverage independently. */
function doc(issuer: string, fiscal_year: number): PublishedDocument {
  return { doc_id: `${issuer}-${fiscal_year}`, issuer, fiscal_year, registry: issuer === "005930" ? "dart" : "sec", language: issuer === "005930" ? "ko" : "en", chunk_count: 10, embedded_chunks: 8 } as PublishedDocument;
}
const documents = [doc("NVDA", 2023), doc("NVDA", 2024), doc("AMD", 2023), doc("AMD", 2024), doc("005930", 2022)];

describe("published portfolio scope", () => {
  it("fixes the 18 tested company/year pairs and excludes other issuers and years", () => {
    expect(PORTFOLIO_FILINGS.reduce((sum, row) => sum + row.last - row.first + 1, 0)).toBe(18);
    expect(portfolioDocuments([...documents, doc("NVDA", 2025), doc("005930", 2020), doc("INTC", 2024)])).toEqual(documents);
  });
  it("keeps sparse pairs exact in every request, rather than expanding their cross product", () => {
    const profile = effectivePublishedProfile(DEFAULT_SESSION_PROFILE, documents, ["NVDA-2023", "AMD-2024"]);
    expect(profile.doc_ids).toEqual(["NVDA-2023", "AMD-2024"]);
    expect(profile.fiscal_years).toEqual([2023, 2024]);
    expect(publishedScopeStats(documents, profile.doc_ids)).toMatchObject({ filings: 2, total: 5, chunks: 20, embedded: 16, pending: 4 });
  });
  it("bounds whole-corpus requests while preserving automatic routing", () => {
    const profile = effectivePublishedProfile(DEFAULT_SESSION_PROFILE, documents, undefined);
    expect(profile.doc_ids).toHaveLength(5);
    expect(profile.issuers).toEqual([]);
    expect(profile.registries).toEqual([]);
    expect(profile.fiscal_years).toEqual([]);
  });
  it("distinguishes explicit empty selection and removes unavailable IDs without widening", () => {
    expect(effectivePublishedProfile(DEFAULT_SESSION_PROFILE, documents, []).doc_ids).toEqual([]);
    expect(effectivePublishedProfile(DEFAULT_SESSION_PROFILE, documents, ["removed"]).doc_ids).toEqual([]);
    expect(effectivePublishedProfile(DEFAULT_SESSION_PROFILE, documents, ["removed", "AMD-2024"]).doc_ids).toEqual(["AMD-2024"]);
  });
  it("intersects SEC/DART tabs and restores the saved selection on Auto", () => {
    const ids = ["NVDA-2023", "005930-2022"];
    const sec = effectivePublishedProfile({ ...DEFAULT_SESSION_PROFILE, corpus_scope: "sec" }, documents, ids);
    expect(sec.doc_ids).toEqual(["NVDA-2023"]);
    expect(sec.issuers).toEqual(["NVDA"]);
    expect(effectivePublishedProfile({ ...DEFAULT_SESSION_PROFILE, corpus_scope: "dart" }, documents, ids).doc_ids).toEqual(["005930-2022"]);
    expect(effectivePublishedProfile(DEFAULT_SESSION_PROFILE, documents, ids).doc_ids).toEqual(ids);
  });
  it("intersects manual company/year filters with exact saved IDs", () => {
    expect(effectivePublishedProfile({ ...DEFAULT_SESSION_PROFILE, issuers: ["AMD"], fiscal_years: [2024] }, documents, undefined).doc_ids).toEqual(["AMD-2024"]);
  });
});


it("keeps pending targets out of requests, then pins their first published identities", () => {
  const pending = createPublicTargets([], [{ registry: "sec", issuer: "NVDA", year: 2024 }]);
  expect(pending).toEqual([{ registry: "sec", issuer: "NVDA", year: 2024 }]);
  expect(publicTargetIds([], pending)).toEqual([]);
  const pinned = pinPublicTargets(documents, pending);
  expect(publicTargetIds(documents, pinned)).toEqual(["NVDA-2024"]);
  const replacement = [{ ...doc("NVDA", 2024), doc_id: "different-filing" }];
  expect(publicTargetIds(replacement, pinned)).toEqual(["NVDA-2024"]);
  expect(effectivePublishedProfile(DEFAULT_SESSION_PROFILE, replacement, publicTargetIds(replacement, pinned)).doc_ids).toEqual([]);
  expect(pinPublicTargets(replacement, pinned)).toBe(pinned);
  expect(publicTargetIds(documents, [])).toEqual([]);
});
