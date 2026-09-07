import { describe, expect, it } from "vitest";
import { acquisitionBatches, acquisitionDraft, selectedSourceState, type SourceInventory } from "./source-selection";

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


it("preserves a sparse selection without introducing the other company/year combinations", () => {
  const draft = acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "sec", issuer: "AMD", year: 2023 }]);
  const state = selectedSourceState(rows, draft);
  expect(state.selected.map((row) => row.document_id)).toEqual(["NVDA-FY2024", "AMD-FY2023"]);
  expect(state.complete).toBe(true);
  expect(state.excluded).toHaveLength(2);
  expect(acquisitionBatches(state.pairs)).toEqual([
    { registry: "sec", identifiers: ["AMD"], years: [2023] },
    { registry: "sec", identifiers: ["NVDA"], years: [2024] },
  ]);
});

it("batches matching year sets while preserving registry and incomplete-year identity", () => {
  const partial = [...rows, { ...rows[0], document_id: "NVDA-FY2023-extra", on_disk: false }];
  const draft = acquisitionDraft([
    { registry: "sec", issuer: "NVDA", year: 2023 }, { registry: "sec", issuer: "AMD", year: 2023 },
    { registry: "dart", issuer: "005930", year: 2023 },
  ]);
  const state = selectedSourceState(partial, draft);
  expect(state.missingPairs).toEqual([{ registry: "sec", issuer: "NVDA", year: 2023 }, { registry: "dart", issuer: "005930", year: 2023 }]);
  expect(state.complete).toBe(false);
  expect(acquisitionBatches(state.pairs)).toEqual([
    { registry: "sec", identifiers: ["AMD", "NVDA"], years: [2023] },
    { registry: "dart", identifiers: ["005930"], years: [2023] },
  ]);
  expect(selectedSourceState(rows, { identifiers: "NVDA", years: "2024", pairs: [] }).selected).toEqual([]);
});
