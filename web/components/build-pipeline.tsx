"use client";
import { translate, useI18n, type Locale } from "@/lib/i18n";


import { TerminalHandoff } from "@/components/terminal-handoff";
import { PipelineReference } from "@/components/pipeline-reference";
import { DevelopmentBadge } from "@/components/development-badge";
import { WipeRuntime } from "@/components/wipe-runtime";
import { Activity, ArrowDown, ArrowRight, Check, RefreshCw } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { elapsedLabel, JobProgress } from "@/components/job-center";
import { AcquisitionFields } from "@/components/acquisition-fields";
import { acquisitionGroups, acquisitionRegistry, type AcquisitionCompany } from "@/lib/acquisition-catalog";
import { companyLabel } from "@/lib/company-labels";
import type { Pipeline, Stage, StageActionKind, StageStatus } from "@/lib/pipeline";
import { diagnosePreparation } from "@/lib/preparation-diagnostics";
import type { Diagnosis } from "@/lib/preparation-diagnostics";
import { stageStatusLabel } from "@/lib/pipeline";
import type { CorpusDocument, ManifestSummary } from "@/lib/types";

export interface AcquisitionForm {
  identifiers: string;
  years: string;
}

export interface BuildPipelineProps {
  pipeline: Pipeline;
  focusStage?: string | null;
  embeddingProvider?: string | null;
  documents?: CorpusDocument[];
  companies?: AcquisitionCompany[];
  live: boolean;
  busy: boolean;
  canOperateCorpus: boolean;
  acquisition: AcquisitionForm;
  onAcquisitionChange: (next: AcquisitionForm) => void;
  manifests: ManifestSummary[];
  selectedSources?: string[];
  selectedDocumentCount?: number;
  onToggleSource?: (key: string) => void;
  /** Ingested documents per registry, used for the per-manifest "ingested" count. */
  registryCounts?: Record<string, number>;
  /** Runtime flags for the strip; `null` or `undefined` means "not known yet". */
  databaseConnected?: boolean | null;
  schemaStatus?: string | null;
  schemaMessage?: string | null;
  writable?: boolean | null;
  /** "dev key" / "prod key" / "explicit key" / "local" / "off"; `null` while readiness is unknown. */
  answerModel?: string | null;
  /** Local Operations reachable from this build; the strip then offers service buttons instead of commands. */
  operationsAvailable?: boolean;
  onRunOperation?: (commandId: string) => void;
  onCancelJob: (jobId: string) => void;
  onDownload: () => void;
  onIngestAll: () => void;
  onIngest: (manifestName: string, selectionId: string) => void;
  onBackfill: () => void;
  onRebuildBm25: () => void;
  onAsk: () => void;
  onRecheck: () => void;
  onEvaluate: () => void;
  onCompareSnapshots: () => void;
  onOpenDocuments: () => void;
  onOpenJobs: () => void;
  onOpenStatus: () => void;
  onRefresh: () => unknown | Promise<unknown>;
}

const REGISTRY_LABELS: Record<"sec" | "dart", string> = { sec: "SEC EDGAR", dart: "DART" };
const STEP_DEPENDENCIES: Record<Stage["id"], string> = {
  filings: "Start with SEC or DART filings",
  index: "Source files → chunks",
  embeddings: "Chunks → embeddings · parallel with BM25",
  lexical: "Chunks → BM25 · parallel with embeddings",
  ask: "Search indexes + answer engine → cited answer",
  answer_model: "Configure independently before generating answers",
  evaluate: "Search index + golden dataset → evaluation",
};

/** Actions that queue an operator job; they are locked in read-only mode and while a request is in flight. */
const OPERATOR_ACTIONS: ReadonlySet<StageActionKind> = new Set(["acquire", "ingest_all", "embed", "bm25", "evaluate"]);
/** Stages whose work runs only on the local operator build. */
const OPERATOR_STAGES: ReadonlySet<Stage["id"]> = new Set(["filings", "index", "embeddings", "lexical", "evaluate"]);
const READ_ONLY_NOTE = "Runs on the local operator build.";

export function splitList(value: string): string[] {
  return value.split(/[\s,]+/).filter(Boolean);
}

