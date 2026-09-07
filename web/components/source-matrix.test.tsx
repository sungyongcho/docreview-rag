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
  return { document_id: `${issuer}-${year}`, registry: /^\d{6}$/.test(issuer) ? "dart" : "sec", issuer, fiscal_year: year, on_disk: onDisk, name, manifest: "manifest.json" };
}
const inventory = [source("NVDA", 2024), source("005930", 2023, false, "Samsung"), source("AMD", 2023), source("NVDA", 2022)];

/** Keep the matrix controlled and expose the exact sparse selection used by downstream steps. */
function Harness({ sources = inventory, initialPairs = [] as AcquisitionPair[], companies = [] as AcquisitionCompany[], changed = vi.fn(), download = vi.fn(), disabled = false }) {
  const [draft, setDraft] = useState<AcquisitionForm>(acquisitionDraft(initialPairs));
  return <SourceMatrix sources={sources} companies={companies} acquisition={draft} onChange={(next) => { changed(next); setDraft(next); }} disabled={disabled} onDownload={download} downloadDisabled={false} />;
}

/** Add codes and year/range syntax through the actual add-only controls. */
function add(codes: string, years: string) {
  fireEvent.change(screen.getByLabelText("Tickers / stock codes"), { target: { value: codes } });
  fireEvent.change(screen.getByLabelText("Fiscal years"), { target: { value: years } });
  fireEvent.click(screen.getByRole("button", { name: "Add to selection" }));
}

describe("company and year source matrix", () => {
  it("focuses an existing company without requiring a year or selecting extra cells", () => {
    const changed = vi.fn(); render(<Harness changed={changed} />);
    fireEvent.change(screen.getByLabelText("Tickers / stock codes"), { target: { value: "NVDA" } });
    fireEvent.click(screen.getByRole("button", { name: "Find company" }));
    expect(screen.getByRole("button", { name: "NVDA FY2022 · On disk" })).toHaveFocus();
    expect(changed).not.toHaveBeenCalled();
  });

  it("sorts registry/company/year rows and uses one catalog-first display name", () => {
    render(<Harness sources={[...inventory, source("INTC", 2021, true, "Intel"), source("INTC", 2022, true, "Intel"), source("INTC", 2024, true, "INTEL CORP")]} companies={[{ registry: "sec", issuer: "INTC", name: "Intel Corporation" }]} />);
    const sections = screen.getAllByRole("region").filter((section) => ["SEC", "DART"].includes(section.getAttribute("aria-label") ?? ""));
    expect(sections.map((section) => section.getAttribute("aria-label"))).toEqual(["SEC", "DART"]);
    expect(within(sections[0]).getAllByRole("group").map((row) => row.getAttribute("aria-label"))).toEqual(["AMD", "INTC · Intel Corporation", "NVDA"]);
    expect(within(screen.getByRole("group", { name: "NVDA" })).getAllByRole("button").map((button) => button.textContent)).toEqual(["FY2022On disk", "FY2024On disk"]);
    expect(screen.queryByText(/Available companies/)).toBeNull();
  });
  it("uses deduplicated document-name frequency when the catalog has no name", () => {
    const uncommon = source("INTC", 2024, true, "INTEL CORP");
    render(<Harness sources={[source("INTC", 2021, true, "Intel"), source("INTC", 2022, true, "Intel"), uncommon, { ...uncommon, manifest: "other.json" }, { ...uncommon, manifest: "third.json" }]} />);
    expect(screen.getByRole("group", { name: "INTC · Intel" })).toBeVisible();
  });
  it("toggles sparse cells and row selection without adding a Cartesian product", () => {
    const changed = vi.fn(); render(<Harness changed={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "NVDA FY2024 · On disk" }));
    fireEvent.click(screen.getByRole("button", { name: "AMD FY2023 · On disk" }));
    expect(changed.mock.calls.at(-1)![0].pairs).toHaveLength(2);
    expect(changed.mock.calls.at(-1)![0].pairs).toEqual(expect.arrayContaining([{ registry: "sec", issuer: "AMD", year: 2023 }, { registry: "sec", issuer: "NVDA", year: 2024 }]));
    expect(screen.queryByRole("button", { name: /AMD FY2024/ })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all years for NVDA" }));
    expect(screen.getByRole("button", { name: "NVDA FY2022 · On disk" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all years for NVDA" }));
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "false");
  });
  it("focuses existing pairs and adds only genuinely new years with range syntax", () => {
    const changed = vi.fn(); render(<Harness changed={changed} />);
    add("NVDA", "2024");
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveFocus();
    add("NVDA", "2024-2025");
    expect(changed.mock.calls.at(-1)![0].pairs).toEqual([{ registry: "sec", issuer: "NVDA", year: 2025 }]);
    expect(screen.getByRole("button", { name: "NVDA FY2025 · Missing source" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveLength(1);
  });
  it("shows only selected missing pairs and their registry credential notes in the plan", () => {
    const download = vi.fn(); render(<Harness download={download} />);
    expect(screen.getByRole("button", { name: "Download missing filings" })).toBeDisabled();
    expect(screen.queryByText("DART downloads need DART_API_KEY in .env.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "005930 FY2023 · Missing source" }));
    const plan = screen.getByRole("region", { name: "Download plan" });
    expect(within(plan).getByText(/005930 FY2023/)).toBeVisible();
    expect(within(plan).getByText("DART downloads need DART_API_KEY in .env.")).toBeVisible();
    expect(screen.queryByText("EDGAR downloads need SEC_USER_AGENT in .env.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Download missing filings" })); expect(download).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Select everything on disk" }));
    expect(screen.getByRole("button", { name: "005930 FY2023 · Missing source" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("button", { name: "NVDA FY2024 · On disk" })).toHaveAttribute("aria-pressed", "false");
  });
  it("collapses large registry groups and reveals an existing typed row", () => {
    render(<Harness sources={Array.from({ length: 10 }, (_, index) => source(`C${index}`, 2024))} />);
    expect(screen.getAllByRole("group")).toHaveLength(8);
    expect(screen.getByRole("button", { name: "Show all companies (10)" })).toHaveAttribute("aria-expanded", "false");
    add("C9", "2024");
    expect(screen.getAllByRole("group")).toHaveLength(10);
    expect(screen.getByRole("button", { name: "C9 FY2024 · On disk" })).toHaveFocus();
  });
  it("preserves the edited draft when new source inventory arrives", () => {
    const changed = vi.fn(); const { rerender } = render(<Harness changed={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "AMD FY2023 · On disk" }));
    rerender(<Harness changed={changed} sources={[...inventory, source("MSFT", 2024)]} />);
    expect(changed).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "AMD FY2023 · On disk" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "MSFT FY2024 · On disk" })).toHaveAttribute("aria-pressed", "false");
  });
  it("keeps read-only controls disabled and invalid ranges out of the draft", () => {
    const changed = vi.fn(); const { rerender } = render(<Harness changed={changed} disabled />);
    expect(screen.getByRole("button", { name: "AMD FY2023 · On disk" })).toBeDisabled();
    expect(screen.getByLabelText("Fiscal years")).toBeDisabled();
    rerender(<Harness changed={changed} />);
    fireEvent.change(screen.getByLabelText("Tickers / stock codes"), { target: { value: "NVDA" } });
    fireEvent.change(screen.getByLabelText("Fiscal years"), { target: { value: "2025-2024" } });
    expect(screen.getByRole("button", { name: "Add to selection" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("Use a four-digit year");
    expect(changed).not.toHaveBeenCalled();
  });
});
