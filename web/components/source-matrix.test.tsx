import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SourceMatrix } from "./source-matrix";
import type { AcquisitionForm, AcquisitionPair } from "./build-pipeline";
import type { AcquisitionCompany } from "@/lib/acquisition-catalog";
import { acquisitionDraft, type SourceInventory } from "@/lib/source-selection";

afterEach(cleanup);

/** Build one distinct source document without hiding registry or disk state. */
function source(issuer: string, year: number, onDisk = true, name = issuer): SourceInventory {
  return { document_id: `${issuer}-${year}`, registry: /^\d{6}$/.test(issuer) ? "dart" : "sec", issuer, fiscal_year: year, ready: onDisk, on_disk: onDisk, name, manifest: "manifest.json" };
}
const inventory = [source("NVDA", 2024), source("005930", 2023, false, "Samsung"), source("AMD", 2023), source("NVDA", 2022)];

/** Keep the matrix controlled and expose the exact sparse selection used by downstream steps. */
function Harness({ sources = inventory, initialPairs = [] as AcquisitionPair[], companies = [{ registry: "sec", issuer: "NVDA", name: "NVDA" }, { registry: "sec", issuer: "AMD", name: "AMD" }, { registry: "dart", issuer: "000660", name: "000660" }] as AcquisitionCompany[], changed = vi.fn(), download = vi.fn(), disabled = false }) {
  const [draft, setDraft] = useState<AcquisitionForm>(acquisitionDraft(initialPairs));
  return <SourceMatrix sources={sources} companies={companies} acquisition={draft} onChange={(next) => { changed(next); setDraft(next); }} disabled={disabled} onDownload={download} downloadDisabled={false} />;
}