function isApiDown(pipeline: Pipeline): boolean {
  return pipeline.stages.some((stage) => stage.status === "unknown" && stage.statusDetail === "API unavailable");
}

/** Move focus to the disclosure's summary: the details element renders as `display: contents` and has no box to focus. */
function focusSetupSummary(setup: HTMLDetailsElement, scroll = false): void {
  const target = setup.querySelector<HTMLElement>("summary") ?? setup;
  target.focus();
  if (scroll) target.scrollIntoView?.({ block: "nearest" });
}

export function BuildPipeline(props: BuildPipelineProps) {
  const { t, locale } = useI18n();
  const { pipeline } = props;
  const [acquisitionValid, setAcquisitionValid] = useState(true);
  const [selectedChoice, setSelectedId] = useState<Stage["id"] | null>(null);
  const selectedId = selectedChoice ?? pipeline.stages.find((stage) => stage.status === "running")?.id ?? pipeline.next?.id ?? "filings";
  const selected = pipeline.stages.find((stage) => stage.id === selectedId) ?? pipeline.stages[0];


  const focusId = props.focusStage === "setup" ? "setup" : pipeline.stages.find((item) => item.id === props.focusStage || String(item.order) === props.focusStage)?.id;
  useEffect(() => {
    if (focusId === "setup") {
      const setup = document.getElementById("pipeline-setup-checks") as HTMLDetailsElement | null;
      if (setup) { setup.open = true; focusSetupSummary(setup); }
    } else if (focusId) setSelectedId(focusId);
  }, [focusId]);

  function handler(kind: StageActionKind): () => void {
    switch (kind) {
      case "acquire": return props.onDownload;
      case "ingest_all": return props.onIngestAll;
      case "embed": return props.onBackfill;
      case "bm25": return props.onRebuildBm25;
      case "ask": return props.onAsk;
      case "recheck": return props.onRecheck;
      case "evaluate": return props.onEvaluate;
      case "compare": return props.onCompareSnapshots;
    }
  }

  function disabled(kind: StageActionKind): boolean {
    if (OPERATOR_ACTIONS.has(kind) && props.live) {
      if (props.databaseConnected === false || props.schemaStatus === "empty" || props.schemaStatus === "unavailable") return true;
      if (kind !== "acquire" && props.schemaStatus === "drifted") return true;
    }
    if (kind === "acquire" && !acquisitionValid) return true;
    if (!OPERATOR_ACTIONS.has(kind)) return false;
    return pipeline.readOnly || props.busy || (props.live && !props.canOperateCorpus);
  }

  const diagnosis = diagnosePreparation(selected.id === "filings" && props.schemaStatus === "empty" ? "index" : selected.id, pipeline, {
    databaseConnected: props.databaseConnected ?? null,
    schemaStatus: props.schemaStatus ?? null,
    writable: props.writable ?? null,
  });

  function navigatePreparation(target: NonNullable<Diagnosis["returnTo"]>) {
    if (target === "setup") {
      const setup = document.getElementById("pipeline-setup-checks") as HTMLDetailsElement | null;
      if (setup) { setup.open = true; focusSetupSummary(setup, true); }
    } else {
      setSelectedId(target);
    }
  }

  return (
    <div className="build-pipeline panel-stack">
      <div className="pipeline-toolbar">
      <WipeRuntime enabled={props.live && !pipeline.readOnly} />
      <RuntimeStrip
        pipeline={pipeline}
        live={props.live}
        databaseConnected={props.databaseConnected ?? null}
        returnStage={selected.id}
        schemaStatus={props.schemaStatus ?? null}
        schemaMessage={props.schemaMessage ?? null}
        writable={props.writable ?? null}
        answerModel={props.answerModel ?? null}
        onRunOperation={props.operationsAvailable && props.onRunOperation ? props.onRunOperation : null}
        onRefresh={props.onRefresh}
      />
      </div>
      <div className="pipeline-workspace">
      <section className="pipeline-map" aria-label={t("Data workflow")}>
        <header className="pipeline-map-heading"><h2>{t("Data workflow")}</h2><span>{t("Select a step")}</span></header>
        <div className="pipeline-graph" data-tour="stage-list">
          {pipeline.stages.map((stage) => <button key={stage.id} data-help={`build.stage.${stage.id}`} className={`pipeline-node ${stage.id} ${stage.status}`} type="button" aria-label={t("Select {p0}", { p0: t(stage.title) })} aria-pressed={selectedId === stage.id} aria-controls="pipeline-execution" onClick={() => setSelectedId(stage.id)}>
            <span className="pipeline-node-number">{stage.order}</span><strong>{t(stage.title)}</strong><small className="pipeline-node-status"><i className="status-beacon" aria-hidden="true" />{t(stage.statusDetail || stageStatusLabel(stage.status))}</small>
            <span className="pipeline-dependency">{t(STEP_DEPENDENCIES[stage.id])}</span>
          </button>)}
          <span className="pipeline-flow-link source-link" aria-hidden="true"><ArrowDown size={16} /></span>
          <span className="pipeline-flow-link index-link">{t("Parallel search indexes")}<ArrowDown size={16} aria-hidden="true" /></span>
          <span className="pipeline-flow-link answer-link">{t("Search indexes + answer engine → cited answer")}</span>
          <span className="pipeline-flow-link evaluation-link">{t("Search index + golden dataset → evaluation")}</span>
        </div>
        <div className="pipeline-guidance" data-tour="next-step" data-help="build.next-step">
          <span>{t(pipeline.corpusReady ? "Corpus ready" : "Recommended next step")}</span>
          {pipeline.next ? <button type="button" onClick={() => setSelectedId(pipeline.next!.id)}>{t(pipeline.next.title)}<ArrowRight size={15} /></button> : <button type="button" onClick={props.onAsk}>{t("Ask a question")}<ArrowRight size={15} /></button>}
          <p>{t(pipeline.next?.hint || "Ask a question, inspect the evaluation results, or run another evaluation.")}</p>
        </div>
      </section>
      <section id="pipeline-execution" className="pipeline-execution" aria-label={t("Selected step execution")}>
        <header><span>{t("Selected step")}</span><h2>{selected.order}. {t(selected.title)}</h2><button type="button" className="button ghost" onClick={props.onOpenJobs}>{t("Open Jobs")}</button></header>
        <p className="helper">{selected.blockedBy ? t("Required first: {p0}", { p0: t(pipeline.stages.find((item) => item.id === selected.blockedBy)?.title ?? selected.blockedBy) }) : t("Review the inputs before starting. Selecting a step does not execute it.")}</p>
        {selected.id === "embeddings" && <p className="notice">{t("OpenAI embedding may incur cost for all pending chunks in the database. Check the provider and counts before running.")}</p>}
      <ol className="stage-list" role="list" data-tour="stage-list">
        {[selected].map((stage) => (
          <StageCard
            key={stage.id}
            stage={stage}
            recovery={props.live && !pipeline.readOnly ? <TerminalHandoff diagnosis={diagnosis} technicalDetail={props.schemaStatus === "drifted" && selected.id !== "filings" && selected.id !== "answer_model" ? props.schemaMessage : null} steps={diagnosis.terminalSteps} blocking={diagnosis.state === "blocked"} onNavigate={diagnosis.returnTo !== selected.id ? navigatePreparation : undefined} onRefresh={props.onRefresh} /> : null}
            isNext={pipeline.next?.id === stage.id}
            readOnly={pipeline.readOnly}
            handler={handler}
            disabled={disabled}
            acquisition={props.acquisition}
            onAcquisitionChange={props.onAcquisitionChange}
            documents={props.documents ?? []}
            companies={props.companies ?? []}
            onAcquisitionValidityChange={setAcquisitionValid}
            manifests={props.manifests}
            selectedSources={props.selectedSources}
            selectedDocumentCount={props.selectedDocumentCount}
            onToggleSource={props.onToggleSource}
            registryCounts={props.registryCounts ?? {}}
            onIngest={props.onIngest}
            onOpenDocuments={props.onOpenDocuments}
            onOpenJobs={props.onOpenJobs}
            onOpenStatus={props.onOpenStatus}
            onCancelJob={props.onCancelJob}
          />
        ))}
      </ol>
        <details className="execution-console"><summary>{t("Actual server job record")}</summary>{selected.job ? <pre>{JSON.stringify({ job_id: selected.job.job_id, status: selected.job.status, stage: selected.job.stage, current: selected.job.current, total: selected.job.total, message: selected.job.message }, null, 2)}</pre> : <p className="helper">{t("No job has been started for this step.")}</p>}</details>
        <PipelineReference stage={selected.id} acquisition={props.acquisition} manifests={props.manifests} provider={props.embeddingProvider} />
      </section>
      </div>
    </div>
  );
}

