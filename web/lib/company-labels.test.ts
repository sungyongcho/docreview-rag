import { describe, expect, it } from "vitest";

import { companyLabel } from "./company-labels";

describe("companyLabel", () => {
  it("appends a supplied company name with surrounding whitespace removed", () => {
    expect(companyLabel("AAPL", " Apple Inc. ")).toBe("AAPL · Apple Inc.");
    expect(companyLabel("005930", "삼성전자")).toBe("005930 · 삼성전자");
  });

  it.each([undefined, null, "", "   "])("preserves the raw issuer without a name: %s", (name) => {
    expect(companyLabel("UNKNOWN", name)).toBe("UNKNOWN");
  });

  it("omits names that duplicate the issuer regardless of case", () => {
    expect(companyLabel("AAPL", " aapl ")).toBe("AAPL");
  });
});
