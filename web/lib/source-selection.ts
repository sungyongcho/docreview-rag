import { readStoredValue, writeStoredValue } from "./storage";
import type { CorpusSnapshot } from "@/lib/types";
import type { AcquisitionForm, AcquisitionPair } from "@/components/build-pipeline";
import type { AcquisitionCompany } from "./acquisition-catalog";
import { acquisitionRegistry } from "./acquisition-catalog";

export type SourceInventory = NonNullable<CorpusSnapshot["sources"]>[number];

/** Keep registry and exact company/year identity distinct across draft operations. */
export function pairKey(pair: AcquisitionPair): string {
  return `${pair.registry}:${pair.issuer.toUpperCase()}:${pair.year}`;
}

/** Preserve explicit pairs, interpreting only legacy drafts as a company/year product. */
export function acquisitionPairs(draft: AcquisitionForm, sources: SourceInventory[] = []): AcquisitionPair[] {
  const identifiers = [...new Set(draft.identifiers.split(/[\s,]+/).filter(Boolean).map((value) => value.toUpperCase()))];
  const years = [...new Set(draft.years.split(/[\s,]+/).filter(Boolean).map(Number))];
  const pairs = draft.pairs ?? identifiers.flatMap((issuer) => years.map((year) => ({
    registry: sources.find((row) => row.issuer.toUpperCase() === issuer)?.registry ?? acquisitionRegistry(issuer), issuer, year,
  })));
  return [...new Map(pairs.map((pair) => {
    const normalized = { ...pair, issuer: pair.issuer.trim().toUpperCase() };
    return [pairKey(normalized), normalized];
  })).values()];
}

/** Keep legacy display fields consistent while retaining the exact sparse selection. */
export function acquisitionDraft(pairs: AcquisitionPair[]): AcquisitionForm {
  const selected = acquisitionPairs({ identifiers: "", years: "", pairs });
  return {
    identifiers: [...new Set(selected.map((pair) => pair.issuer))].sort().join(" "),
    years: [...new Set(selected.map((pair) => pair.year))].sort((a, b) => a - b).join(" "),
    pairs: selected,
  };
}

/** Batch only companies with identical selected years; never introduce extra combinations. */
export function acquisitionBatches(pairs: AcquisitionPair[]) {
  const companies = new Map<string, { registry: AcquisitionPair["registry"]; issuer: string; years: Set<number> }>();
  for (const pair of pairs) {
    const key = `${pair.registry}:${pair.issuer}`;
    const entry = companies.get(key) ?? { registry: pair.registry, issuer: pair.issuer, years: new Set<number>() };
    entry.years.add(pair.year); companies.set(key, entry);
  }
  const groups = new Map<string, { registry: AcquisitionPair["registry"]; identifiers: string[]; years: number[] }>();
  for (const company of [...companies.values()].sort((a, b) => (a.registry === b.registry ? a.issuer.localeCompare(b.issuer) : a.registry === "sec" ? -1 : 1))) {
    const years = [...company.years].sort((a, b) => a - b);
    const key = `${company.registry}:${years.join(",")}`;
    const group = groups.get(key) ?? { registry: company.registry, identifiers: [], years };
    group.identifiers.push(company.issuer); groups.set(key, group);
  }
  return [...groups.values()];
}