interface RuntimeStripProps {
  pipeline: Pipeline;
  live: boolean;
  databaseConnected: boolean | null;
  returnStage: string;
  schemaStatus: string | null;
  schemaMessage: string | null;
  writable: boolean | null;
  answerModel: string | null;
  /** Set only when Local Operations can run the fix for a problem from the browser. */
  onRunOperation: ((commandId: string) => void) | null;
  onRefresh: () => unknown | Promise<unknown>;
}

interface RuntimeProblem {
  reason: string;
  guidance?: string;
  /** Command line shown when no local operator is attached. */
  fix: string;
  /** Operations registry commands that perform the fix, in order. */
  commands: Array<{ id: string; label: string }>;
}

function RuntimeStrip({ pipeline, live, databaseConnected, returnStage, schemaStatus, schemaMessage, writable, answerModel, onRunOperation, onRefresh }: RuntimeStripProps) {
  const { t, locale } = useI18n();
  if (pipeline.readOnly) {
    return <span className="runtime-readonly" data-help="build.runtime">{t("Read-only portfolio · stored snapshots + live retrieval")}</span>;
  }
  const apiDown = isApiDown(pipeline);
  const known = databaseConnected !== null || schemaStatus !== null;
  const items: string[] = [apiDown ? "API unavailable" : known ? "API ok" : "Checking runtime…"];
  if (databaseConnected === true) items.push("Database connected");
  if (schemaStatus === "compatible") items.push("Schema compatible");
  if (writable === true) items.push("Writable");
  if (answerModel) items.push(`Answer model: ${answerModel}`);
  if (!apiDown && known && databaseConnected === null && schemaStatus === null && writable === null) items.push("Checking runtime…");

  const problems: RuntimeProblem[] = [];
  if (databaseConnected === false) {
    problems.push({ reason: schemaMessage || "The database is not connected.", fix: "rag-dev up --build -d", commands: [{ id: "db-start", label: "Start database" }] });
  } else if (schemaStatus === "empty") {
    problems.push({ reason: "The local database needs its initial schema.", fix: "uv run python -m scripts.schema_status prepare", commands: [] });
  } else if (schemaStatus === "drifted") {
    problems.push({ reason: "Database schema is incompatible", guidance: "Preserve this database. Create a separate recovery checkout with its own ports and volume, then open the printed URL and re-check the blocked step.", fix: `uv run python -m scripts.schema_status recover --return-stage ${returnStage}`, commands: [] });
  }
  if (schemaStatus === "unavailable") { problems.push({ reason: schemaMessage || "Database schema is unavailable", fix: "uv run python -m scripts.schema_status check", commands: [] }); }
  if (writable === false) {
    problems.push({ reason: "data/ is not writable, so downloads and ingest cannot save files. Set HOST_GID=$(id -g) in .env, then rebuild the app.", fix: 'HOST_GID="$(id -g)" rag-dev up --build -d', commands: [{ id: "app-start", label: "Rebuild app" }] });
  }

  return (
    <details id="pipeline-setup-checks" className="runtime-disclosure" data-help="build.runtime">
      <summary tabIndex={0}><Activity size={15} /><span>{t(apiDown ? "API unavailable" : problems.length ? "Runtime needs attention" : known ? "Runtime connected" : "Checking runtime…")}</span></summary>
      <div className="runtime-strip">
      <div className="runtime-items">{items.map((item, index) => <Fragment key={t(item)}>{index > 0 && <span className="sep" aria-hidden="true">·</span>}<span>{t(item)}</span></Fragment>)}</div>
      <div className="runtime-actions">
        {live && <button className="button ghost" type="button" onClick={() => void onRefresh()}><RefreshCw size={14} />{t("Check schema")}</button>}
        {live && onRunOperation && !problems.length && <button className="button ghost" type="button" onClick={() => onRunOperation("app-start")}>{t("Rebuild app")}</button>}
      </div>
      {problems.map((problem) => (
        <div className="notice error" role="alert" key={problem.fix || problem.reason}>
          <p>{t(problem.reason)}</p>
          {problem.guidance && <p>{t(problem.guidance)}</p>}
          {onRunOperation && problem.commands.length > 0
            ? <div className="action-row">{problem.commands.map((command) => <button className="button" type="button" key={command.id} onClick={() => onRunOperation(command.id)}>{t(command.label)}</button>)}</div>
            : problem.fix && <code>{problem.fix}</code>}
        </div>
      ))}
      </div>
    </details>
  );
}

