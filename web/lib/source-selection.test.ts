import { describe, expect, it } from "vitest";
import { acquisitionBatches, acquisitionDraft, loadAcquisitionDraft, saveAcquisitionDraft, selectedSourceState, type SourceInventory } from "./source-selection";

const rows: SourceInventory[] = ["NVDA", "AMD"].flatMap((issuer) => [2023, 2024].map((year) => ({ manifest: "manifest.json", document_id: `${issuer}-FY${year}`, filing_id: `${issuer}-FY${year}`, can_redownload: false, registry: "sec", issuer, name: issuer, fiscal_year: year, ready: true, on_disk: true })));

describe("current source selection", () => {
  it("resolves four downloaded sources without duplicate manifest memberships", () => {
    const state = selectedSourceState([...rows, rows[0]], acquisitionDraft(rows.map(row => ({ registry: row.registry, issuer: row.issuer, year: row.fiscal_year }))));
    expect(state.complete).toBe(true);
    expect(state.present).toHaveLength(4);
  });
  it("names absent company/year pairs and downloaded exclusions", () => {
    const state = selectedSourceState(rows, acquisitionDraft([2022, 2024].map(year => ({ registry: "sec", issuer: "NVDA", year }))));
    expect(state.complete).toBe(false);
    expect(state.missing).toEqual(["NVDA FY2022"]);
    expect(state.present).toHaveLength(1);
    expect(state.excluded).toHaveLength(3);
  });
  it("never marks an empty draft or missing file complete", () => {
    expect(selectedSourceState(rows, acquisitionDraft([])).complete).toBe(false);
    expect(selectedSourceState(rows.map((row) => ({ ...row, on_disk: false, ready: false, can_redownload: true })), acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2024 }])).missing).toEqual(["NVDA FY2024"]);
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
  const partial = [...rows, { ...rows[0], document_id: "NVDA-FY2023-extra", filing_id: "NVDA-FY2023-extra", on_disk: false, ready: false, can_redownload: true }];
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


it("persists sparse and empty explicit choices until the server reset revision changes", () => {
  const draft = acquisitionDraft([{ registry: "sec", issuer: "NVDA", year: 2019 }, { registry: "dart", issuer: "000660", year: 2022 }]);
  saveAcquisitionDraft("reset-a", draft);
  expect(loadAcquisitionDraft("reset-a")).toEqual(draft);
  expect(loadAcquisitionDraft("reset-b")).toBeNull();
  saveAcquisitionDraft("reset-a", acquisitionDraft([]));
  expect(loadAcquisitionDraft("reset-a")?.pairs).toEqual([]);
});

it("keeps conflicting downloaded primaries distinct from pending downloads", () => {
  const blocked = { ...rows[0], ready: false, blocker: "Conflicting primary sources" };
  const state = selectedSourceState([blocked], acquisitionDraft([{ registry: "sec", issuer: blocked.issuer, year: blocked.fiscal_year }]));
  expect(state.missingPairs).toEqual([]);
  expect(state.blocked).toEqual([blocked]);
  expect(state.complete).toBe(false);
});


it("includes recoverable on-disk sources in downloads without labeling them missing", () => {
  const damaged = { ...rows[0], ready: false, can_redownload: true, blocker: "Download it again in Filings" };
  const pair = { registry: "sec" as const, issuer: damaged.issuer, year: damaged.fiscal_year };
  const state = selectedSourceState([damaged, rows[1]], acquisitionDraft([pair, { registry: "sec", issuer: rows[1].issuer, year: rows[1].fiscal_year }]));
  expect(state.present).toHaveLength(2);
  expect(state.missingPairs).toEqual([]);
  expect(state.downloadPairs).toEqual([pair]);
  expect(state.complete).toBe(false);
});

it.each([false, true])("never downloads a conflicting filing even when on_disk is %s", (onDisk) => {
  const conflict = { ...rows[0], on_disk: onDisk, ready: false, can_redownload: false, blocker: "Conflicting primary sources" };
  const pair = { registry: "sec" as const, issuer: conflict.issuer, year: conflict.fiscal_year };
  const state = selectedSourceState([conflict], acquisitionDraft([pair]));
  expect(state.downloadPairs).toEqual([]);
  expect(state.complete).toBe(false);
});

it("reacquires physically present invalid sources without counting them as missing", () => {
  const invalid = { ...rows[0], ready: false, can_redownload: true, blocker: "Source bytes changed" };
  const absent = { ...rows[1], on_disk: false, ready: false, can_redownload: true };
  const state = selectedSourceState([invalid, absent], acquisitionDraft([
    { registry: "sec", issuer: "NVDA", year: 2023 }, { registry: "sec", issuer: "NVDA", year: 2024 },
    { registry: "dart", issuer: "005930", year: 2024 },
  ]));
  expect(state.present).toEqual([invalid]);
  expect(state.missingPairs).toEqual([{ registry: "sec", issuer: "NVDA", year: 2024 }, { registry: "dart", issuer: "005930", year: 2024 }]);
  expect(state.downloadPairs).toHaveLength(3);
  expect(state.blocked).toEqual([invalid]);
  expect(state.complete).toBe(false);
});
