import { useI18n } from "@/lib/i18n";


import { AnswerEngineLight, AnswerEngineRows } from "@/components/answer-engine-light";
import { answerEngineStates, answerEngineSummary, type AnswerEngineState } from "@/lib/answer-engine-state";
import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import { TerminalHandoff } from "@/components/terminal-handoff";
import { PipelineReference } from "@/components/pipeline-reference";
import { PipelineNext } from "@/components/pipeline-next";
import { HoverBubble } from "@/components/hover-bubble";
import { DevelopmentBadge } from "@/components/development-badge";
import { DEV_ONLY_NOTE } from "@/lib/dev-mode";
import { DevLockedButton } from "@/components/dev-locked-button";
import type { ScopeFilters } from "@/lib/scope-filters";
import { WipeRuntime } from "@/components/wipe-runtime";
import { Info, CircleAlert, MessageSquare, Server, ChevronDown, Lightbulb, MousePointer2, ArrowDown, ArrowRight, Check, RefreshCw, CircleDollarSign, Clock3 } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { JobProgress } from "@/components/job-center";
import { SourceSelectionGrid } from "@/components/source-selection-grid";
import "./index-selection.css";
import { SourceMatrix, PUBLIC_COMPANIES } from "@/components/source-matrix";
import type { AcquisitionCompany } from "@/lib/acquisition-catalog";
import { acquisitionDraft, pairKey, selectedSourceState, type SourceInventory } from "@/lib/source-selection";
import type { Pipeline, Stage, StageActionKind } from "@/lib/pipeline";
import { diagnosePreparation } from "@/lib/preparation-diagnostics";
import type { Diagnosis } from "@/lib/preparation-diagnostics";
import { stageStatusLabel } from "@/lib/pipeline";
import type { ReviewEngineState, CorpusDocument, ManifestSummary, Readiness } from "@/lib/types";

const PUBLIC_PARSING_NOTE = "PROD does not run parsing or chunking. It uses precomputed results for the scope selected in step 1-1, Filings. Selection is shared with step 1-1; confirm the search scope here.";

export interface AcquisitionPair {
  registry: "sec" | "dart";
  issuer: string;
  year: number;
}

export interface AcquisitionForm {
  identifiers: string;
  years: string;
  pairs: AcquisitionPair[];
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
  evaluationBlockedReason?: string | null;
  evaluationSetup?: (action: ReactNode) => ReactNode;
  evaluationPreparationReady?: boolean;
  acquisition: AcquisitionForm;
  onAcquisitionChange: (next: AcquisitionForm) => void;
  manifests: ManifestSummary[];
  sources?: SourceInventory[];
  onChangeFilings?: () => void;
  onDeleteSources?: (token: string) => Promise<void>;
  sourceDeletionDisabled?: boolean;
  /** Runtime flags for the strip; `null` or `undefined` means "not known yet". */
  databaseConnected?: boolean | null;
  schemaStatus?: string | null;
  schemaMessage?: string | null;
  writable?: boolean | null;
  /** "dev key" / "prod key" / "explicit key" / "local" / "off"; `null` while readiness is unknown. */
  answerModel?: string | null;
  readiness?: Readiness | null;
  localModel?: string | null;
  onOpenLocalSettings?: () => void;
  onLocalPrepared?: (local: ReviewEngineState) => void;
  /** Local Operations reachable from this build; the strip then offers service buttons instead of commands. */
  operationsAvailable?: boolean;
  onRunOperation?: (commandId: string) => void;
  onCancelJob: (jobId: string) => void;
  onDownload: (next?: AcquisitionForm) => void;
  onIngestAll: () => void;
  onBackfill: () => void;
  onRebuildBm25: () => void;
  onAsk: () => void;
  /** Read-only servers turn the company grid into a question scope. */
  publicProgress?: { candidates?: import("@/lib/types").PublicTarget[]; stage: string; checked: string[] };
  onConfirmScope?: () => void;
  onPublicProgressChange?: (progress: { stage: string; checked: string[] }) => void;
  candidates?: import("@/lib/types").PublicTarget[];
  onAskScope?: (filters: ScopeFilters) => void;
  corpusScope?: string;
  onRecheck: () => void;
  onEvaluate: () => void;
  onCompareSnapshots: () => void;
  onOpenDocuments: () => void;
  onOpenJobs: () => void;
  onOpenStatus: () => void;
  onRefresh: () => unknown | Promise<unknown>;
}

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
/** Stages whose work runs only in DEV mode. */
const OPERATOR_STAGES: ReadonlySet<Stage["id"]> = new Set(["filings", "index", "embeddings", "lexical", "evaluate"]);

