import type { ManifestSummary } from "@/lib/types";

export type AcquisitionCompany = NonNullable<ManifestSummary["issuers"]>[number];

export const ACQUISITION_YEARS = [2020, 2021, 2022, 2023, 2024];

/** Use known source metadata, with the supported ticker/stock-code syntax for new issuers. */
export function acquisitionRegistry(identifier: string, companies: readonly AcquisitionCompany[] = []): "sec" | "dart" {
  return companies.find((company) => company.issuer === identifier)?.registry ?? (/^\d{6}$/.test(identifier) ? "dart" : "sec");
}

/** Keep a mixed selection while producing one explicit request per source adapter. */
export function acquisitionGroups(identifiers: string[], companies: readonly AcquisitionCompany[] = []) {
  return (["sec", "dart"] as const).map((registry) => ({ registry, identifiers: [...new Set(identifiers)].filter((identifier) => acquisitionRegistry(identifier, companies) === registry) })).filter((group) => group.identifiers.length > 0);
}
