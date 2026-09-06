import type { CorpusSnapshot } from "@/lib/types";
import type { AcquisitionForm } from "@/components/build-pipeline";

export type SourceInventory = NonNullable<CorpusSnapshot["sources"]>[number];

/** Resolve every requested company/year, including pairs absent from any manifest. */
export function selectedSourceState(sources: SourceInventory[], draft: AcquisitionForm) {
  const identifiers = [...new Set(draft.identifiers.split(/[\s,]+/).filter(Boolean).map((value) => value.toUpperCase()))];
  const years = [...new Set(draft.years.split(/[\s,]+/).filter(Boolean).map(Number))];
  const unique = [...new Map(sources.map((row) => [`${row.registry}:${row.document_id}`, row])).values()];
  const selected = unique.filter((row) => identifiers.includes(row.issuer.toUpperCase()) && years.includes(row.fiscal_year));
  const missing = identifiers.flatMap((issuer) => years.flatMap((year) => {
    const rows = selected.filter((row) => row.issuer.toUpperCase() === issuer && row.fiscal_year === year);
    return !rows.length || rows.some((row) => !row.on_disk) ? [`${issuer} FY${year}`] : [];
  }));
  const present = selected.filter((row) => row.on_disk);
  const excluded = unique.filter((row) => row.on_disk && !selected.includes(row));
  return { selected, present, excluded, missing, complete: identifiers.length > 0 && years.length > 0 && present.length > 0 && missing.length === 0 };
}
