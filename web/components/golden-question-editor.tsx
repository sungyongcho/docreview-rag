"use client";
import { useConfirmation } from "./use-confirmation";

import { ArrowLeft, Check, FileSearch, Plus, Save, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DatasetLock } from "./dataset-lock";
import { useI18n } from "@/lib/i18n";
import { getAdminDocuments, getGoldenEvidence } from "@/lib/api";
import type { components } from "@/lib/api-generated";
import type { AdminDocumentPage } from "@/lib/types";
import "./golden-question-editor.css";

type Evidence = components["schemas"]["GoldenEvidenceChunk"];
export type GoldenFieldError = { location: (string | number)[]; message: string; code?: string };
interface Props {
  filename: string; registry: string; json: string; readOnly: boolean; dirty: boolean; busy: boolean;
  error: string; issues: GoldenFieldError[]; onChange: (json: string) => void;
  onReload?: () => void; onSave: () => void; onBack: () => void; onParsing?: () => void;
  /** Removes the draft question after confirmation; absent for read-only sources. */
  onDelete?: () => void;
}

/** Full-width authoring replaces the list without creating a second page scroll area. */
export function GoldenQuestionEditor(props: Props) {
  const { confirm, confirmationDialog } = useConfirmation();
  const { t } = useI18n();
  const body = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, []);
  const [picker, setPicker] = useState(false);
  const [tag, setTag] = useState("");
  const [previews, setPreviews] = useState<Record<string, Evidence>>({});
  let value: Record<string, unknown> | null = null;
  try { const parsed = JSON.parse(props.json); if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) value = parsed; } catch { /* Keep invalid JSON editable. */ }
  const answers = value && Array.isArray(value.answers) ? value.answers as Record<string, unknown>[] : [];
  const absent = value?.category === "absent";
  const selected = value?.category != null;
  const tags = Array.isArray(value?.tags) ? value.tags as string[] : [];
  const issuesId = "golden-question-issues";
  useEffect(() => {
    if (!props.error && !props.issues.length) return;
    if (body.current) body.current.scrollTop = 0;
    const field = String(props.issues[0]?.location[0] ?? "");
    if (field) {
      const target = Array.from(body.current?.querySelectorAll<HTMLElement>("[data-field]") ?? []).find(element => element.dataset.field === field);
      const disclosure = target?.closest("details");
      if (disclosure) disclosure.open = true;
      target?.focus({ preventScroll: true });
      target?.scrollIntoView?.({ block: "nearest" });
    }
  }, [props.error, props.issues]);
  function patch(update: Record<string, unknown>) { if (value) props.onChange(JSON.stringify({ ...value, ...update }, null, 2)); }
  async function chooseAnswerability(support: boolean) {
    if (!value) return;
    if (!support && (answers.length > 0 || typeof value.reference_answer === "string" && value.reference_answer.trim() && value.reference_answer !== "NOT_IN_DOCS")) {
      if (!await confirm(t("Changing to no evidence removes the reference answer and source spans. Continue?"))) return;
    }
    patch(support ? { category: !selected || absent ? "simple_lookup" : value.category, expected_label: "SUPPORTED", reference_answer: value.reference_answer === "NOT_IN_DOCS" ? "" : value.reference_answer } : { category: "absent", expected_label: "NOT_IN_DOCS", reference_answer: "NOT_IN_DOCS", answers: [] });
  }
  function addTag() {
    const normalized = tag.normalize("NFC").trim();
    if (tags.length >= 30 || !normalized || normalized.length > 64 || /[\p{Cc}\p{Cf}]/u.test(normalized)) return;
    patch({ tags: [...new Set([...tags, normalized])] }); setTag("");
  }
  function addEvidence(chunk: Evidence) {
    setPreviews(current => ({ ...current, [`${chunk.doc_id}:${chunk.source_sha256}:${chunk.start_char}:${chunk.end_char}`]: chunk }));
    const span = { doc_id: chunk.doc_id, source_sha256: chunk.source_sha256, start_char: chunk.start_char, end_char: chunk.end_char };
    if (!answers.some(answer => Object.entries(span).every(([key, item]) => answer[key] === item))) patch({ answers: [...answers, span] });
    setPicker(false);
  }
  function fieldErrors(field: string) {
    return props.issues.filter(issue => String(issue.location[0]) === field).map((issue, index) => <p className="golden-field-error" key={index}>{t(issue.message)}</p>);
  }
  return <section className="golden-question-screen" aria-label={t("Question editor")}>{confirmationDialog}
    <header className="golden-question-header"><button type="button" className="button ghost" onClick={props.onBack} disabled={props.busy}><ArrowLeft size={16} />{t("Question list")}</button>
      <div className="golden-question-meta"><strong>{props.filename}{props.readOnly && <DatasetLock />}</strong><span>{t(props.readOnly ? "Read-only source" : "Editable draft")}{props.dirty ? ` · ${t("Unsaved changes")}` : ""}</span></div>
      {!props.readOnly && <div className="golden-question-actions"><span>{t(props.issues.length ? "Incomplete" : "Saving a draft does not run an evaluation.")}</span>{props.onDelete && <button type="button" className="button danger-button" disabled={props.busy} onClick={() => { void confirm(t("Delete this draft question?"), { confirm: "Yes", cancel: "No", danger: true }).then(approved => { if (approved) props.onDelete?.(); }); }}><Trash2 size={15} />{t("Delete draft")}</button>}<button type="button" className="button primary" disabled={props.busy || !props.dirty || !value} onClick={props.onSave}><Save size={15} />{t(props.busy ? "Saving…" : "Save draft")}</button></div>}
    </header>
    <div ref={body} className="golden-question-body">
      <h2 ref={heading} tabIndex={-1}>{t(picker ? "Select original evidence" : props.readOnly ? "Question details" : "Edit question")}</h2>
      {(props.error || props.issues.length > 0) && <div id={issuesId} role="alert" className="golden-question-alert">{props.error && <p>{t(props.error)}</p>}{props.error.startsWith("Dataset changed") && props.onReload && <button type="button" className="button" onClick={props.onReload}>{t("Reload saved question")}</button>}{props.issues.length > 0 && !props.error && <p>{t("Complete the indicated fields before evaluation. Draft saving remains available.")}</p>}</div>}
      {picker ? <GoldenEvidencePicker registry={props.registry} selected={answers} onSelect={addEvidence} onBack={() => setPicker(false)} onParsing={props.onParsing} /> : <>
        {value && <>
          <label>{t("Question")}<textarea data-field="question" rows={4} readOnly={props.readOnly} value={String(value.question ?? "")} onChange={event => patch({ question: event.target.value })} />{fieldErrors("question")}</label>
          <fieldset className="golden-answerability"><legend>{t("Can the original documents answer this question?")}</legend><div><button type="button" data-field="category" disabled={props.readOnly} aria-pressed={selected && !absent} onClick={() => chooseAnswerability(true)}>{t("Evidence available")}</button><button type="button" disabled={props.readOnly} aria-pressed={absent} onClick={() => chooseAnswerability(false)}>{t("No evidence")}</button></div>{fieldErrors("category")}{fieldErrors("expected_label")}</fieldset>
          {absent && <p className="helper">{t("This question tests whether the system correctly reports that the documents contain no answer.")}</p>}
          {selected && !absent && <>
            <label>{t("Reference answer")}<textarea data-field="reference_answer" rows={5} readOnly={props.readOnly} value={String(value.reference_answer ?? "")} onChange={event => patch({ reference_answer: event.target.value })} />{fieldErrors("reference_answer")}</label>
            <section className="golden-evidence-section"><header><h3>{t("Answer source spans")}</h3>{!props.readOnly && <button data-field="answers" type="button" className="button" onClick={() => setPicker(true)}><FileSearch size={16} />{t("Select evidence from documents")}</button>}</header>{fieldErrors("answers")}{!answers.length && <p className="helper">{t("Choose a document chunk to fill its exact original-source coordinates.")}</p>}
              {answers.map((answer, index) => <article className="golden-selected-evidence" key={index}><div><strong>{String(answer.doc_id ?? "")}</strong><p>{t("chars")} {String(answer.start_char ?? "—")}–{String(answer.end_char ?? "—")}</p>{previews[`${answer.doc_id}:${answer.source_sha256}:${answer.start_char}:${answer.end_char}`] && <p className="golden-evidence-preview">{previews[`${answer.doc_id}:${answer.source_sha256}:${answer.start_char}:${answer.end_char}`].body}</p>}<details><summary>{t("Source coordinates")}</summary><code>{String(answer.source_sha256 ?? "")}</code></details></div>{!props.readOnly && <button type="button" className="icon-button" aria-label={t("Remove source span") + ` ${index + 1}`} onClick={() => patch({ answers: answers.filter((_, i) => i !== index) })}><X size={16} /></button>}</article>)}
            </section>
          </>}
          <details className="golden-question-options" open={props.issues.some(issue => ["note", "tags", "facet"].includes(String(issue.location[0]))) || undefined}><summary>{t("Classification, tags and review note")}</summary><div className="golden-classifications">{selected && !absent && <label>{t("Category")}<select disabled={props.readOnly} value={String(value.category)} onChange={event => patch({ category: event.target.value })}><option value="simple_lookup">{t("Simple lookup")}</option><option value="exact_number">{t("Exact number")}</option><option value="multi_hop">{t("Multi-hop")}</option></select></label>}<label>{t("Facet")}<select disabled={props.readOnly} value={String(value.facet ?? "factual")} onChange={event => patch({ facet: event.target.value })}>{["factual", "comparison", "risk", "policy", "numeric"].map(facet => <option value={facet} key={facet}>{t(facet)}</option>)}</select></label></div>
            <label>{t("Tags")}<div className="golden-tag-chips">{tags.map(item => <span key={item}>{item}{!props.readOnly && <button type="button" aria-label={t("Remove tag") + ` ${item}`} onClick={() => patch({ tags: tags.filter(current => current !== item) })}><X size={12} /></button>}</span>)}</div>{!props.readOnly && <div className="golden-tag-entry"><input data-field="tags" value={tag} maxLength={64} placeholder={t("Korean or English tag · Enter to add")} onChange={event => setTag(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); addTag(); } }} /><button type="button" className="button" onClick={addTag} disabled={!tag.trim() || tags.length >= 30}><Plus size={14} />{t("Add")}</button></div>}{fieldErrors("tags")}</label>
            <label>{t("Reviewer note")}<textarea data-field="note" rows={4} readOnly={props.readOnly} value={String(value.note ?? "")} onChange={event => patch({ note: event.target.value })} />{fieldErrors("note")}</label>
          </details>
        </>}
        <details className="golden-question-options" open={!value || undefined}><summary>{t("Technical details and question JSON")}</summary><p className="helper">{String(value?.id ?? "")} · {String(value?.expected_label ?? "—")}</p>{!props.readOnly && selected && !absent && <button type="button" className="button" onClick={() => patch({ answers: [...answers, { doc_id: "", source_sha256: "", start_char: null, end_char: null }] })}>{t("Add span manually in JSON")}</button>}<label>{t("Single-case JSON")}<textarea className="golden-question-json" rows={10} wrap="off" readOnly={props.readOnly} value={props.json} onChange={event => props.onChange(event.target.value)} /></label></details>
      </>}
    </div>
  </section>;
}

