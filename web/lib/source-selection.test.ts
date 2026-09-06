import { describe, expect, it } from "vitest";
import { selectedSourceState, type SourceInventory } from "./source-selection";

const rows: SourceInventory[] = ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, registry: "sec", issuer, name: issuer, fiscal_year: year, on_disk: true })));

describe("current source selection", () => {
  it("resolves four downloaded sources without duplicate manifest memberships", () => {
    const state = selectedSourceState([...rows, rows[0]], { identifiers: "NVDA AMD", years: "2023 2024" });
    expect(state.complete).toBe(true);
    expect(state.present).toHaveLength(4);
  });
  it("names absent company/year pairs and downloaded exclusions", () => {
    const state = selectedSourceState(rows, { identifiers: "NVDA", years: "2022 2024" });
    expect(state.complete).toBe(false);
    expect(state.missing).toEqual(["NVDA FY2022"]);
    expect(state.present).toHaveLength(1);
    expect(state.excluded).toHaveLength(3);
  });
  it("never marks an empty draft or missing file complete", () => {
    expect(selectedSourceState(rows, { identifiers: "", years: "" }).complete).toBe(false);
    expect(selectedSourceState(rows.map((row) => ({ ...row, on_disk: false })), { identifiers: "NVDA", years: "2024" }).missing).toEqual(["NVDA FY2024"]);
  });
});
