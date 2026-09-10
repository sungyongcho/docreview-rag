"use client";
import { DevelopmentBadge } from "./development-badge";

import { useEffect, useState } from "react";
import { acquisitionGroups, type AcquisitionCompany } from "@/lib/acquisition-catalog";
import { Copy } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { StageId } from "@/lib/pipeline";
import type { ManifestSummary } from "@/lib/types";
import type { AcquisitionForm } from "./build-pipeline";

const DESIGN: Record<StageId, { mechanism: string; tradeoff: string }> = {
  filings: { mechanism: "Preserve original filing bytes; later citations bind to their source SHA-256.", tradeoff: "Source identity makes verification reproducible, so revised source files require revalidation." },
  index: { mechanism: "Registry parsers produce text and table chunks with original character spans.", tradeoff: "Chunk boundaries balance precise citations against enough context to answer." },
  embeddings: { mechanism: "Persist vector model identity alongside every embedding.", tradeoff: "Semantic retrieval crosses languages, but changing the model requires compatible vectors and can incur provider cost." },
  lexical: { mechanism: "BM25 uses term frequency, document frequency, and chunk length per corpus language.", tradeoff: "Exact terms and rare tokens help retrieval; length and frequency settings change the ranking." },
  ask: { mechanism: "RRF combines rank positions from vector and lexical retrieval, not their incompatible raw scores.", tradeoff: "More candidates can improve evidence recall while increasing latency and context size." },
  answer_model: { mechanism: "The model receives retrieved evidence, and citations are validated before the final result.", tradeoff: "Missing support and provider failure are distinct outcomes; neither is replaced by a fabricated answer." },
  evaluate: { mechanism: "Golden source spans and dataset identities make retrieval results reproducible and comparable.", tradeoff: "Retrieval metrics measure evidence finding, not the factual correctness of every generated answer." },
};

function quote(value: string): string { return "'" + value.replaceAll("'", "'\\''") + "'"; }

export function pipelineReferenceCommand(stage: StageId, acquisition: AcquisitionForm, manifest: string, provider: string | null | undefined, question: string, selectionId: string = "", companies: AcquisitionCompany[] = []): string | null {
  const identifiers = acquisition.identifiers.split(/[\s,]+/).filter(Boolean);
  const years = acquisition.years.split(/[\s,]+/).filter(Boolean);
  if (stage === "filings") {
    if (!identifiers.length || !years.length || years.some((year) => !/^\d{4}$/.test(year))) return null;
    return acquisitionGroups(identifiers, companies).map((group) => `rag-corpus ${group.registry === "dart" ? "acquire_dart" : "acquire_edgar"} ${group.identifiers.map((identifier) => `--identifier ${quote(identifier)}`).join(" ")} ${[...new Set(years)].map((year) => `--year ${year}`).join(" ")}`).join("\n");
  }
  if (stage === "index") return manifest && selectionId ? `rag-corpus ingest_manifest --manifest ${quote(manifest)} --selection ${quote(selectionId)}` : null;
  if (stage === "embeddings") return "rag-corpus backfill_embeddings";
  if (stage === "lexical") return "rag-corpus rebuild_bm25";
  if ((stage === "ask") && provider && ["openai", "deterministic", "sbert"].includes(provider) && question.trim()) return `MODE=dev uv run python -m app.cli retrieve --provider ${quote(provider)} --query ${quote(question.trim())}`;
  return null;
}

export function PipelineReference({ stage, acquisition, manifests, provider }: { stage: StageId; acquisition: AcquisitionForm; manifests: ManifestSummary[]; provider?: string | null }) {
  const { t, locale } = useI18n();
  const [manifest, setManifest] = useState("");
  const [selection, setSelection] = useState("");
  const [question, setQuestion] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const selectedManifest = manifests.some((item) => item.valid && item.name === manifest) ? manifest : "";
  const selections = manifests.find((item) => item.name === selectedManifest)?.selections ?? [];
  const selectedSelection = selections.some((item) => item.selection_id === selection) ? selection : "";
  const command = pipelineReferenceCommand(stage, acquisition, selectedManifest, provider, question, selectedSelection, manifests.flatMap((item) => item.issuers ?? []));
  const design = DESIGN[stage];
  useEffect(() => setCopyStatus(""), [command]);
  async function copy() {
    if (!command) return;
    try { await navigator.clipboard.writeText(command); setCopyStatus("Copied"); }
    catch { setCopyStatus("Copy failed. Select the code and copy it manually."); }
  }
  return <details className="pipeline-reference"><summary><span>{t("Implementation and terminal reference")}</span><span className="terminal-reference-badge"><DevelopmentBadge locale={locale} compact /></span></summary>
    <dl className="step-design"><div><dt>{t("Mechanism")}</dt><dd>{t(design.mechanism)}</dd></div><div><dt>{t("Design trade-off")}</dt><dd>{t(design.tradeoff)}</dd></div></dl>
    <a href={`/docreview-rag-agent/docs/${locale}/`} target="_blank" rel="noreferrer noopener">{t("Read the walkthrough")}</a>
    <p>{t("The controls above run a server job. These commands are a separate reference for your terminal; do not run completed work twice.")}</p>
    {stage === "index" && <fieldset className="reference-choices"><legend>{t("CLI manifest reference")}</legend><div role="group" aria-label={t("CLI manifest reference")}>{manifests.filter((item) => item.valid).map((item) => <button type="button" key={item.name} aria-pressed={selectedManifest === item.name} onClick={() => { setManifest(item.name); setSelection(""); setCopyStatus(""); }}>{item.name}</button>)}</div>{!manifests.some((item) => item.valid) && <p className="helper">{t("No valid manifest to ingest.")}</p>}</fieldset>}
    {stage === "index" && <fieldset className="reference-choices"><legend>{t("Processing selection")}</legend><div role="group" aria-label={t("Processing selection")}>{selections.map((item) => <button type="button" key={item.selection_id} aria-pressed={selectedSelection === item.selection_id} onClick={() => setSelection(item.selection_id)}>{item.selection_id}</button>)}</div>{!selections.length && <p className="helper">{t(selectedManifest ? "No processing selections in this manifest." : "Choose a manifest above.")}</p>}</fieldset>}
    {stage === "ask" && <label>{t("CLI question reference")}<input value={question} onChange={(event) => { setQuestion(event.target.value); setCopyStatus(""); }} /><small>{t("Configured embedding provider")}: {provider ?? t("Checking…")}</small></label>}
    {command ? <figure className="code-card"><header><span>bash</span><button type="button" onClick={() => void copy()}><Copy size={14} />{t("Copy code")}</button></header><pre><code>{command}</code></pre><figcaption role="status">{copyStatus && t(copyStatus)}</figcaption></figure> : <p className="helper">{t(["lexical", "answer_model", "evaluate"].includes(stage) ? "Use the application controls for this operation." : "Complete the reference inputs to see an exact command.")}</p>}
    {stage === "filings" && <p className="helper">{t("EDGAR year options expand discovery; other missing filings for the selected tickers may also be downloaded.")}</p>}
    {stage === "embeddings" && <p className="helper">{t("The CLI backfills all pending vectors and then performs a query. The web backfill action does not run that query.")}</p>}
  </details>;
}
