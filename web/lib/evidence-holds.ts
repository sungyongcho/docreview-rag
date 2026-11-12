import type { EvidenceHold } from "./types";

type Translate = (source: string, values?: Record<string, string | number>) => string;

/**
 * What each hold means and what ends it, one sentence per reason.
 *
 * The amended-filings panel, the retrieval notice and the answer notice all read these,
 * so the three cannot describe one hold differently. The record is also open to reasons
 * a newer server reports before this bundle's generated contract lists them.
 */
const HOLD_SENTENCES: Record<EvidenceHold["reason"], string> & Readonly<Record<string, string>> = {
  amendment_pending: "An amendment to this report has not been reviewed yet, so nothing from this report period is used as evidence until an administrator reviews it under Build › Documents › Amended filings.",
  report_missing: "Only an amendment is on record for this report period and the report it amends was never collected, so nothing from the period is used as evidence until an administrator runs Check for newer filings and then Parse & chunk for this company and year.",
  order_unknown: "Two filings of this report period cannot be put in order, so nothing from the period is used as evidence until an administrator runs Check for newer filings, which reads their filing times from the registry again.",
  not_indexed: "The latest report for this report period is known but not downloaded and parsed yet, so nothing from the period is used as evidence until an administrator downloads that report and runs Parse & chunk.",
  item_withheld: "A review of an amendment withheld some Items of this report period, so neither filing's text for those Items is used as evidence until an administrator edits the review under Build › Documents › Amended filings.",
  replaced: "Everything this search covers of this report period was replaced by a later filing that the search leaves out, so none of it is used as evidence; widen the search to include the later filing.",
};

/** The same hold when the server names the withheld Items. */
const ITEMS_WITHHELD_SENTENCE = "A review of an amendment withheld {items} of this report period, so neither filing's text for them is used as evidence until an administrator edits the review under Build › Documents › Amended filings.";

/** The same for a search that leaves out the filing which replaced the named Items. */
const ITEMS_REPLACED_SENTENCE = "A later filing that this search leaves out replaced {items} of this report period, so the text this search covers for them is not used as evidence; widen the search to include the later filing.";

/** A reason this bundle has no wording for still says that evidence is held, never nothing. */
const UNKNOWN_HOLD_SENTENCE = "A later filing keeps this report period's text out of evidence.";

/**
 * Read the holds a review run answered without from its report reasons.
 *
 * A run that held nothing carries no `evidence_held` reason, so the answer is `undefined`.
 */
export function heldEvidence(reasons: ReadonlyArray<{ code: string; holds?: EvidenceHold[] }> | undefined): EvidenceHold[] | undefined {
  return reasons?.find((reason) => reason.code === "evidence_held")?.holds;
}

/** Name one section code the way its registry's citations do: EDGAR writes `Item 7`, DART a bare numeral. */
export function itemLabel(registry: string, item: string): string {
  return registry === "sec" ? `Item ${item}` : item;
}

/** Name the report period a hold or a list row is about, e.g. `SEC · AMD · FY 2025`. */
export function reportPeriodLabel(period: Pick<EvidenceHold, "registry" | "issuer" | "fiscal_year">, t: Translate): string {
  return `${period.registry.toUpperCase()} · ${period.issuer} · ${t("FY {year}", { year: period.fiscal_year })}`;
}

/** Turn one hold into the sentence every surface shows for it: what it means and what ends it. */
export function evidenceHoldSentence(hold: Pick<EvidenceHold, "registry" | "reason"> & { items?: readonly string[] }, t: Translate): string {
  const named = { item_withheld: ITEMS_WITHHELD_SENTENCE, replaced: ITEMS_REPLACED_SENTENCE }[hold.reason as string];
  if (named && hold.items?.length) {
    return t(named, { items: hold.items.map((item) => itemLabel(hold.registry, item)).join(", ") });
  }
  return t(Object.hasOwn(HOLD_SENTENCES, hold.reason) ? HOLD_SENTENCES[hold.reason] : UNKNOWN_HOLD_SENTENCE);
}