export function splitList(value: string): string[] {
  return value.split(/[\s,]+/).filter(Boolean);
}

function isApiDown(pipeline: Pipeline): boolean {
  return pipeline.stages.some((stage) => stage.status === "unknown" && stage.statusDetail === "API unavailable");
}

export function BuildPipeline(props: BuildPipelineProps) {
  const { t, locale } = useI18n();
  const { pipeline } = props;
  const answerEngines = answerEngineStates(props.readiness ?? null, props.localModel).filter((engine) => !pipeline.readOnly && LOCAL_ENGINE_VISIBLE || engine.id === "openai");
  const [acquisitionValid, setAcquisitionValid] = useState(true);
  const [selectedChoice, setLocalSelectedId] = useState<Stage["id"] | null>(null);
  const selectedId = (pipeline.readOnly ? props.publicProgress?.stage as Stage["id"] | undefined : undefined) ?? selectedChoice ?? (pipeline.readOnly ? "filings" : null) ?? pipeline.stages.find((stage) => stage.status === "running")?.id ?? pipeline.next?.id ?? "filings";
  const [localChecks, setLocalChecks] = useState<string[]>([]);
  const checks = props.publicProgress?.checked ?? localChecks;
  function setSelectedId(stage: Stage["id"]) {
    setLocalSelectedId(stage);
    if (pipeline.readOnly) props.onPublicProgressChange?.({ stage, checked: checks });
  }
  function saveProgress(stage: Stage["id"], checked: string[]) {
    setLocalSelectedId(stage); setLocalChecks(checked);
    props.onPublicProgressChange?.({ stage, checked });
  }
  const sequence: Stage["id"][] = ["filings", "index", "embeddings", "lexical", "answer_model", "ask"];
  function advance() {
    if (selectedId === "index") props.onConfirmScope?.();
    const next = sequence.slice(sequence.indexOf(selectedId) + 1).find(step => step === "ask" || !checks.includes(step));
    if (next) saveProgress(next, [...new Set([...checks, selectedId])]);
  }
  const selected = pipeline.stages.find((stage) => stage.id === selectedId) ?? pipeline.stages[0];
  const selectedGroup = selected.order <= 4 ? 1 : selected.id === "answer_model" ? 2 : 3;
  const selectedGroupTitle = selectedGroup === 1 ? t("Data preparation") : selectedGroup === 2 ? t("Answer preparation") : t("Use and evaluation");
  const selectedNumber = selectedGroup === 1 ? `1-${selected.order}` : selectedGroup === 2 ? "2" : selected.id === "ask" ? "3-1" : "3-2";


  const focusId = props.focusStage === "setup" ? "setup" : pipeline.stages.find((item) => item.id === props.focusStage || String(item.order) === props.focusStage)?.id;
  useEffect(() => {
    if (focusId === "setup") {
      const setup = document.getElementById("pipeline-setup-checks") as HTMLDetailsElement | null;
      if (setup) { setup.open = true; setup.focus(); }
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
    if (kind === "evaluate" && (props.evaluationBlockedReason || props.evaluationPreparationReady === false)) return true;
    if (kind === "ask" && !["done", "readonly"].includes(pipeline.stages.find((stage) => stage.id === "ask")?.status ?? "unknown")) return true;
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

  if (selected.id === "answer_model" && selected.status === "done") {
    diagnosis.detail = answerEngineSummary(answerEngines);
  }

  function navigatePreparation(target: NonNullable<Diagnosis["returnTo"]>) {
    if (target === "setup") {
      const setup = document.getElementById("pipeline-setup-checks") as HTMLDetailsElement | null;
      if (setup) { setup.open = true; setup.focus(); setup.scrollIntoView?.({ block: "nearest" }); }
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
        <div className="pipeline-map-sections" data-tour="stage-list">
          {[
            { id: "data", number: 1, title: t("Data preparation"), stages: ["filings", "index", "embeddings", "lexical"] },
            { id: "model", number: 2, title: t("Answer preparation"), stages: ["answer_model"] },
            { id: "use", number: 3, title: t("Use and evaluation"), stages: ["ask", "evaluate"] },
          ].map((group) => <section className={`pipeline-map-group ${group.id}`} key={group.id} aria-label={group.title}>
            <h3>{group.number}. {group.title}</h3>
            <div className="pipeline-group-nodes">
              {group.stages.map((id) => pipeline.stages.find((stage) => stage.id === id)!).map((stage, index) => <button key={stage.id} data-help={`build.stage.${stage.id}`} className={`pipeline-node ${stage.id} ${stage.status}`} type="button" aria-label={t("Select {p0}", { p0: t(stage.title) })} aria-pressed={selectedId === stage.id} aria-controls="pipeline-execution" onClick={() => setSelectedId(stage.id)}>
                {group.id !== "model" && <span className="pipeline-node-number">{group.number}-{index + 1}</span>}
                <strong>{stage.id === "ask" ? t("Questions and answers") : stage.id === "evaluate" ? t("Search quality evaluation") : t(stage.title)}</strong>
                {stage.id !== "answer_model" && <small className="pipeline-node-status"><i className="status-beacon" aria-hidden="true" />{t(stage.statusDetail || stageStatusLabel(stage.status))}</small>}
                {stage.id === "answer_model" && <span className="answer-engine-lights">{answerEngines.map((engine) => <AnswerEngineLight key={engine.id} engine={engine} showStatus />)}</span>}
                <span className="pipeline-dependency">{t(STEP_DEPENDENCIES[stage.id])}</span>
              </button>)}
              {group.id === "data" && <><span className="pipeline-flow-link source-link" aria-hidden="true"><ArrowDown size={15} /></span><span className="pipeline-flow-link index-link">{t("Parallel search indexes")}<ArrowDown size={15} aria-hidden="true" /></span></>}
            </div>
            {group.id === "model" && <p className="pipeline-group-note">{t("Configure independently of the search indexes.")}</p>}
            {group.id === "use" && <div className="pipeline-use-requirements"><span>{t("Search + answer model")}</span><span>{t("Search + evaluation dataset")}</span></div>}
          </section>)}
        </div>
        <div className="pipeline-guidance" data-tour="next-step" data-help="build.next-step">
          <span>{t(pipeline.corpusReady ? "Corpus ready" : "Recommended next step")}</span>
          {pipeline.next ? <button type="button" onClick={() => setSelectedId(pipeline.next!.id)}>{t(pipeline.next.title)}<ArrowRight size={15} /></button> : <button type="button" onClick={props.onAsk}>{t("Ask a question")}<ArrowRight size={15} /></button>}
          <p>{t(pipeline.next?.hint || "Ask a question, inspect the evaluation results, or run another evaluation.")}</p>
        </div>
      </section>
      <section id="pipeline-execution" className="pipeline-execution" aria-label={t("Selected step execution")}>
        <header><span>{t("Stage {number}: {title}", { number: selectedGroup, title: selectedGroupTitle })}</span><h2>{selectedNumber}. {t(selected.title)}</h2>{props.live && !pipeline.readOnly ? <TerminalHandoff compact diagnosis={diagnosis} technicalDetail={props.schemaStatus === "drifted" && selected.id !== "filings" && selected.id !== "answer_model" ? props.schemaMessage : null} steps={diagnosis.terminalSteps} blocking={diagnosis.state === "blocked"} onNavigate={diagnosis.returnTo !== selected.id ? navigatePreparation : undefined} onRefresh={props.onRefresh} /> : null}{OPERATOR_STAGES.has(selected.id) && !(pipeline.readOnly && selected.id !== "evaluate") && <div className="pipeline-header-dev"><DevelopmentBadge locale={locale} compact reason={pipeline.readOnly && selected.id === "index" ? PUBLIC_PARSING_NOTE : undefined} /></div>}{!pipeline.readOnly && <button type="button" className="button ghost" onClick={props.onOpenJobs}>{t("View all jobs")}</button>}</header>
        {!(pipeline.readOnly && selected.id === "index") && <p className={selected.blockedBy ? "pipeline-prerequisite" : "helper"}>{selected.blockedBy && <span className="pipeline-state-label">{t("Prerequisite")}</span>}{selected.blockedBy ? t("Required first: {p0}", { p0: t(pipeline.stages.find((item) => item.id === selected.blockedBy)?.title ?? selected.blockedBy) }) : t(pipeline.readOnly && selected.id !== "evaluate" ? "Confirm your search scope in step 1-2, then review the remaining steps. No preparation jobs run when you select or confirm a step." : "Review the inputs before starting. Selecting a step does not execute it.")}</p>}
        {selected.id === "evaluate" && props.evaluationBlockedReason && <p className="notice" role="status">{t(props.evaluationBlockedReason)}</p>}
        {selected.id === "embeddings" && !pipeline.readOnly && <div className="embedding-notices">
          <p className="embedding-cost-note" role="note"><CircleDollarSign size={15} aria-hidden="true" focusable="false" /><span>{t("OpenAI charges for embedding all pending chunks in the database. Check the embedding provider and pending chunk count before running.")}</span></p>
          <p className="embedding-duration-note" role="note"><Clock3 size={15} aria-hidden="true" focusable="false" /><span>{t("Initial embedding or a large number of new chunks can take time.")}</span></p>
        </div>}
      {pipeline.readOnly && props.publicProgress && !checks.includes("index") && selected.id !== "evaluate" && <div className="pipeline-scope-notice" role="status"><CircleAlert size={16} aria-hidden="true" /><div><strong>{t("Scope not applied")}</strong><span>{t("Confirm your selection in step 1-2.")}</span></div></div>}
      <ol className="stage-list" role="list" data-tour="stage-list">
        {[selected].map((stage) => (
          <StageCard
            key={stage.id}
            stage={stage}
            evaluationSetup={props.evaluationSetup}
            answerEngines={answerEngines}
            onOpenLocalSettings={props.onOpenLocalSettings}
            onLocalPrepared={props.onLocalPrepared}
            recovery={null}
            isNext={pipeline.next?.id === stage.id}
            readOnly={pipeline.readOnly}
            busy={props.busy}
            handler={handler}
            onDownload={props.onDownload}
            onDeleteSources={pipeline.readOnly ? undefined : props.onDeleteSources}
            sourceDeletionDisabled={props.sourceDeletionDisabled || !props.canOperateCorpus || pipeline.stages.some((item) => item.job?.domain === "corpus" && ["queued", "running"].includes(item.job.status))}
            disabled={disabled}
            acquisition={props.acquisition}
            onAcquisitionChange={props.onAcquisitionChange}
            candidates={props.publicProgress?.candidates}
            documents={props.documents ?? []}
            onAskScope={pipeline.readOnly ? advance : props.onAskScope}
            corpusScope={props.corpusScope}
            companies={props.companies ?? []}
            onAcquisitionValidityChange={setAcquisitionValid}
            manifests={props.manifests}
            sources={props.sources}
            onChangeFilings={() => setSelectedId("filings")}
            onOpenDocuments={props.onOpenDocuments}
            onOpenJobs={props.onOpenJobs}
            onOpenStatus={props.onOpenStatus}
            onCancelJob={props.onCancelJob}
          />
        ))}
      </ol>
      {pipeline.readOnly && ["embeddings", "lexical", "answer_model", "ask"].includes(selected.id) && <div className="pipeline-public-actions">

        <div className="source-sync-actions"><HoverBubble label={t("DEV preparation options")} bubble={t(selected.id === "embeddings" ? "DEV can generate embeddings for prepared chunks. PROD uses existing vectors; checking this step does not generate embeddings." : selected.id === "lexical" ? "DEV can rebuild BM25 statistics. PROD uses existing server statistics grouped by language; checking this step does not recalculate them." : "Pipeline choices stay in this browser. Confirm the search scope in step 1-2 before continuing to Ask.")}><span className="source-scope-trigger"><button type="button" aria-label={t("DEV preparation options")}><Info size={15} /></button></span></HoverBubble>
          {["embeddings", "lexical"].includes(selected.id) ? <PipelineNext key={`${selected.id}:${JSON.stringify(props.acquisition)}`} completed={checks.includes(selected.id)} onNext={advance} /> : <button type="button" className="button primary" disabled={selected.id === "ask" && !sequence.slice(0, -1).every(step => checks.includes(step))} onClick={selected.id === "ask" ? () => props.onAskScope?.({ registries: [], issuers: [], fiscal_years: [] }) : advance}>{t(selected.id === "ask" ? "Ask about this scope" : "Next step")}</button>}
        </div>
        {selected.id === "ask" && !sequence.slice(0, -1).every(step => checks.includes(step)) && <p className="helper">{t("Complete the preceding pipeline steps before applying this scope.")}</p>}
      </div>}
        {!pipeline.readOnly && <details className="execution-console"><summary>{t("Actual server job record")}</summary>{selected.job ? <pre>{JSON.stringify({ job_id: selected.job.job_id, status: selected.job.status, stage: selected.job.stage, current: selected.job.current, total: selected.job.total, overall_current: selected.job.overall_current, overall_total: selected.job.overall_total, stage_index: selected.job.stage_index, stage_count: selected.job.stage_count, stage_started_at: selected.job.stage_started_at, progress_stage: selected.job.progress_stage, detail_current: selected.job.detail_current, detail_total: selected.job.detail_total, message: selected.job.message }, null, 2)}</pre> : <p className="helper">{t("No job has been started for this step.")}</p>}</details>}
        {(!pipeline.readOnly || selected.id === "embeddings" || selected.id === "lexical") && <PipelineReference stage={selected.id} acquisition={props.acquisition} manifests={props.manifests} provider={props.embeddingProvider} />}
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
  const items = [
    { label: t("API"), value: apiDown ? t("API unavailable") : known ? t("API ok") : t("Checking status"), tone: apiDown ? "bad" : known ? "good" : "pending" },
    { label: t("Database"), value: databaseConnected === true ? t("Database connected") : databaseConnected === false ? t("Not connected") : t("Checking status"), tone: databaseConnected === true ? "good" : databaseConnected === false ? "bad" : "pending" },
    { label: t("Schema"), value: ["compatible", "ok"].includes(schemaStatus ?? "") ? t("Schema compatible") : schemaStatus === "empty" ? t("Database schema is empty") : schemaStatus === "drifted" ? t("Database schema is incompatible") : schemaStatus === "unavailable" ? t("Database schema is unavailable") : t("Checking status"), tone: ["compatible", "ok"].includes(schemaStatus ?? "") ? "good" : ["drifted", "unavailable"].includes(schemaStatus ?? "") ? "bad" : "pending" },
    { label: t("Source storage"), value: writable === true ? t("Writable") : writable === false ? t("Read-only") : t("Checking status"), tone: writable === true ? "good" : writable === false ? "bad" : "pending" },
    // A configured model name alone does not establish that its engine is ready.
    { label: t("Answer model"), value: answerModel ? `${t("Configured")} · ${t(answerModel)}` : t("Not configured"), tone: "pending" },
  ];

  const problems: RuntimeProblem[] = [];
  if (databaseConnected === false) {
    problems.push({ reason: schemaMessage || "The database is not connected.", fix: "rag-dev up --build -d", commands: [{ id: "db-start", label: "Start database" }] });
  } else if (schemaStatus === "empty") {
    problems.push({ reason: "The local database needs its initial schema.", fix: "uv run python -m scripts.schema prepare", commands: [] });
  } else if (schemaStatus === "drifted") {
    problems.push({ reason: "Database schema is incompatible", guidance: "Preserve this database. Create a separate recovery checkout with its own ports and volume, then open the printed URL and re-check the blocked step.", fix: `uv run python -m scripts.schema recover --return-stage ${returnStage}`, commands: [] });
  }
  if (schemaStatus === "unavailable") { problems.push({ reason: schemaMessage || "Database schema is unavailable", fix: "uv run python -m scripts.schema check", commands: [] }); }
  if (writable === false) {
    problems.push({ reason: "data/ is not writable, so downloads and ingest cannot save files. Set HOST_GID=$(id -g) in .env, then rebuild the app.", fix: 'HOST_GID="$(id -g)" rag-dev up --build -d', commands: [{ id: "app-start", label: "Rebuild app" }] });
  }

  return (
    <details id="pipeline-setup-checks" tabIndex={-1} className="runtime-disclosure" data-health={apiDown || problems.length ? "warning" : known ? "connected" : "checking"} data-help="build.runtime">
      <summary><Server size={14} aria-hidden="true" /><span>{t(apiDown ? "API unavailable" : problems.length ? "Runtime needs attention" : known ? "System connected" : "Checking runtime…")}</span><ChevronDown size={13} aria-hidden="true" /></summary>
      <div className="runtime-strip">
      <table className="runtime-status-table" aria-label={t("Runtime status")}><tbody>{items.map((item) => <tr key={item.label}><th scope="row">{item.label}</th><td><span className={`runtime-health-dot ${item.tone}`} aria-hidden="true" /><span>{item.value}</span></td></tr>)}</tbody></table>
      <div className="runtime-actions">
        {live && <button className="button ghost" type="button" onClick={() => void onRefresh()}>{t("Check schema")}</button>}
        {live && onRunOperation && !problems.length && <button className="button ghost" type="button" onClick={() => onRunOperation("app-start")}>{t("Rebuild app")}</button>}
        {live && <button className="button ghost" type="button" onClick={onRefresh}><RefreshCw size={14} />{t("Refresh")}</button>}
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

function ActionButton({ stage, primary, handler, disabled, locked = false }: { stage: Stage; primary: boolean; handler: (kind: StageActionKind) => () => void; disabled: (kind: StageActionKind) => boolean; locked?: boolean }) {
  const { t, locale } = useI18n();
  if (!stage.action) return null;
  const { kind, label } = stage.action;
  if (locked && OPERATOR_ACTIONS.has(kind)) return <DevLockedButton reason={kind === "evaluate" ? "evaluation" : "corpus"} className={primary ? "button primary" : "button"}>{t(label)}</DevLockedButton>;
  return <button className={primary ? "button primary" : "button"} type="button" disabled={disabled(kind)} onClick={handler(kind)}>{t(label)}</button>;
}



interface StageCardProps {
  answerEngines: AnswerEngineState[];
  onOpenLocalSettings?: () => void;
  onLocalPrepared?: (local: ReviewEngineState) => void;
  busy: boolean;
  recovery?: ReactNode;
  stage: Stage;
  evaluationSetup?: (action: ReactNode) => ReactNode;
  isNext: boolean;
  readOnly: boolean;
  handler: (kind: StageActionKind) => () => void;
  onDownload: (next?: AcquisitionForm) => void;
  disabled: (kind: StageActionKind) => boolean;
  acquisition: AcquisitionForm;
  documents: CorpusDocument[];
  companies: AcquisitionCompany[];
  candidates?: import("@/lib/types").PublicTarget[];
  onAskScope?: (filters: ScopeFilters) => void;
  corpusScope?: string;
  onAcquisitionValidityChange: (valid: boolean) => void;
  onAcquisitionChange: (next: AcquisitionForm) => void;
  manifests: ManifestSummary[];
  sources?: SourceInventory[];
  onChangeFilings?: () => void;
  onDeleteSources?: (token: string) => Promise<void>;
  sourceDeletionDisabled?: boolean;
  onOpenDocuments: () => void;
  onOpenJobs: () => void;
  onOpenStatus: () => void;
  onCancelJob: (jobId: string) => void;
}

function StageCard({ candidates, answerEngines, onOpenLocalSettings, onLocalPrepared, onDownload, onDeleteSources, sourceDeletionDisabled, busy, sources = [], onChangeFilings, recovery, stage, evaluationSetup, isNext, readOnly, handler, disabled, acquisition, onAcquisitionChange, documents, companies, onAskScope, corpusScope, onAcquisitionValidityChange, manifests, onOpenDocuments, onOpenJobs, onOpenStatus, onCancelJob }: StageCardProps) {
  const { t, locale } = useI18n();
  const job = stage.job;
  const showHint = Boolean(stage.hint) && stage.hint !== job?.message;
  const readOnlyNote = readOnly && !["filings", "embeddings", "lexical"].includes(stage.id) && OPERATOR_STAGES.has(stage.id);
  const sourceState = selectedSourceState(sources, acquisition);
  const activeJob = job && (job.status === "running" || job.status === "queued");
  const selectedKeys = new Set(sourceState.selected.map((source) => pairKey({ registry: source.registry, issuer: source.issuer, year: source.fiscal_year })));
  const absentCount = sourceState.pairs.filter((pair) => !selectedKeys.has(pairKey(pair))).length;
  const scopedDocuments = documents.filter((doc) => (corpusScope === "auto" || !corpusScope || doc.registry === corpusScope) && sourceState.pairs.some((pair) => pair.registry === doc.registry && pair.issuer === doc.issuer && pair.year === doc.fiscal_year));
  const scopedChunks = scopedDocuments.reduce((sum, doc) => sum + doc.chunk_count, 0);
  const documentCount = readOnly ? scopedDocuments.length : sourceState.selected.length + absentCount;
  const companyCount = new Set(sourceState.pairs.filter((pair) => !readOnly || !corpusScope || corpusScope === "auto" || pair.registry === corpusScope).map((pair) => `${pair.registry}:${pair.issuer}`)).size;
  const yearCount = new Set(sourceState.pairs.filter((pair) => !readOnly || !corpusScope || corpusScope === "auto" || pair.registry === corpusScope).map((pair) => pair.year)).size;
  const missingCount = documentCount - sourceState.present.length;
  const unreadyPairs = sourceState.pairs.filter((pair) => {
    const rows = sourceState.selected.filter((source) => source.registry === pair.registry && source.issuer.toUpperCase() === pair.issuer && source.fiscal_year === pair.year);
    return !rows.length || rows.some((source) => !source.on_disk || source.ready === false);
  });

  return (
    <li>
      <article id={`stage-${stage.order}`} className={`stage-card ${stage.status}${isNext ? " next" : ""}`} data-help={`build.stage.${stage.id}`}>
        <div className={`stage-index ${stage.status}`} aria-hidden="true">{stage.status === "done" ? <Check size={15} /> : stage.order}</div>
        <div className="stage-body">

          {!(readOnly && stage.id === "index") && <div className={stage.id === "evaluate" ? "evaluation-intro" : undefined}><p className="stage-description">{t(stage.description)}</p></div>}
          {stage.id === "answer_model" && (readOnly || stage.status !== "readonly") && <AnswerEngineRows showLocalPreview={readOnly} engines={answerEngines} onOpenStatus={onOpenStatus} onOpenLocal={onOpenLocalSettings} onLocalPrepared={onLocalPrepared} />}
          {stage.numbers.length > 0 && (stage.id !== "answer_model" || stage.status === "readonly") && (
            <p className="stage-numbers">
              {stage.numbers.map((item, index) => <Fragment key={`${index}:${t(item)}`}>{index > 0 && <span className="sep" aria-hidden="true">·</span>}<span>{t(item)}</span></Fragment>)}
            </p>
          )}
          {stage.id === "evaluate" && (evaluationSetup ? evaluationSetup(stage.action ? <ActionButton stage={stage} primary={true} handler={handler} disabled={disabled} /> : null) : stage.action ? <ActionButton stage={stage} primary={true} handler={handler} disabled={disabled} /> : null)}
          {stage.id === "filings" && <SourceMatrix locked={readOnly} corpusScope={corpusScope} onAskScope={onAskScope} sources={sources} companies={companies} acquisition={acquisition} onChange={onAcquisitionChange} disabled={busy} onValidityChange={onAcquisitionValidityChange} onDownload={onDownload} downloadDisabled={disabled("acquire")} onDeleteSources={onDeleteSources} deleteDisabled={sourceDeletionDisabled} onOpenJobs={onOpenJobs} />}
          {job && !(stage.id === "index" && activeJob) && (
            <div className="stage-job">
              <JobProgress job={job} />
            </div>
          )}
          {showHint && <p className="stage-hint">{t(stage.hint)}</p>}
          {recovery}
          {readOnlyNote && <p className="stage-note">{t(stage.id === "evaluate" ? "Open Quality checks to explore datasets, try evaluation settings and compare published results. Running new evaluations is available in DEV mode." : stage.id === "index" ? "Use prepared chunks. Adjust the selection below, then confirm your search scope." : DEV_ONLY_NOTE)}</p>}
          <details className={`stage-why${readOnly ? " public-stage-why" : ""}`}><summary><Lightbulb size={15} aria-hidden="true" /><span>{t(readOnly ? "Why it matters" : "Why it matters:")}</span></summary><p>{t(stage.why)}</p></details>
          {stage.id === "index" && <section className="index-selection source-basket" aria-label={t("Selected documents")}>
            <header className="index-selection-heading">
              <h3>{t("Selected documents")}</h3>
              <button className="button" type="button" onClick={onChangeFilings}><span className="pipeline-return-step" aria-hidden="true">1</span>{t("Change selection in Filings")}</button>
            </header>
            <p className="index-selection-totals" role="status"><strong>{t(readOnly ? "{documents} documents · {chunks} chunks in scope" : "{documents} documents · {ready} ready · {missing} to download", { documents: documentCount, chunks: scopedChunks, ready: sourceState.present.length - sourceState.blocked.length, missing: missingCount })}{sourceState.blocked.length > 0 && <> · {t("Needs repair: {count}", { count: sourceState.blocked.length })}</>}</strong><span>{t("{companies} companies · {years} fiscal years", { companies: companyCount, years: yearCount })}</span></p>
            {!readOnly && <div className="source-year-legend"><span><span className="year-downloaded-mark" aria-hidden="true">✓</span>{t(readOnly ? "In scope" : "Downloaded")}</span><span><span className="source-year-pending" aria-hidden="true">!</span>{t(readOnly ? "Not in scope" : "Download or repair needed")}</span><span><MousePointer2 size={11} aria-hidden="true" />{t("Click to select or deselect")}</span></div>}
            <SourceSelectionGrid availablePairs={readOnly ? candidates ?? sourceState.pairs : undefined} scopeMode={readOnly} corpusScope={corpusScope} sources={sources.filter((source) => sourceState.pairs.some((pair) => pair.registry === source.registry && pair.issuer === source.issuer))} pairs={sourceState.pairs} companies={readOnly ? PUBLIC_COMPANIES : companies} disabled={busy || Boolean(activeJob)}
              onRemoveCompany={(company) => onAcquisitionChange(acquisitionDraft(sourceState.pairs.filter((pair) => pair.registry !== company.registry || pair.issuer !== company.issuer)))} onToggle={(changed, included) => {
              const next = new Map(sourceState.pairs.map((pair) => [pairKey(pair), pair]));
              for (const pair of changed) if (included) next.set(pairKey(pair), pair); else next.delete(pairKey(pair));
              onAcquisitionChange(acquisitionDraft([...next.values()]));
            }} />
            {!readOnly && unreadyPairs.length > 0 && <p className="index-readiness-note" role="alert" id="index-selection-missing">{t("{count} company-years need download or repair in step 1 before parsing.", { count: unreadyPairs.length })}</p>}
            {!readOnly && unreadyPairs.length > 0 && <details className="index-repair-details"><summary>{t("Download and repair details")}</summary><ul>{unreadyPairs.map((pair) => {
              const rows = sourceState.selected.filter((source) => source.registry === pair.registry && source.issuer === pair.issuer && source.fiscal_year === pair.year);
              return <li key={pairKey(pair)}>{pair.registry.toUpperCase()} · {pair.issuer} FY{pair.year}{rows.length ? <ul>{rows.filter((source) => !source.on_disk || source.ready === false).map((source) => <li key={source.document_id}>{source.filing_id}: {source.blocker || t(source.on_disk ? "Source blocked" : "Missing source")}</li>)}</ul> : `: ${t("Missing source")}`}</li>;
            })}</ul></details>}
            {!readOnly && !sourceState.pairs.length && <p className="helper">{t("Select sources in Filings to start parsing.")}</p>}
            {!readOnly && sourceState.pairs.length > 0 && <p className="helper">{t("Select or clear downloaded years here. Add missing filings in step 1.")}</p>}
          </section>}
          {stage.id === "index" ? <div className="index-action-bar" aria-label={t("Parsing actions")} role="group">
            {activeJob && <div className="index-action-progress"><JobProgress job={job} /></div>}
            <button className="button" type="button" onClick={onOpenDocuments}>{t("Open Documents")}</button>
            {activeJob ? <>
              {job.can_cancel && <button className="button" type="button" onClick={() => onCancelJob(job.job_id)}>{t("Cancel")}</button>}
            </> : readOnly ? <div className="source-sync-actions"><HoverBubble label={t("Parsing and chunking in DEV")} bubble={t("In DEV mode, you can choose which source documents to process and run parsing and chunking. PROD uses precomputed chunks for the scope selected in step 1-1.")}><span className="source-scope-trigger"><button type="button" aria-label={t("Parsing and chunking in DEV")}><Info size={15} /></button></span></HoverBubble><button className="button primary" type="button" disabled={busy || !onAskScope || !sourceState.pairs.some(pair => !corpusScope || corpusScope === "auto" || pair.registry === corpusScope)} onClick={() => onAskScope?.({ registries: [], issuers: [], fiscal_years: [] })}><MessageSquare size={15} />{t("Confirm search scope")}</button></div> : <button className="button primary" type="button" aria-label={t("Parse & chunk selected sources")} aria-describedby={unreadyPairs.length ? "index-selection-missing" : undefined} disabled={disabled("ingest_all") || !sourceState.complete} onClick={handler("ingest_all")}>{t("Parse & chunk selected sources")}<span className="index-action-count">{sourceState.present.length}</span></button>}
          </div> : <div className="stage-actions">
            {job && job.can_cancel && <button className="button" type="button" onClick={() => onCancelJob(job.job_id)}>{t("Cancel")}</button>}
            {stage.action && stage.id !== "filings" && stage.id !== "evaluate" && !(readOnly && ["embeddings", "lexical", "answer_model", "ask"].includes(stage.id)) && <ActionButton stage={stage} primary={true} handler={handler} disabled={disabled} locked={readOnly} />}
          </div>}

        </div>
      </article>
    </li>
  );
}
