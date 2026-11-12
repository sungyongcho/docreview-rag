import { describe, expect, it } from "vitest";

import { documentFormLabel, formatFilingDate } from "./filing-labels";
import { translate } from "./i18n";

const english = (source: string) => translate("en", source);
const korean = (source: string) => translate("ko", source);

describe("filing form label", () => {
  it("presents a 10-K/A as an amendment of a 10-K in both languages", () => {
    expect(documentFormLabel("10-K/A", english)).toBe("10-K/A (amendment to a 10-K)");
    expect(documentFormLabel("10-K/A", korean)).toBe("10-K/A (10-K 수정 공시)");
  });

  it("keeps a 10-K as it is and localizes the DART annual report", () => {
    expect(documentFormLabel("10-K", english)).toBe("10-K");
    expect(documentFormLabel("사업보고서", english)).toBe("Annual report");
    expect(documentFormLabel("사업보고서", korean)).toBe("사업보고서");
  });

  it("shows an unknown form unchanged, including one named like an object member", () => {
    expect(documentFormLabel("20-F", english)).toBe("20-F");
    expect(documentFormLabel("constructor", english)).toBe("constructor");
  });
});

describe("filing date", () => {
  it("keeps the filing day in every time zone and tolerates a missing or malformed date", () => {
    expect(formatFilingDate("2026-02-04", "en-US")).toBe("2/4/2026");
    expect(formatFilingDate(null, "en-US")).toBe("—");
    expect(formatFilingDate("not a date", "en-US")).toBe("not a date");
  });
});
