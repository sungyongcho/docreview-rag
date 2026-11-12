type Translate = (source: string) => string;

// Registries store the report type in their own words. Only the displayed label changes; the raw
// value stays the filter identity and is never rewritten. A 10-K/A restates only some Items of a
// 10-K, so its label says what it amends instead of leaving an operator to decode the suffix.
const FORM_LABEL_SOURCES: Readonly<Record<string, string>> = {
  "사업보고서": "Annual report",
  "10-K/A": "10-K/A (amendment to a 10-K)",
};

/** Show a registry's report type in the reading language without changing the stored form value. */
export function documentFormLabel(form: string, t: Translate): string {
  return Object.hasOwn(FORM_LABEL_SOURCES, form) ? t(FORM_LABEL_SOURCES[form]) : form;
}

/** Format calendar dates in UTC so the filing day stays unchanged across time zones. */
export function formatFilingDate(value: string | null | undefined, locale: string): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { timeZone: "UTC" }).format(date);
}