/** Browse parsed originals in bounded pages; selecting a chunk never performs retrieval. */
function GoldenEvidencePicker({ registry, selected, onSelect, onBack, onParsing }: { registry: string; selected: Record<string, unknown>[]; onSelect: (value: Evidence) => void; onBack: () => void; onParsing?: () => void }) {
  const { t } = useI18n();
  const [query, setQuery] = useState(""); const [cursor, setCursor] = useState<string | null>(null);
  const [documents, setDocuments] = useState<AdminDocumentPage | null>(null);
  const [doc, setDoc] = useState<AdminDocumentPage["documents"][number] | null>(null);
  const [chunkQuery, setChunkQuery] = useState(""); const [after, setAfter] = useState(0);
  const [chunks, setChunks] = useState<components["schemas"]["GoldenEvidencePage"] | null>(null);
  const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  useEffect(() => {
    let active = true; setLoading(true); setDocuments(null); setError("");
    const timer = window.setTimeout(() => { void getAdminDocuments(new URLSearchParams({ registry, query, limit: "20", ...(cursor ? { cursor } : {}) })).then(value => { if (active) setDocuments(value); }).catch(() => { if (active) setError("Documents could not be loaded."); }).finally(() => { if (active) setLoading(false); }); }, 200);
    return () => { active = false; window.clearTimeout(timer); };
  }, [registry, query, cursor]);
  useEffect(() => {
    if (!doc) return;
    const controller = new AbortController(); setLoading(true); setError(""); setChunks(null);
    const timer = window.setTimeout(() => { void getGoldenEvidence(doc.doc_id, chunkQuery, after, controller.signal).then(value => { if (!controller.signal.aborted) setChunks(value); }).catch(() => { if (!controller.signal.aborted) setError("Evidence chunks could not be loaded."); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [doc, chunkQuery, after]);
  return <section className="golden-evidence-picker"><button type="button" className="button ghost" onClick={doc ? () => { setDoc(null); setChunks(null); setError(""); } : onBack}><ArrowLeft size={15} />{t(doc ? "Document list" : "Back to question")}</button>{error && <p role="alert">{t(error)}</p>}{loading && <p role="status">{t("Loading…")}</p>}
    {!doc ? <><label>{t("Search documents")}<input value={query} onChange={event => { setQuery(event.target.value); setCursor(null); }} placeholder={t("Company, fiscal year or document")} /></label>{documents?.documents.map(item => <button className="golden-document-choice" type="button" key={item.doc_id} onClick={() => { setDoc(item); setAfter(0); setChunkQuery(""); }}><strong>{item.issuer_name ?? item.issuer} · FY{item.fiscal_year}</strong><span>{item.form} · {item.chunk_count} {t("chunks")}</span></button>)}<div className="action-row"><button type="button" className="button" disabled={!cursor} onClick={() => setCursor(null)}>{t("First page")}</button><button type="button" className="button" disabled={!documents?.next_cursor || loading} onClick={() => setCursor(documents!.next_cursor)}>{t("Next page")}</button></div></> : <><h3>{doc.issuer_name ?? doc.issuer} · FY{doc.fiscal_year}</h3>{doc.chunk_count === 0 ? <><p>{t("Parse and chunk this document before selecting evidence.")}</p>{onParsing && <button type="button" className="button" onClick={onParsing}>{t("Open parsing / chunking")}</button>}</> : <><label>{t("Search chunk text")}<input value={chunkQuery} onChange={event => { setChunkQuery(event.target.value); setAfter(0); }} /></label>{chunks?.chunks.map(chunk => {
      const used = selected.some(span => span.doc_id === chunk.doc_id && span.source_sha256 === chunk.source_sha256 && span.start_char === chunk.start_char && span.end_char === chunk.end_char);
      return <article key={chunk.chunk_id} className="golden-chunk-choice"><header><strong>{chunk.item ?? t("Section")} · {chunk.kind}</strong><span>{chunk.start_char}–{chunk.end_char}</span></header><pre>{chunk.body}</pre><button type="button" className="button" disabled={used} onClick={() => onSelect(chunk)}>{used ? <Check size={14} /> : <Plus size={14} />}{t(used ? "Already selected" : "Use this evidence")}</button></article>;
    })}{chunks && !chunks.chunks.length && <p>{t("No evidence chunks match this search.")}</p>}<div className="action-row"><button type="button" className="button" disabled={!after} onClick={() => setAfter(0)}>{t("First page")}</button><button type="button" className="button" disabled={!chunks?.next_after || loading} onClick={() => setAfter(chunks!.next_after!)}>{t("Next page")}</button></div></>}</>}
  </section>;
}
