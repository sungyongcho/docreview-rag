"use client";
import { RefreshCw } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";

import { useConfirmation } from "@/components/use-confirmation";
import { getAmendedPeriods, reviewAmendment, withdrawAmendmentReview } from "@/lib/api";
import { evidenceHoldSentence, itemLabel, reportPeriodLabel } from "@/lib/evidence-holds";
import { documentFormLabel, formatFilingDate } from "@/lib/filing-labels";
import { useI18n } from "@/lib/i18n";
import type { AmendedReportPeriod, AmendmentDecision, FilingVersion } from "@/lib/types";
import "./amended-filings.css";

type AmendmentAction = AmendmentDecision["action"];

/** The three things a review can decide for one Item, in the order the form offers them. */
const ACTIONS: ReadonlyArray<{ action: AmendmentAction; label: string; meaning: string }> = [
  { action: "replace", label: "Replace", meaning: "Use the amendment's text for this Item instead of the report's." },
  { action: "add", label: "Add", meaning: "Use both the report's text and the amendment's text for this Item." },
  { action: "withhold", label: "Withhold", meaning: "Use neither filing's text for this Item." },
];

interface AmendedFilingsProps {
  /** Administrator mode. The public surface renders nothing here and never calls the route. */
  live: boolean;
  /** Load only while the surrounding tab is shown. */
  active?: boolean;
  /** Changes when a corpus job ends, so a newly found or newly parsed filing is read again. */
  refreshRevision?: string;
}

/** One report period is one registry, issuer and period end date. */
function periodKey(period: Pick<AmendedReportPeriod, "registry" | "issuer" | "report_period">): string {
  return `${period.registry}:${period.issuer}:${period.report_period}`;
}

/** Keep a refusal's own words: the server says which Item or field it would not accept. */
function failureText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

/**
 * Report periods that hold an amendment or a corrected report, and the review an amendment needs.
 *
 * A later whole report replaces the earlier one by itself. An amendment restates only some
 * Items, so an administrator decides here what each of its Items does; until then the whole
 * report period stays out of evidence, and this panel says so.
 */