function ActionButton({ stage, primary, handler, disabled }: { stage: Stage; primary: boolean; handler: (kind: StageActionKind) => () => void; disabled: (kind: StageActionKind) => boolean }) {
  const { t, locale } = useI18n();
  if (!stage.action) return null;
  const { kind, label } = stage.action;
  return <button className={primary ? "button primary" : "button"} type="button" disabled={disabled(kind)} onClick={handler(kind)}>{t(label)}</button>;
}

function StatusPill({ status, detail }: { status: StageStatus; detail: string }) {
  const { t, locale } = useI18n();
  const label = stageStatusLabel(status);
  return <span className={`stage-status ${status}`}><i className="status-beacon" aria-hidden="true" />{t(label)}{detail && detail !== label && <em>{t(detail)}</em>}</span>;
}

interface StageCardProps {
  recovery?: ReactNode;
  stage: Stage;
  isNext: boolean;
  readOnly: boolean;
  handler: (kind: StageActionKind) => () => void;
  disabled: (kind: StageActionKind) => boolean;
  acquisition: AcquisitionForm;
  documents: CorpusDocument[];
  companies: AcquisitionCompany[];
  onAcquisitionValidityChange: (valid: boolean) => void;
  onAcquisitionChange: (next: AcquisitionForm) => void;
  manifests: ManifestSummary[];
  selectedSources?: string[];
  selectedDocumentCount?: number;
  onToggleSource?: (key: string) => void;
  registryCounts: Record<string, number>;
  onIngest: (manifestName: string, selectionId: string) => void;
  onOpenDocuments: () => void;
  onOpenJobs: () => void;
  onOpenStatus: () => void;
  onCancelJob: (jobId: string) => void;
}

