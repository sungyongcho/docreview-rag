import { describe, expect, it } from "vitest";

import { evidenceHeading, evidencePage } from "./evidence";

describe("evidence headings", () => {

  it("falls back to the citation label without a title and to the whole citation without a separator", () => {
    expect(evidenceHeading({ citation: "NVDA FY2020 · Item 15", section_title: null })).toBe("Item 15");
    expect(evidenceHeading({ citation: "ACME FY2024 - Item 7" })).toBe("ACME FY2024 - Item 7");
    expect(evidenceHeading({ citation: "NVDA FY2024 · Unnumbered section", section_title: "  " })).toBe("Unnumbered section");
  });
});

describe("evidence pages", () => {

  it("clamps an overflowing page and reports an empty list honestly", () => {
    expect(evidencePage([1, 2, 3], 5, 2)).toEqual({ items: [3], page: 1, pages: 2, from: 3, to: 3 });
    expect(evidencePage([], 2)).toEqual({ items: [], page: 0, pages: 1, from: 0, to: 0 });
  });
});
