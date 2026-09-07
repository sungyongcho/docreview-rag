import { describe, expect, it } from "vitest";

import { EVIDENCE_PAGE_SIZE, evidenceHeading, evidencePage } from "./evidence";

describe("evidence headings", () => {
  it("titles EDGAR items from the section title", () => {
    expect(evidenceHeading({ citation: "NVDA FY2024 · Item 7", section_title: "Management's Discussion and Analysis" }))
      .toBe("Item 7 - (Management's Discussion and Analysis)");
  });

  it("does not repeat a DART title the label already spells", () => {
    expect(evidenceHeading({ citation: "005930 FY2024 · II. 사업의 내용", section_title: "사업의 내용" })).toBe("II. 사업의 내용");
  });

  it("falls back to the citation label without a title and to the whole citation without a separator", () => {
    expect(evidenceHeading({ citation: "NVDA FY2020 · Item 15", section_title: null })).toBe("Item 15");
    expect(evidenceHeading({ citation: "ACME FY2024 - Item 7" })).toBe("ACME FY2024 - Item 7");
    expect(evidenceHeading({ citation: "NVDA FY2024 · Unnumbered section", section_title: "  " })).toBe("Unnumbered section");
  });
});

describe("evidence pages", () => {
  it("slices five candidates per page with one-based bounds", () => {
    const items = Array.from({ length: 12 }, (_, index) => index + 1);
    expect(evidencePage(items, 0)).toEqual({ items: items.slice(0, EVIDENCE_PAGE_SIZE), page: 0, pages: 3, from: 1, to: 5 });
    expect(evidencePage(items, 1)).toEqual({ items: [6, 7, 8, 9, 10], page: 1, pages: 3, from: 6, to: 10 });
    expect(evidencePage(items, 2)).toEqual({ items: [11, 12], page: 2, pages: 3, from: 11, to: 12 });
  });

  it("clamps an overflowing page and reports an empty list honestly", () => {
    expect(evidencePage([1, 2, 3], 5, 2)).toEqual({ items: [3], page: 1, pages: 2, from: 3, to: 3 });
    expect(evidencePage([], 2)).toEqual({ items: [], page: 0, pages: 1, from: 0, to: 0 });
  });
});