export function AmendedFilings({ live, active = true, refreshRevision = "" }: AmendedFilingsProps) {
  const { t } = useI18n();
  const headingId = useId();
  const [periods, setPeriods] = useState<AmendedReportPeriod[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!live || !active) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getAmendedPeriods(controller.signal).then((rows) => {
      if (!controller.signal.aborted) setPeriods(rows);
    }).catch((reason) => {
      if (!controller.signal.aborted) setError(failureText(reason));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [live, active, refreshRevision, refresh]);

  if (!live) return null;

  /** A review answers with its report period as it stands now; show that instead of reloading the list. */
  function replacePeriod(next: AmendedReportPeriod) {
    setPeriods((current) => current?.map((period) => periodKey(period) === periodKey(next) ? next : period) ?? [next]);
  }

  const held = periods?.filter((period) => period.hold).length ?? 0;
  return (
    <section className="surface amended-filings" aria-labelledby={headingId} aria-busy={loading}>
      <div className="amended-heading">
        <div>
          <h2 id={headingId}>{t("Amended filings")}</h2>
          <p className="helper">{t("A report period can have more than one filing: a report and a later amendment or corrected report. This list shows which of them is used as evidence, and which amendment still needs your review.")}</p>
          {periods !== null && periods.length > 0 && <p className="helper" role="status">{t("{periods} report periods · {held} on hold", { periods: periods.length, held })}</p>}
        </div>
        <button className="button ghost" type="button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={14} aria-hidden="true" />{t("Refresh")}</button>
      </div>
      {error && <div className="amended-error" role="alert"><p>{t("Could not load amended filings.")}</p><p>{error}</p><button className="button" type="button" onClick={() => setRefresh((value) => value + 1)}>{t("Retry")}</button></div>}
      {periods === null
        ? loading && <p className="amended-status" role="status">{t("Loading amended filings…")}</p>
        : periods.length === 0
          ? <p className="amended-status">{t("No report period has an amendment or a corrected report. When Check for newer filings finds one, it appears here.")}</p>
          : <ul className="amended-periods">{periods.map((period) => <ReportPeriod key={periodKey(period)} period={period} onChange={replacePeriod} />)}</ul>}
    </section>
  );
}

/** One report period: what holds it, and each of its filings in the order the policy applies them. */
function ReportPeriod({ period, onChange }: { period: AmendedReportPeriod; onChange: (next: AmendedReportPeriod) => void }) {
  const { t, locale } = useI18n();
  // A held period opens by itself; it is the one that needs the operator.
  const [open, setOpen] = useState(Boolean(period.hold));
  const withheld = [...new Set(period.versions.flatMap((version) => version.review?.decisions.filter((decision) => decision.action === "withhold").map((decision) => decision.item) ?? []))];
  return (
    <li className="amended-period" data-held={period.hold ? "true" : "false"}>
      <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>
          <span className="amended-period-name">{reportPeriodLabel(period, t)}</span>
          <span className="amended-period-meta">{t("Report period ending {date}", { date: formatFilingDate(period.report_period, locale) })} · {t("{count} filings", { count: period.versions.length })}</span>
          <span className={`coverage-badge ${period.hold ? "partial" : "complete"}`}>{t(period.hold ? "On hold" : "In use")}</span>
        </summary>
        {period.hold && <p className="amended-hold" role="note">{evidenceHoldSentence({ registry: period.registry, reason: period.hold, items: withheld }, t)}</p>}
        <ol className="amended-versions" aria-label={t("Filings of {period}", { period: reportPeriodLabel(period, t) })}>
          {period.versions.map((version) => <Filing key={version.filing_id} period={period} version={version} onChange={onChange} />)}
        </ol>
      </details>
    </li>
  );
}

/** One filing of a report period: what is stored from it, its recorded review, and the review actions. */
function Filing({ period, version, onChange }: { period: AmendedReportPeriod; version: FilingVersion; onChange: (next: AmendedReportPeriod) => void }) {
  const { t, locale } = useI18n();
  const { confirm, confirmationDialog } = useConfirmation();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const docId = version.doc_id;
  const amendment = version.kind === "amendment";
  const numberLocale = locale === "ko" ? "ko-KR" : "en-US";
  const form = documentFormLabel(version.form, t);

  /** Withdrawing puts the whole report period back on hold, so it is confirmed first. */
  async function withdraw() {
    if (!docId || busy) return;
    if (!await confirm(t("Withdraw this review? The whole report period goes back on hold: nothing from it is used as evidence until the amendment is reviewed again."), { confirm: "Withdraw review", danger: true })) return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    try {
      onChange(await withdrawAmendmentReview(docId));
      setEditing(false);
      setNotice("Review withdrawn. This report period is on hold again.");
    } catch (reason) {
      setFailure(failureText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="amended-version">
      <header>
        <strong>{form}</strong>
        <span className="mode-badge">{t(amendment ? "Amendment" : "Report")}</span>
        <span className={`coverage-badge ${version.current ? "complete" : "missing"}`}>{t(version.current ? "Used as evidence now" : "Not used as evidence now")}</span>
      </header>
      <dl className="amended-version-meta">
        <div><dt>{t("Filed")}</dt><dd>{formatFilingDate(version.filing_date, locale)}</dd></div>
        <div><dt>{t("Filing identity")}</dt><dd><code>{version.filing_id}</code></dd></div>
        <div><dt>{t("Document")}</dt><dd>{docId ? <code>{docId}</code> : t("Not downloaded or not parsed yet")}</dd></div>
        <div><dt>{t("Source")}</dt><dd>{version.source_url && /^https?:\/\//i.test(version.source_url) ? <a href={version.source_url} target="_blank" rel="noreferrer">{t("Open original filing")}</a> : "—"}</dd></div>
      </dl>
      {!docId && <p className="helper">{t(amendment
        ? "This amendment is on record but is not downloaded or not parsed yet, so it has no Items to review. Download it in Build › Pipeline › Filings, then run Parse & chunk."
        : "This report is on record but is not downloaded or not parsed yet, so none of its text is stored. Download it in Build › Pipeline › Filings, then run Parse & chunk.")}</p>}
      {docId && version.parse_status && version.parse_status !== "parsed" && <p className="amended-warning" role="note">{t("Parse status: {status}. The parser could not find where every Item starts and ends, so the Items listed here may be incomplete.", { status: t(version.parse_status) })}</p>}
      {docId && <div className="amended-items">
        <h4>{t("Items stored from this filing")}</h4>
        {version.items.length
          ? <ul>{version.items.map((entry) => <li key={entry.item}><span>{itemLabel(period.registry, entry.item)}</span><span>{t("{count} chunks", { count: entry.chunks.toLocaleString(numberLocale) })}</span></li>)}</ul>
          : <p className="helper">{t("No Item was recognised in this filing.")}</p>}
        <p className="helper">{t("Outside every Item: {count} chunks", { count: version.unnumbered_chunks.toLocaleString(numberLocale) })}</p>
      </div>}
      {version.review && <section className="amended-review" aria-label={t("Recorded review of {form}", { form })}>
        <h4>{t("Recorded review")}</h4>
        <p>{t("Reviewed by {reviewer} on {date}", { reviewer: version.review.reviewer, date: new Date(version.review.reviewed_at).toLocaleString(numberLocale) })}</p>
        <p className="amended-rationale"><span>{t("Rationale")}</span>{version.review.rationale}</p>
        <ul>{version.review.decisions.map((decision) => {
          const choice = ACTIONS.find((entry) => entry.action === decision.action);
          return <li key={decision.item}><span>{itemLabel(period.registry, decision.item)}</span><strong>{choice ? t(choice.label) : decision.action}</strong><span>{choice ? t(choice.meaning) : ""}</span></li>;
        })}</ul>
      </section>}
      {amendment && docId && !version.review && !editing && <p className="amended-warning" role="note">{t("This amendment has not been reviewed. Until it is, nothing from this report period is used as evidence.")}</p>}
      {amendment && docId && !editing && <div className="action-row">
        <button className="button primary" type="button" disabled={busy} onClick={() => { setFailure(null); setNotice(null); setEditing(true); }}>{t(version.review ? "Edit review" : "Review this amendment")}</button>
        {version.review && <button className="button danger-button" type="button" disabled={busy} onClick={() => void withdraw()}>{t("Withdraw review")}</button>}
      </div>}
      {amendment && docId && editing && <ReviewForm
        registry={period.registry}
        docId={docId}
        version={version}
        formLabel={form}
        onCancel={() => setEditing(false)}
        onSaved={(next) => { onChange(next); setEditing(false); setFailure(null); setNotice("Review saved."); }}
      />}
      {failure && <p className="amended-refusal" role="alert">{failure}</p>}
      {notice && <p className="helper" role="status">{t(notice)}</p>}
      {confirmationDialog}
    </li>
  );
}

interface ReviewFormProps {
  registry: string;
  docId: string;
  version: FilingVersion;
  formLabel: string;
  onCancel: () => void;
  onSaved: (next: AmendedReportPeriod) => void;
}

/**
 * Decide what every Item of one amendment does, with who decided and why.
 *
 * It starts from the recorded review when there is one, because saving replaces that review.
 * An Item the amendment has no text for can be added: deciding it retires the report's text.
 */
function ReviewForm({ registry, docId, version, formLabel, onCancel, onSaved }: ReviewFormProps) {
  const { t, locale } = useI18n();
  const formId = useId();
  const numberLocale = locale === "ko" ? "ko-KR" : "en-US";
  const stored = new Map(version.items.map((entry) => [entry.item, entry.chunks]));
  const [reviewer, setReviewer] = useState(version.review?.reviewer ?? "");
  const [rationale, setRationale] = useState(version.review?.rationale ?? "");
  const [choices, setChoices] = useState<Record<string, AmendmentAction>>(() => Object.fromEntries(version.review?.decisions.map((decision) => [decision.item, decision.action]) ?? []));
  // Items a recorded review decided although the amendment has no text for them stay on the form.
  const [extraItems, setExtraItems] = useState<string[]>(() => version.review?.decisions.map((decision) => decision.item).filter((item) => !stored.has(item)) ?? []);
  const [newItem, setNewItem] = useState("");
  const [saving, setSaving] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const items = [...version.items.map((entry) => entry.item), ...extraItems];
  const undecided = items.filter((item) => !choices[item]);
  const candidate = newItem.trim().replace(/^item\s+/i, "").toUpperCase();
  const complete = reviewer.trim() !== "" && rationale.trim() !== "" && undecided.length === 0;

  function addItem() {
    if (!candidate || items.includes(candidate)) return;
    setExtraItems((current) => [...current, candidate]);
    setNewItem("");
  }

  function removeItem(item: string) {
    setExtraItems((current) => current.filter((entry) => entry !== item));
    setChoices((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== item)));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving || !complete) return;
    setSaving(true);
    setRefusal(null);
    try {
      onSaved(await reviewAmendment(docId, {
        reviewer: reviewer.trim(),
        rationale: rationale.trim(),
        decisions: items.map((item) => ({ item, action: choices[item] })),
      }));
    } catch (reason) {
      setRefusal(failureText(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="amended-review-form" aria-label={t("Review of {form}", { form: formLabel })} onSubmit={(event) => void save(event)}>
      <p className="helper">{t("Decide what each Item of this amendment does to the report it amends. Saving replaces any earlier review, and the decisions take effect at once.")}</p>
      <dl className="amended-choice-guide">{ACTIONS.map((entry) => <div key={entry.action}><dt>{t(entry.label)}</dt><dd id={`${formId}-${entry.action}`}>{t(entry.meaning)}</dd></div>)}</dl>
      <div className="amended-form-fields">
        <label>{t("Reviewer")}<input value={reviewer} required autoComplete="name" onChange={(event) => setReviewer(event.target.value)} /></label>
        <label>{t("Rationale")}<textarea value={rationale} required rows={3} placeholder={t("Why each Item was decided this way")} onChange={(event) => setRationale(event.target.value)} /></label>
      </div>
      {!version.items.length && <p className="helper">{t("No Item was recognised in this amendment, so there is nothing of its own to decide. Add an Item below only to stop the report's text for it being used.")}</p>}
      {items.map((item) => {
        const label = itemLabel(registry, item);
        const chunks = stored.get(item);
        return (
          <fieldset className="amended-item-choice" key={item}>
            <legend>{label}</legend>
            <span className="amended-item-count">{chunks === undefined ? t("No text in this amendment") : t("{count} chunks", { count: chunks.toLocaleString(numberLocale) })}</span>
            {ACTIONS.map((entry) => <label key={entry.action}><input type="radio" name={`${formId}-${item}`} value={entry.action} checked={choices[item] === entry.action} aria-describedby={`${formId}-${entry.action}`} onChange={() => setChoices((current) => ({ ...current, [item]: entry.action }))} />{t(entry.label)}</label>)}
            {chunks === undefined && <button className="button ghost" type="button" aria-label={t("Remove {item}", { item: label })} onClick={() => removeItem(item)}>{t("Remove")}</button>}
          </fieldset>
        );
      })}
      <div className="amended-add-item">
        <label>{t("Add an Item this amendment does not contain")}<input value={newItem} placeholder={t("Item number, for example 9A")} onChange={(event) => setNewItem(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addItem(); } }} /></label>
        <button className="button" type="button" disabled={!candidate || items.includes(candidate)} onClick={addItem}>{t("Add Item")}</button>
        <p className="helper">{t("The amendment has no text for an Item added here. Choosing Replace or Withhold for it stops the report's text for that Item being used.")}</p>
      </div>
      {!complete && <p className="helper">{t("Enter the reviewer and the rationale, and choose what every Item does, before saving.")}</p>}
      {refusal && <p className="amended-refusal" role="alert">{refusal}</p>}
      <div className="action-row">
        <button className="button primary" type="submit" disabled={saving || !complete}>{t(saving ? "Saving…" : "Save review")}</button>
        <button className="button" type="button" disabled={saving} onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}
