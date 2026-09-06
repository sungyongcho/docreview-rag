"use client";

import { useEffect, useState } from "react";
import { TokenSelect, type TokenOption } from "@/components/token-select";
import { ACQUISITION_YEARS, type AcquisitionCompany } from "@/lib/acquisition-catalog";
import { companyLabel } from "@/lib/company-labels";
import { useI18n } from "@/lib/i18n";
import type { CorpusDocument } from "@/lib/types";
import "./acquisition-fields.css";

interface Acquisition {
  identifiers: string;
  years: string;
}

interface Props {
  acquisition: Acquisition;
  onChange: (next: Acquisition) => void;
  disabled?: boolean;
  documents?: CorpusDocument[];
  companies?: AcquisitionCompany[];
  onValidityChange?: (valid: boolean) => void;
}

/** Accept explicit fiscal years and small inclusive ranges without rewriting invalid drafts. */
function parseYears(value: string): string[] | null {
  if (/^\d{4}$/.test(value) && Number(value) > 0) return [value];
  const range = value.match(/^(\d{4})-(\d{4})$/);
  if (!range) return null;
  const first = Number(range[1]);
  const last = Number(range[2]);
  if (first <= 0 || last < first || last - first >= 50) return null;
  return Array.from({ length: last - first + 1 }, (_, offset) => String(first + offset).padStart(4, "0"));
}

/** Offer real corpus companies while still allowing acquisition of new filing codes. */
export function AcquisitionFields({ acquisition, onChange, disabled, documents = [], companies: references = [], onValidityChange }: Props) {
  const { t } = useI18n();
  const [companiesValid, setCompaniesValid] = useState(true);
  const [yearsValid, setYearsValid] = useState(true);
  const identifiers = acquisition.identifiers.split(/[\s,]+/).filter(Boolean);
  const years = acquisition.years.split(/[\s,]+/).filter(Boolean);
  const rows = documents;
  const companies = new Map<string, TokenOption>(references.map((company) => [company.issuer, { value: company.issuer, label: companyLabel(company.issuer, company.name), badge: { label: company.registry.toUpperCase(), tone: company.registry === "sec" ? "blue" : "amber" } }]));
  for (const document of rows) {
    if (!companies.has(document.issuer) || document.issuer_name?.trim()) companies.set(document.issuer, { value: document.issuer, label: companyLabel(document.issuer, document.issuer_name), badge: { label: document.registry.toUpperCase(), tone: document.registry === "sec" ? "blue" : "amber" } });
  }
  const companyOptions = [...companies.values()].sort((left, right) => left.label.localeCompare(right.label));
  const yearOptions = ACQUISITION_YEARS.map((year) => ({ value: String(year), label: String(year) }));
  const quickYears = yearOptions;

  /** Preserve valid punctuation in SEC tickers and require DART stock codes verbatim. */
  function parseCompany(value: string): string[] | null {
    const normalized = value.toUpperCase();
    return (/^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$/.test(normalized) || /^\d{6}$/.test(value)) ? [normalized] : null;
  }

  const invalidCompanies = identifiers.filter((value) => parseCompany(value) === null);
  const invalidYears = years.filter((value) => !/^\d{4}$/.test(value) || Number(value) <= 0);
  const valid = companiesValid && yearsValid && identifiers.length > 0 && years.length > 0 && invalidCompanies.length === 0 && invalidYears.length === 0;
  useEffect(() => { onValidityChange?.(valid); }, [valid, onValidityChange]);

  return <div className="acquisition-fields">

    <div className="profile-grid">
      <TokenSelect overlayOptions label={t("Tickers / stock codes")} values={identifiers} options={companyOptions} disabled={disabled}
        placeholder={t("Find a company, SEC ticker or DART stock code")}
        hint={companyOptions.length ? t("Available companies: {companies}", { companies: companyOptions.map((option) => option.label).join(" · ") }) : t("Company choices load from the manifest. You can enter a ticker or stock code.")}
        invalidMessage={t("Use a SEC ticker such as NVDA or a six-digit DART stock code such as 005930.")}
        invalidValues={invalidCompanies} parseCustom={parseCompany} onValidityChange={setCompaniesValid}
        onChange={(next) => onChange({ ...acquisition, identifiers: next.join(" ") })} />
      <TokenSelect overlayOptions label={t("Fiscal years")} values={years} options={yearOptions} disabled={disabled}
        placeholder={t("Add a year or range, for example 2023-2025")}
        hint={t("Enter a four-digit year or a range of up to 50 years. Suggestions are optional.")}
        invalidMessage={t("Use a four-digit year or an ascending range of up to 50 years.")}
        invalidValues={invalidYears} parseCustom={parseYears} quickOptions={quickYears} onValidityChange={setYearsValid}
        onChange={(next) => onChange({ ...acquisition, years: next.join(" ") })} />
    </div>
  </div>;
}