/** Resolve exact selected pairs, including partial or absent inventory records. */
export function selectedSourceState(sources: SourceInventory[], draft: AcquisitionForm) {
  const pairs = acquisitionPairs(draft, sources);
  const keys = new Set(pairs.map(pairKey));
  const unique = [...new Map(sources.map((row) => [`${row.registry}:${row.document_id}`, row])).values()];
  const selected = unique.filter((row) => keys.has(pairKey({ registry: row.registry, issuer: row.issuer, year: row.fiscal_year })));
  const missingPairs = pairs.filter((pair) => {
    const rows = selected.filter((row) => row.registry === pair.registry && row.issuer.toUpperCase() === pair.issuer && row.fiscal_year === pair.year);
    return !rows.length || rows.some((row) => !row.on_disk);
  });
  const downloadPairs = pairs.filter((pair) => {
    const rows = selected.filter((row) => row.registry === pair.registry && row.issuer.toUpperCase() === pair.issuer && row.fiscal_year === pair.year);
    return (!rows.length || rows.some((row) => !row.on_disk || row.can_redownload === true))
      && !rows.some((row) => row.ready === false && row.can_redownload === false);
  });
  const present = selected.filter((row) => row.on_disk);
  const excluded = unique.filter((row) => row.on_disk && !selected.includes(row));
  const blocked = selected.filter((row) => row.on_disk && row.ready === false);
  return { pairs, selected, present, excluded, blocked, downloadPairs, missingPairs, missing: missingPairs.map((pair) => `${pair.issuer} FY${pair.year}`), complete: pairs.length > 0 && present.length > 0 && missingPairs.length === 0 && blocked.length === 0 };
}

/** Group unique documents into registry/company rows shared by both preparation steps. */
export function sourceSelectionRows(sources: SourceInventory[], pairs: AcquisitionPair[], companies: AcquisitionCompany[], selectedOnly = false) {
  const unique = [...new Map(sources.map((source) => [`${source.registry}:${source.document_id}`, source])).values()];
  const selected = new Set(pairs.map(pairKey));
  const cells = new Map<string, { pair: AcquisitionPair; documents: SourceInventory[] }>();
  for (const source of unique) {
    const pair = { registry: source.registry, issuer: source.issuer.toUpperCase(), year: source.fiscal_year };
    const key = pairKey(pair);
    if (selectedOnly && !selected.has(key)) continue;
    if (!cells.has(key)) cells.set(key, { pair, documents: [] });
    cells.get(key)!.documents.push(source);
  }
  for (const pair of pairs) if (!cells.has(pairKey(pair))) cells.set(pairKey(pair), { pair, documents: [] });
  return (["sec", "dart"] as const).map((registry) => {
    const registryCells = [...cells.values()].filter((cell) => cell.pair.registry === registry);
    const issuers = [...new Set(registryCells.map((cell) => cell.pair.issuer))].sort();
    return { registry, rows: issuers.map((issuer) => {
      const names = new Map<string, number>();
      for (const source of unique) if (source.registry === registry && source.issuer.toUpperCase() === issuer && source.name?.trim()) names.set(source.name.trim(), (names.get(source.name.trim()) ?? 0) + 1);
      const name = companies.find((company) => company.registry === registry && company.issuer.toUpperCase() === issuer)?.name?.trim()
        || [...names.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] || "";
      return { issuer, label: `${issuer}${name && name !== issuer ? ` · ${name}` : ""}`, cells: registryCells.filter((cell) => cell.pair.issuer === issuer).sort((a, b) => a.pair.year - b.pair.year) };
    }) };
  });
}


const ACQUISITION_DRAFT_KEY = "docreview:acquisition-draft:v1";

/** Restore explicit choices only within the same server reset revision, including an empty choice. */
export function loadAcquisitionDraft(revision: string): AcquisitionForm | null {
  const raw = readStoredValue(ACQUISITION_DRAFT_KEY);
  if (!raw) return null;
  try {
    const saved: unknown = JSON.parse(raw);
    if (!saved || typeof saved !== "object" || !("revision" in saved) || saved.revision !== revision || !("pairs" in saved) || !Array.isArray(saved.pairs)) return null;
    const pairs = saved.pairs;
    if (!pairs.every((p) => p && typeof p === "object" && ["sec", "dart"].includes(p.registry) && typeof p.issuer === "string" && Number.isInteger(p.year) && p.year >= 1900 && p.year <= 2100)) return null;
    return acquisitionDraft(pairs);
  } catch { return null; }
}

/** Keep pending and downloaded choices independent of inventory refreshes. */
export function saveAcquisitionDraft(revision: string, draft: AcquisitionForm): void {
  writeStoredValue(ACQUISITION_DRAFT_KEY, JSON.stringify({ revision, pairs: acquisitionPairs(draft) }));
}
