import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n";
import type { AmendedReportPeriod, FilingVersion } from "@/lib/types";
import { AmendedFilings } from "./amended-filings";

const api = vi.hoisted(() => ({ getAmendedPeriods: vi.fn(), reviewAmendment: vi.fn(), withdrawAmendmentReview: vi.fn() }));
vi.mock("@/lib/api", () => api);
// The panel is given the real error class, so a refusal carries the message the API client builds.
const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");

/** The report an amendment restates, already parsed and still the newest whole report. */
const REPORT: FilingVersion = {
  filing_id: "0000002488-26-000012", form: "10-K", kind: "report", filing_date: "2026-02-04", doc_id: "AMD-FY2025",
  source_url: "https://www.sec.gov/Archives/amd-10k.htm", parse_status: "parsed",
  items: [{ item: "1A", chunks: 40 }, { item: "7", chunks: 31 }], unnumbered_chunks: 3, current: false, review: null,
};

/** An amendment that restates Items 7 and 15 and nobody has reviewed. */
const AMENDMENT: FilingVersion = {
  filing_id: "0000002488-26-000045", form: "10-K/A", kind: "amendment", filing_date: "2026-04-20", doc_id: "AMD-FY2025-A1",
  source_url: "https://www.sec.gov/Archives/amd-10ka.htm", parse_status: "parsed",
  items: [{ item: "7", chunks: 12 }, { item: "15", chunks: 2 }], unnumbered_chunks: 1, current: false, review: null,
};

/** AMD's FY2025 report period, held until its amendment is reviewed. */
function heldPeriod(overrides: Partial<AmendedReportPeriod> = {}): AmendedReportPeriod {
  return { registry: "sec", issuer: "AMD", fiscal_year: 2025, report_period: "2025-12-27", hold: "amendment_pending", versions: [REPORT, AMENDMENT], ...overrides };
}

/** The same period after a review that replaces Item 7 and withholds Item 15. */
function reviewedPeriod(): AmendedReportPeriod {
  const review = { reviewed_at: "2026-11-12T03:04:05Z", reviewer: "Dana Operator", rationale: "Item 7 restates revenue; Item 15 lists exhibits only.", decisions: [{ item: "15", action: "withhold" as const }, { item: "7", action: "replace" as const }] };
  return heldPeriod({ hold: null, versions: [{ ...REPORT, current: true }, { ...AMENDMENT, current: true, review }] });
}

function renderPanel(live = true) {
  return render(<I18nProvider><AmendedFilings live={live} /></I18nProvider>);
}

/** Open a report period the way an operator does; only a held one opens by itself. */
function openPeriod(name: string) {
  const summary = screen.getByText(name).closest("summary")!;
  fireEvent.click(summary);
  expect(summary.closest("details")).toHaveAttribute("open");
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem("docreview.locale", "en");
  api.getAmendedPeriods.mockResolvedValue([heldPeriod()]);
});

afterEach(() => { cleanup(); localStorage.clear(); });

