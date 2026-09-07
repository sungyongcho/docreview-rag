import type { CorpusSnapshot } from "@/lib/types";
import type { AcquisitionForm, AcquisitionPair } from "@/components/build-pipeline";
import { acquisitionRegistry } from "./acquisition-catalog";

export type SourceInventory = NonNullable<CorpusSnapshot["sources"]>[number];

/** Keep registry and exact company/year identity distinct across draft operations. */
function pairKey(pair: AcquisitionPair): string {
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
  const present = selected.filter((row) => row.on_disk);
  const excluded = unique.filter((row) => row.on_disk && !selected.includes(row));
  return { pairs, selected, present, excluded, missingPairs, missing: missingPairs.map((pair) => `${pair.issuer} FY${pair.year}`), complete: pairs.length > 0 && present.length > 0 && missingPairs.length === 0 };
}