/** Enter through the one search box, committing company context before fiscal years. */
function enter(value: string) {
  const input = screen.getByLabelText("Search/add company or year");
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("company and year source matrix", () => {
  it("sorts compact rows, keeps registry/name identity and exposes readiness without captions", () => {
    render(<Harness companies={[{ registry: "sec", issuer: "NVDA", name: "NVIDIA" }]} />);
    const sec = screen.getByRole("region", { name: "SEC" });
    expect(within(sec).getAllByRole("group").map((row) => row.getAttribute("aria-label"))).toEqual(["AMD", "NVDA · NVIDIA"]);
    const chips = within(screen.getByRole("group", { name: "NVDA · NVIDIA" })).getAllByRole("button");
    expect(chips.map((chip) => chip.textContent)).toEqual(["✓FY2022", "✓FY2024"]);
    expect(chips[1]).toHaveAccessibleName("NVDA FY2024 · On disk");
    expect(screen.getByRole("button", { name: "005930 FY2023 · Missing source" })).toHaveClass("missing");
  });
  it("uses deduplicated document-name frequency when the catalog has no name", () => {
    const uncommon = source("INTC", 2024, true, "INTEL CORP");
    render(<Harness sources={[source("INTC", 2021, true, "Intel"), source("INTC", 2022, true, "Intel"), uncommon, { ...uncommon, manifest: "other.json" }]} />);
    expect(screen.getByRole("group", { name: "INTC · Intel" })).toBeVisible();
  });
  it("toggles sparse cells and indeterminate rows without adding a Cartesian product", () => {
    const changed = vi.fn(); render(<Harness changed={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "NVDA FY2024 · On disk" }));
    fireEvent.click(screen.getByRole("button", { name: "AMD FY2023 · On disk" }));
    expect(changed.mock.calls.at(-1)![0].pairs).toEqual([{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "sec", issuer: "AMD", year: 2023 }]);
    expect(screen.getByRole("checkbox", { name: "Select all years for NVDA" })).toHaveProperty("indeterminate", true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all years for NVDA" }));
    expect(screen.getByRole("button", { name: "NVDA FY2022 · On disk" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /AMD FY2024/ })).toBeNull();
  });
  it("searches company names and navigates to checkable years using the keyboard", () => {
    render(<Harness companies={[{ registry: "sec", issuer: "NVDA", name: "NVIDIA" }]} />);
    const input = screen.getByLabelText("Search/add company or year");
    fireEvent.change(input, { target: { value: "NVIDIA" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const company = screen.getByRole("button", { name: "NVDA · NVIDIA · 2 years on disk SEC" });
    expect(company).toHaveFocus(); fireEvent.click(company);
    const years = screen.getByLabelText("Search/add company or year");
    expect(years).toHaveFocus();
    fireEvent.keyDown(years, { key: "ArrowDown" });
    const firstYear = screen.getAllByRole("checkbox", { name: /^FY/ })[0];
    expect(firstYear).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getAllByRole("checkbox", { name: /^FY/ })[1]).toHaveFocus();
    fireEvent.click(screen.getByRole("checkbox", { name: "FY2022" }));
    expect(screen.getByRole("checkbox", { name: "FY2022" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: "NVDA FY2022 · On disk" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(years, { key: "Escape" });
    expect(screen.queryByRole("checkbox", { name: "FY2022" })).toBeNull();
  });
  it("stages only missing pairs and synchronizes the exact next draft without stale state", () => {
    const changed = vi.fn(); const download = vi.fn(); render(<Harness changed={changed} download={download} />);
    enter("NVDA"); enter("2024-2025");
    expect(changed.mock.calls.at(-1)![0].pairs).toEqual([{ registry: "sec", issuer: "NVDA", year: 2024 }]);
    expect(within(screen.getByRole("region", { name: "To be added" })).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Remove NVDA FY2025" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Sync selection" }));
    expect(download).toHaveBeenCalledExactlyOnceWith(acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "sec", issuer: "NVDA", year: 2025 }]));
    expect(changed.mock.calls.at(-1)![0]).toEqual(download.mock.calls[0][0]);
  });
  it("supports repeated checks, removes pending entries and keeps downloaded selection", () => {
    render(<Harness />); enter("NVDA"); enter("2024-2025");
    fireEvent.click(screen.getByRole("checkbox", { name: "FY2025" }));
    expect(screen.queryByRole("button", { name: "Remove NVDA FY2025" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "FY2025" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove NVDA FY2025" }));
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
    enter("2023,2025");
    fireEvent.click(screen.getByRole("button", { name: "Clear pending" }));
    expect(screen.getByRole("button", { name: "Sync selection" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
  });
  it("merges selected missing pairs into the pending plan with registry prerequisites", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "005930 FY2023 · Missing source" }));
    expect(screen.getByRole("region", { name: "To be added" })).toHaveTextContent("DART downloads need DART_API_KEY in .env.");
    expect(screen.queryByText("EDGAR downloads need SEC_USER_AGENT in .env.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Select everything on disk" }));
    expect(screen.getByRole("button", { name: "005930 FY2023 · Missing source" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "false");
  });
  it("accepts supported mixed codes and bounded year ranges without selecting them before sync", () => {
    const changed = vi.fn(); const download = vi.fn(); render(<Harness sources={[]} changed={changed} download={download} />);
    enter("AMD,000660"); enter("2023-2024");
    expect(changed).not.toHaveBeenCalled();
    expect(within(screen.getByRole("region", { name: "To be added" })).getAllByRole("listitem")).toHaveLength(4);
    fireEvent.click(screen.getByRole("button", { name: "Sync selection" }));
    expect(download.mock.calls[0][0].pairs).toEqual([{ registry: "sec", issuer: "AMD", year: 2023 }, { registry: "sec", issuer: "AMD", year: 2024 }, { registry: "dart", issuer: "000660", year: 2023 }, { registry: "dart", issuer: "000660", year: 2024 }]);
  });
  it("does not commit search text on blur and blocks invalid input until corrected", () => {
    const changed = vi.fn(); render(<Harness changed={changed} />);
    const input = screen.getByLabelText("Search/add company or year");
    fireEvent.change(input, { target: { value: "???" } }); fireEvent.blur(input);
    expect(input).toHaveValue("???"); expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a company from the supported catalog.");
    enter("NVDA"); enter("2025-2024");
    expect(screen.getByRole("alert")).toHaveTextContent("Use a four-digit year");
    expect(screen.getByRole("button", { name: "Sync selection" })).toBeDisabled();
    expect(changed).not.toHaveBeenCalled();
  });
  it("deduplicates repeated staging and keeps partial multi-document years pending", () => {
    render(<Harness sources={[source("NVDA", 2024), { ...source("NVDA", 2024, false), document_id: "second" }]} />);
    enter("NVDA"); enter("2024"); enter("2024");
    expect(within(screen.getByRole("region", { name: "To be added" })).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "NVDA FY2024 · Missing source" })).toHaveTextContent("1/2");
  });
  it("collapses large groups and preserves a sparse selection on inventory refresh", () => {
    const changed = vi.fn(); const sources = Array.from({ length: 10 }, (_, index) => source(`C${index}`, 2024));
    const { rerender } = render(<Harness sources={sources} changed={changed} />);
    expect(screen.getAllByRole("group")).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: "Show all companies (10)" }));
    fireEvent.click(screen.getByRole("button", { name: "C9 FY2024 · On disk" }));
    rerender(<Harness sources={[...sources, source("MSFT", 2024)]} changed={changed} />);
    expect(screen.getByRole("button", { name: "C9 FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "MSFT FY2024 · On disk" })).toHaveAttribute("aria-pressed", "false");
    expect(changed).toHaveBeenCalledOnce();
  });
  it("disables selection, search, pending removal and synchronization in read-only mode", () => {
    render(<Harness disabled initialPairs={[{ registry: "dart", issuer: "005930", year: 2023 }]} />);
    expect(screen.getByRole("button", { name: "AMD FY2023 · On disk" })).toBeDisabled();
    expect(screen.getByLabelText("Search/add company or year")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove 005930 FY2023" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sync selection" })).toBeDisabled();
  });
});


