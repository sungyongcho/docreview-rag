import { describe, expect, it } from "vitest";

import { evidenceHoldSentence, heldEvidence, itemLabel, reportPeriodLabel } from "./evidence-holds";
import { translate } from "./i18n";
import type { EvidenceHold } from "./types";

const english = (source: string, values?: Record<string, string | number>) => translate("en", source, values);
const korean = (source: string, values?: Record<string, string | number>) => translate("ko", source, values);

/** Every reason the contract names, plus the one the server adds for a document scope. */
const REASONS = ["amendment_pending", "report_missing", "order_unknown", "not_indexed", "item_withheld", "replaced"] as const;

/** Build one hold on AMD's FY2025 report period. */
function hold(reason: string, items: string[] = []): EvidenceHold {
  return { registry: "sec", issuer: "AMD", fiscal_year: 2025, reason: reason as EvidenceHold["reason"], items };
}

describe("evidence hold wording", () => {
  it("gives every reason its own sentence that never shows an internal identifier", () => {
    const sentences = REASONS.map((reason) => evidenceHoldSentence(hold(reason), english));
    expect(new Set(sentences).size).toBe(REASONS.length);
    for (const sentence of sentences) {
      expect(sentence).not.toMatch(/[a-z]_[a-z]/);
      expect(sentence).toMatch(/evidence/);
    }
  });

  it("tells the operator what ends an unreviewed amendment's hold", () => {
    expect(evidenceHoldSentence(hold("amendment_pending"), english)).toBe("An amendment to this report has not been reviewed yet, so nothing from this report period is used as evidence until an administrator reviews it under Build › Documents › Amended filings.");
  });

  it("names the Items a review withheld the way the registry cites them", () => {
    expect(evidenceHoldSentence(hold("item_withheld", ["7", "9A"]), english)).toContain("withheld Item 7, Item 9A of this report period");
    expect(evidenceHoldSentence(hold("item_withheld"), english)).toContain("withheld some Items of this report period");
  });

  it("still says that evidence is held for a reason this build does not know", () => {
    expect(evidenceHoldSentence(hold("superseded_elsewhere"), english)).toBe("A later filing keeps this report period's text out of evidence.");
    expect(evidenceHoldSentence(hold("toString"), english)).toBe("A later filing keeps this report period's text out of evidence.");
  });

  it("has Korean wording for every sentence", () => {
    for (const subject of [...REASONS.map((reason) => hold(reason)), hold("item_withheld", ["7"]), hold("unknown_reason")]) {
      expect(evidenceHoldSentence(subject, korean), subject.reason).not.toBe(evidenceHoldSentence(subject, english));
    }
    expect(evidenceHoldSentence(hold("item_withheld", ["7"]), korean)).toContain("Item 7");
  });

  it("labels a report period and an Item for each registry", () => {
    expect(reportPeriodLabel(hold("amendment_pending"), english)).toBe("SEC · AMD · FY 2025");
    expect(itemLabel("sec", "1A")).toBe("Item 1A");
    expect(itemLabel("dart", "II")).toBe("II");
  });
});

describe("held evidence of a run report", () => {
  it("reads the holds from the evidence_held reason wherever it stands", () => {
    const holds = [hold("amendment_pending")];
    expect(heldEvidence([{ code: "evidence_held", holds }, { code: "retrieval_empty" }])).toEqual(holds);
    expect(heldEvidence([{ code: "retrieval_empty" }, { code: "evidence_held", holds }])).toEqual(holds);
  });

  it("reports nothing held for a run without that reason", () => {
    expect(heldEvidence([{ code: "retrieval_empty" }])).toBeUndefined();
    expect(heldEvidence(undefined)).toBeUndefined();
  });
});
