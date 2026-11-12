import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n";
import type { EvidenceHold } from "@/lib/types";
import { EvidenceHoldNotice } from "./evidence-hold-notice";

afterEach(() => { cleanup(); localStorage.clear(); });

const HOLDS: EvidenceHold[] = [
  { registry: "sec", issuer: "AMD", fiscal_year: 2025, reason: "amendment_pending", items: [] },
  { registry: "sec", issuer: "NVDA", fiscal_year: 2024, reason: "item_withheld", items: ["7"] },
];

describe("EvidenceHoldNotice", () => {
  it("lists each held report period with its reason in plain words", () => {
    localStorage.setItem("docreview.locale", "en");
    render(<I18nProvider><EvidenceHoldNotice holds={HOLDS} /></I18nProvider>);
    const notice = screen.getByRole("note", { name: "Evidence on hold" });
    const rows = within(notice).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("SEC · AMD · FY 2025");
    expect(rows[0]).toHaveTextContent(/An amendment to this report has not been reviewed yet/);
    expect(rows[1]).toHaveTextContent("SEC · NVDA · FY 2024");
    expect(rows[1]).toHaveTextContent(/withheld Item 7 of this report period/);
    expect(notice).toHaveTextContent(/not that the filings never said it/);
    expect(notice).not.toHaveTextContent(/amendment_pending|item_withheld/);
  });

  it.each([undefined, []])("renders nothing when nothing is held (%j)", (holds) => {
    const { container } = render(<I18nProvider><EvidenceHoldNotice holds={holds} /></I18nProvider>);
    expect(container).toBeEmptyDOMElement();
  });

  it("reads in Korean when that is the interface language", () => {
    localStorage.setItem("docreview.locale", "ko");
    render(<I18nProvider><EvidenceHoldNotice holds={HOLDS.slice(0, 1)} /></I18nProvider>);
    const notice = screen.getByRole("note", { name: "보류 중인 근거" });
    expect(notice).toHaveTextContent("SEC · AMD · 2025 회계연도");
    expect(notice).toHaveTextContent(/수정 공시가 아직 검토되지 않아/);
  });
});