describe("AmendedFilings", () => {
  it("lists a held report period, says why in plain words, and describes each filing in order", async () => {
    renderPanel();
    expect(screen.getByRole("status")).toHaveTextContent("Loading amended filings…");
    const filings = await screen.findByRole("list", { name: "Filings of SEC · AMD · FY 2025" });
    expect(screen.getByText("1 report periods · 1 on hold")).toBeVisible();
    expect(screen.getByText("On hold")).toBeVisible();
    expect(screen.getByText("An amendment to this report has not been reviewed yet, so nothing from this report period is used as evidence until an administrator reviews it under Build › Documents › Amended filings.")).toBeVisible();
    expect(screen.queryByText(/amendment_pending/)).toBeNull();

    const [report, amendment] = within(filings).getAllByRole("listitem").filter((row) => row.classList.contains("amended-version"));
    expect(report).toHaveTextContent("10-K");
    expect(report).toHaveTextContent("Report");
    expect(report).toHaveTextContent("0000002488-26-000012");
    expect(report).toHaveTextContent("2/4/2026");
    expect(report).toHaveTextContent("AMD-FY2025");
    expect(report).toHaveTextContent("Not used as evidence now");
    expect(report).toHaveTextContent("Item 1A40 chunks");
    expect(report).toHaveTextContent("Outside every Item: 3 chunks");
    expect(within(report).getByRole("link", { name: "Open original filing" })).toHaveAttribute("href", "https://www.sec.gov/Archives/amd-10k.htm");
    expect(within(report).queryByRole("button", { name: "Review this amendment" })).toBeNull();

    expect(amendment).toHaveTextContent("10-K/A (amendment to a 10-K)");
    expect(amendment).toHaveTextContent("Amendment");
    expect(amendment).toHaveTextContent("Item 152 chunks");
    expect(amendment).toHaveTextContent("This amendment has not been reviewed.");
    expect(within(amendment).getByRole("button", { name: "Review this amendment" })).toBeEnabled();
  });

  it("says when a filing is not downloaded or parsed and warns when its Items may be incomplete", async () => {
    api.getAmendedPeriods.mockResolvedValue([heldPeriod({
      hold: "not_indexed",
      versions: [
        { ...REPORT, parse_status: "partial", current: true },
        { ...REPORT, filing_id: "0000002488-26-000099", filing_date: "2026-06-01", doc_id: null, source_url: null, parse_status: null, items: [], unnumbered_chunks: 0 },
      ],
    })]);
    renderPanel();
    expect(await screen.findByText(/The latest report for this report period is known but not downloaded and parsed yet/)).toBeVisible();
    expect(screen.getByText("Not downloaded or not parsed yet")).toBeVisible();
    expect(screen.getByText(/This report is on record but is not downloaded or not parsed yet/)).toBeVisible();
    expect(screen.getByText("Parse status: partial. The parser could not find where every Item starts and ends, so the Items listed here may be incomplete.")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Open original filing" })).toHaveLength(1);
  });

  it("saves one decision for every Item and shows the period the server answers with", async () => {
    api.reviewAmendment.mockResolvedValue(reviewedPeriod());
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Review this amendment" }));
    const form = screen.getByRole("form", { name: "Review of 10-K/A (amendment to a 10-K)" });
    expect(within(form).getByText("Use the amendment's text for this Item instead of the report's.")).toBeVisible();
    expect(within(form).getByText("Use both the report's text and the amendment's text for this Item.")).toBeVisible();
    expect(within(form).getByText("Use neither filing's text for this Item.")).toBeVisible();
    const save = within(form).getByRole("button", { name: "Save review" });
    expect(save).toBeDisabled();

    fireEvent.change(within(form).getByLabelText("Reviewer"), { target: { value: " Dana Operator " } });
    fireEvent.change(within(form).getByLabelText("Rationale"), { target: { value: "Item 7 restates revenue; Item 15 lists exhibits only." } });
    fireEvent.click(within(within(form).getByRole("group", { name: "Item 7" })).getByRole("radio", { name: "Replace" }));
    expect(save).toBeDisabled();
    fireEvent.click(within(within(form).getByRole("group", { name: "Item 15" })).getByRole("radio", { name: "Withhold" }));
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(api.reviewAmendment).toHaveBeenCalledExactlyOnceWith("AMD-FY2025-A1", {
      reviewer: "Dana Operator",
      rationale: "Item 7 restates revenue; Item 15 lists exhibits only.",
      decisions: [{ item: "7", action: "replace" }, { item: "15", action: "withhold" }],
    }));
    expect(await screen.findByText("Review saved.")).toBeVisible();
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.getByText("In use")).toBeVisible();
    expect(screen.queryByText(/has not been reviewed yet/)).toBeNull();
    const record = screen.getByRole("region", { name: "Recorded review of 10-K/A (amendment to a 10-K)" });
    expect(record).toHaveTextContent("Reviewed by Dana Operator on");
    expect(record).toHaveTextContent("Item 7 restates revenue; Item 15 lists exhibits only.");
    expect(record).toHaveTextContent("Item 15WithholdUse neither filing's text for this Item.");
    expect(record).toHaveTextContent("Item 7ReplaceUse the amendment's text for this Item instead of the report's.");
    expect(api.getAmendedPeriods).toHaveBeenCalledOnce();
  });

  it("lets the reviewer decide an Item the amendment has no text for", async () => {
    api.reviewAmendment.mockResolvedValue(reviewedPeriod());
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Review this amendment" }));
    const form = screen.getByRole("form");
    fireEvent.change(within(form).getByLabelText("Reviewer"), { target: { value: "Dana" } });
    fireEvent.change(within(form).getByLabelText("Rationale"), { target: { value: "Item 9A is withdrawn by the amendment's cover note." } });
    fireEvent.click(within(within(form).getByRole("group", { name: "Item 7" })).getByRole("radio", { name: "Add" }));
    fireEvent.click(within(within(form).getByRole("group", { name: "Item 15" })).getByRole("radio", { name: "Add" }));

    const add = within(form).getByRole("button", { name: "Add Item" });
    expect(add).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Add an Item this amendment does not contain"), { target: { value: "item 9a" } });
    fireEvent.click(add);
    const extra = within(form).getByRole("group", { name: "Item 9A" });
    expect(extra).toHaveTextContent("No text in this amendment");
    expect(within(form).getByRole("button", { name: "Save review" })).toBeDisabled();
    fireEvent.click(within(extra).getByRole("radio", { name: "Withhold" }));
    // An Item already on the form cannot be added twice.
    fireEvent.change(within(form).getByLabelText("Add an Item this amendment does not contain"), { target: { value: "7" } });
    expect(add).toBeDisabled();
    fireEvent.click(within(form).getByRole("button", { name: "Save review" }));

    await waitFor(() => expect(api.reviewAmendment).toHaveBeenCalledOnce());
    expect(api.reviewAmendment.mock.calls[0][1].decisions).toEqual([{ item: "7", action: "add" }, { item: "15", action: "add" }, { item: "9A", action: "withhold" }]);
  });

  it("shows the server's refusal word for word next to the form and keeps what was entered", async () => {
    api.reviewAmendment.mockRejectedValue(new ApiError(400, "invalid_review", "the review leaves Items undecided: 15"));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Review this amendment" }));
    const form = screen.getByRole("form");
    fireEvent.change(within(form).getByLabelText("Reviewer"), { target: { value: "Dana" } });
    fireEvent.change(within(form).getByLabelText("Rationale"), { target: { value: "Checked." } });
    for (const item of ["Item 7", "Item 15"]) fireEvent.click(within(within(form).getByRole("group", { name: item })).getByRole("radio", { name: "Replace" }));
    fireEvent.click(within(form).getByRole("button", { name: "Save review" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent(/^the review leaves Items undecided: 15$/);
    expect(within(form).getByLabelText("Reviewer")).toHaveValue("Dana");
    expect(within(form).getByRole("button", { name: "Save review" })).toBeEnabled();
    expect(screen.getByText("On hold")).toBeVisible();
  });

  it("edits a recorded review starting from its decisions", async () => {
    api.getAmendedPeriods.mockResolvedValue([reviewedPeriod()]);
    api.reviewAmendment.mockResolvedValue(reviewedPeriod());
    renderPanel();
    expect(await screen.findByRole("button", { name: "Edit review" })).not.toBeVisible();
    openPeriod("SEC · AMD · FY 2025");
    fireEvent.click(screen.getByRole("button", { name: "Edit review" }));
    const form = screen.getByRole("form");
    expect(within(form).getByLabelText("Reviewer")).toHaveValue("Dana Operator");
    expect(within(within(form).getByRole("group", { name: "Item 7" })).getByRole("radio", { name: "Replace" })).toBeChecked();
    expect(within(within(form).getByRole("group", { name: "Item 15" })).getByRole("radio", { name: "Withhold" })).toBeChecked();
    fireEvent.click(within(within(form).getByRole("group", { name: "Item 15" })).getByRole("radio", { name: "Add" }));
    fireEvent.click(within(form).getByRole("button", { name: "Save review" }));
    await waitFor(() => expect(api.reviewAmendment).toHaveBeenCalledOnce());
    expect(api.reviewAmendment.mock.calls[0][1].decisions).toEqual([{ item: "7", action: "replace" }, { item: "15", action: "add" }]);
  });

  it("withdraws a review only after confirmation and shows the period held again", async () => {
    api.getAmendedPeriods.mockResolvedValue([reviewedPeriod()]);
    api.withdrawAmendmentReview.mockResolvedValue(heldPeriod());
    renderPanel();
    await screen.findByText("In use");
    openPeriod("SEC · AMD · FY 2025");
    fireEvent.click(screen.getByRole("button", { name: "Withdraw review" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm action" });
    expect(dialog).toHaveTextContent("Withdraw this review? The whole report period goes back on hold: nothing from it is used as evidence until the amendment is reviewed again.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.withdrawAmendmentReview).not.toHaveBeenCalled();
    expect(screen.getByText("In use")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Withdraw review" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Confirm action" })).getByRole("button", { name: "Withdraw review" }));
    await waitFor(() => expect(api.withdrawAmendmentReview).toHaveBeenCalledExactlyOnceWith("AMD-FY2025-A1"));
    expect(await screen.findByText("Review withdrawn. This report period is on hold again.")).toBeVisible();
    expect(screen.getByText("On hold")).toBeVisible();
    expect(screen.getByText(/An amendment to this report has not been reviewed yet/)).toBeVisible();
    expect(screen.queryByRole("region", { name: /Recorded review/ })).toBeNull();
  });

  it("reports a refused withdrawal in the server's words", async () => {
    api.getAmendedPeriods.mockResolvedValue([reviewedPeriod()]);
    api.withdrawAmendmentReview.mockRejectedValue(new ApiError(404, "amendment_not_found", "amendment AMD-FY2025-A1 was not found"));
    renderPanel();
    await screen.findByText("In use");
    openPeriod("SEC · AMD · FY 2025");
    fireEvent.click(screen.getByRole("button", { name: "Withdraw review" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Withdraw review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/^amendment AMD-FY2025-A1 was not found$/);
    expect(screen.getByRole("region", { name: /Recorded review/ })).toBeVisible();
  });

  it("explains an empty list", async () => {
    api.getAmendedPeriods.mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText("No report period has an amendment or a corrected report. When Check for newer filings finds one, it appears here.")).toBeVisible();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("reports a failed load and loads again on retry", async () => {
    api.getAmendedPeriods.mockRejectedValueOnce(new Error("The database is unavailable."));
    renderPanel();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load amended filings.");
    expect(alert).toHaveTextContent("The database is unavailable.");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("On hold")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reads the list again when a corpus job finishes and only while its tab is shown", async () => {
    const view = render(<I18nProvider><AmendedFilings live active={false} refreshRevision="" /></I18nProvider>);
    expect(api.getAmendedPeriods).not.toHaveBeenCalled();
    view.rerender(<I18nProvider><AmendedFilings live active refreshRevision="" /></I18nProvider>);
    await screen.findByText("On hold");
    expect(api.getAmendedPeriods).toHaveBeenCalledOnce();
    view.rerender(<I18nProvider><AmendedFilings live active refreshRevision="job-1:succeeded" /></I18nProvider>);
    await waitFor(() => expect(api.getAmendedPeriods).toHaveBeenCalledTimes(2));
  });

  it("stays out of the public mode: nothing is shown and the administrator route is never called", async () => {
    const { container } = renderPanel(false);
    await Promise.resolve();
    expect(container).toBeEmptyDOMElement();
    expect(api.getAmendedPeriods).not.toHaveBeenCalled();
  });

  it("reads in Korean when that is the interface language", async () => {
    localStorage.setItem("docreview.locale", "ko");
    renderPanel();
    expect(await screen.findByText("보류 중")).toBeVisible();
    expect(screen.getByRole("heading", { name: "수정·정정 공시" })).toBeVisible();
    expect(screen.getByText(/이 보고서의 수정 공시가 아직 검토되지 않아/)).toBeVisible();
    expect(screen.getByText("10-K/A (10-K 수정 공시)")).toBeVisible();
  });
});