it("rejects unsupported codes even when local source rows contain that issuer", () => {
  const download = vi.fn();
  render(<Harness sources={[source("MSFT", 2024)]} download={download} />);
  enter("MSFT");
  expect(screen.getByLabelText("Search/add company or year")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Choose a company from the supported catalog.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Sync selection" })).toBeDisabled();
  expect(download).not.toHaveBeenCalled();
});


it("includes a selected damaged source in Sync and clears recovery after verification", () => {
  const download = vi.fn();
  const damaged = { ...source("NVDA", 2024), ready: false, can_redownload: true, blocker: "Download it again in Filings" };
  const healthy = { ...source("AMD", 2023), can_redownload: false };
  const initialPairs: AcquisitionPair[] = [
    { registry: "sec", issuer: "NVDA", year: 2024 },
    { registry: "sec", issuer: "AMD", year: 2023 },
  ];
  const { rerender } = render(<Harness sources={[damaged, healthy]} initialPairs={initialPairs} download={download} />);
  expect(screen.getByRole("status")).toHaveTextContent("Selected on disk: 2 · To download: 1");
  const pending = screen.getByRole("region", { name: "To be added" });
  expect(within(pending).getAllByRole("listitem")).toHaveLength(1);
  expect(within(pending).getByRole("button", { name: "Remove NVDA FY2024" })).toBeVisible();
  const sync = screen.getByRole("button", { name: "Sync selection" });
  expect(sync).toBeEnabled();
  fireEvent.click(sync);
  expect(download).toHaveBeenCalledExactlyOnceWith(acquisitionDraft(initialPairs));
  rerender(<Harness sources={[{ ...damaged, ready: true, can_redownload: false, blocker: null }, healthy]} initialPairs={initialPairs} download={download} />);
  expect(screen.getByRole("status")).toHaveTextContent("Selected on disk: 2 · To download: 0");
  expect(within(pending).queryByRole("listitem")).toBeNull();
  expect(sync).toBeDisabled();
  expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
});

it.each([
  { onDisk: false, staged: false }, { onDisk: false, staged: true },
  { onDisk: true, staged: false }, { onDisk: true, staged: true },
])("excludes conflicting sources from Sync with $onDisk on disk and $staged staged", ({ onDisk, staged }) => {
  const download = vi.fn();
  const conflict = { ...source("NVDA", 2024, onDisk), ready: false, can_redownload: false, blocker: "Conflicting primary sources" };
  render(<Harness sources={[conflict]} initialPairs={staged ? [] : [{ registry: "sec", issuer: "NVDA", year: 2024 }]} download={download} />);
  if (staged) { enter("NVDA"); enter("2024"); }
  expect(screen.getByRole("status")).toHaveTextContent("To download: 0");
  expect(within(screen.getByRole("region", { name: "To be added" })).queryByRole("listitem")).toBeNull();
  const sync = screen.getByRole("button", { name: "Sync selection" });
  expect(sync).toBeDisabled();
  fireEvent.click(sync);
  expect(download).not.toHaveBeenCalled();
});
