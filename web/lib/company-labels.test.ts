import { describe, expect, it } from "vitest";

import { companyDisplayName, companyLabel } from "./company-labels";

it.each([
  ["삼성전자", "Samsung Electronics", "삼성전자"],
  ["SK하이닉스", "SK hynix", "SK하이닉스"],
  ["SK 하이닉스", "SK hynix", "SK하이닉스"],
  ["005930 · 삼성전자", "005930 · Samsung Electronics", "005930 · 삼성전자"],
  ["Samsung Electronics", "Samsung Electronics", "삼성전자"],
  ["Samsung Electronics · 삼성전자", "Samsung Electronics", "삼성전자"],
  ["SK hynix · SK하이닉스", "SK hynix", "SK하이닉스"],
  ["NVIDIA · 엔비디아", "NVIDIA", "NVIDIA · 엔비디아"],
  ["Unknown Company", "Unknown Company", "Unknown Company"],
])("localizes a registered company label without guessing other names: %s", (raw, english, korean) => {
  expect(companyDisplayName(raw, "en")).toBe(english);
  expect(companyDisplayName(raw, "ko")).toBe(korean);
});

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