function manifestSummary(manifest: ManifestSummary, registryCounts: Record<string, number>, locale: Locale): string {
  if (!manifest.valid) return translate(locale, "invalid manifest");
  const parts = [translate(locale, "{count} entries", { count: (manifest.documents ?? 0).toLocaleString(locale) }), translate(locale, "{count} on disk", { count: (manifest.sources_present ?? 0).toLocaleString(locale) })];

  return parts.join(" · ");
}

function StageCard({ recovery, stage, isNext, readOnly, handler, disabled, acquisition, onAcquisitionChange, documents, companies, onAcquisitionValidityChange, manifests, selectedSources = [], selectedDocumentCount = 0, onToggleSource, registryCounts, onIngest, onOpenDocuments, onOpenJobs, onOpenStatus, onCancelJob }: StageCardProps) {
  const { t, locale } = useI18n();
  const job = stage.job;
  const showHint = Boolean(stage.hint) && stage.hint !== job?.message;
  const readOnlyNote = readOnly && OPERATOR_STAGES.has(stage.id);
  const identifiers = splitList(acquisition.identifiers);
  const companyNames = (code: string) => companyLabel(code, documents.find((document) => document.issuer === code)?.issuer_name ?? companies.find((company) => company.issuer === code)?.name);
  const years = splitList(acquisition.years).map((year) => `FY${year}`);

  return (
    <li>
      <article id={`stage-${stage.order}`} className={`stage-card ${stage.status}${isNext ? " next" : ""}`} data-help={`build.stage.${stage.id}`}>
        <div className={`stage-index ${stage.status}`} aria-hidden="true">{stage.status === "done" ? <Check size={15} /> : stage.order}</div>
        <div className="stage-body">
          <div className="stage-head">
            <StatusPill status={stage.status} detail={stage.statusDetail} />
            {OPERATOR_STAGES.has(stage.id) && <DevelopmentBadge locale={locale} compact />}
          </div>
          <p className="stage-description">{t(stage.description)}</p>
          {stage.numbers.length > 0 && (
            <p className="stage-numbers">
              {stage.numbers.map((item, index) => <Fragment key={`${index}:${t(item)}`}>{index > 0 && <span className="sep" aria-hidden="true">·</span>}<span>{t(item)}</span></Fragment>)}
            </p>
          )}
          {stage.id === "filings" && (
            <p className="stage-summary">{[acquisitionGroups(identifiers, companies).map((group) => REGISTRY_LABELS[group.registry]).join(" / "), identifiers.map(companyNames).join(", ") || t("no tickers"), years.join(", ") || t("no fiscal years")].join(" · ")}</p>
          )}
          {job && (
            <div className="stage-job">
              <JobProgress job={job} />
              <p className="helper">{job.message} · {elapsedLabel(job, locale)}</p>
            </div>
          )}
          {showHint && <p className="stage-hint">{t(stage.hint)}</p>}
          {recovery}
          {readOnlyNote && <p className="stage-note">{t(READ_ONLY_NOTE)}</p>}
          <p className="stage-why"><strong>{t("Why it matters:")}</strong> {t(stage.why)}</p>
          {stage.id === "filings" && (
            <details className="stage-advanced" open>
              <summary>{t("Change…")}</summary>
              <div>
                <AcquisitionFields acquisition={acquisition} onChange={onAcquisitionChange} disabled={readOnly} documents={documents} companies={companies} onValidityChange={onAcquisitionValidityChange} />
                <p className="helper">{identifiers.some((code) => acquisitionRegistry(code, companies) === "sec") && t("EDGAR downloads need SEC_USER_AGENT in .env.")} {identifiers.some((code) => acquisitionRegistry(code, companies) === "dart") && t("DART downloads need DART_API_KEY in .env.")}</p>
              </div>
            </details>
          )}
          {stage.id === "index" && (
            <details className="stage-advanced" open>
              <summary>{t("Change…")}</summary>
              <div>
                <p role="status">{t("Selected documents: {count}", { count: selectedDocumentCount })}</p>
                {manifests.map((manifest) => (
                  <div className="manifest-row" key={manifest.name}>
                    <span>{manifest.name} · {manifest.registries.join(" / ").toUpperCase()} · {manifestSummary(manifest, registryCounts, locale)}</span>
                    {manifest.selections.map((selection) => {
                      const key = `${manifest.name}:${selection.selection_id}`;
                      return <div key={key}><label><input type="checkbox" checked={selectedSources.includes(key)} onChange={() => onToggleSource?.(key)} disabled={!manifest.valid || disabled("ingest_all")} />{selection.selection_id} · {selection.document_ids.length} {t("documents")}</label><button className="button" type="button" aria-label={t("Ingest {p0}", { p0: `${manifest.name} / ${selection.selection_id}` })} disabled={!manifest.valid || disabled("ingest_all")} onClick={() => onIngest(manifest.name, selection.selection_id)}>{t("Ingest")}</button></div>;
                    })}
                  </div>
                ))}
                {!manifests.length && <p className="helper">{t("No manifests found in data/corpus.")}</p>}
                <p className="helper">{t("Ingest upserts documents from each manifest in order and recomputes BM25. Run Backfill embeddings afterwards (step 3).")}</p>
              </div>
            </details>
          )}
          <div className="stage-actions">
            {job && job.can_cancel && <button className="button" type="button" onClick={() => onCancelJob(job.job_id)}>{t("Cancel")}</button>}
            {stage.action && <ActionButton stage={stage} primary={isNext} handler={handler} disabled={disabled} />}
            {stage.id === "index" && <button className="button ghost" type="button" onClick={onOpenDocuments}>{t("Open Documents")}</button>}
            {stage.id === "answer_model" && stage.status !== "readonly" && <button className="button ghost" type="button" onClick={onOpenStatus}>{t("Open System status")}</button>}
            {job && <button className="button ghost" type="button" onClick={onOpenJobs}>{t("View all jobs")}</button>}
          </div>
        </div>
      </article>
    </li>
  );
}
