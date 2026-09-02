"use client";

import { Check, RefreshCw } from "lucide-react";
import { Fragment } from "react";

import { elapsedLabel, JobProgress } from "@/components/job-center";
import { Segmented } from "@/components/segmented";
import type { Pipeline, Stage, StageActionKind, StageStatus } from "@/lib/pipeline";
import { stageStatusLabel } from "@/lib/pipeline";
import type { ManifestSummary } from "@/lib/types";

export interface AcquisitionForm {
  registry: "sec" | "dart";
  identifiers: string;
  years: string;
}

export interface BuildPipelineProps {
  pipeline: Pipeline;
  live: boolean;
  busy: boolean;
  canOperateCorpus: boolean;
  acquisition: AcquisitionForm;
  onAcquisitionChange: (next: AcquisitionForm) => void;
  manifests: ManifestSummary[];
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
  onIngest: (manifestName: string) => void;
  onBackfill: () => void;
  onRebuildBm25: () => void;
  onAsk: () => void;
  onRecheck: () => void;
  onEvaluate: () => void;
  onCompareSnapshots: () => void;
  onOpenDocuments: () => void;
  onOpenJobs: () => void;
  onOpenStatus: () => void;
  onRefresh: () => void;
}

const REGISTRY_LABELS: Record<AcquisitionForm["registry"], string> = { sec: "SEC EDGAR", dart: "DART" };

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

export function BuildPipeline(props: BuildPipelineProps) {
  const { pipeline } = props;

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
    if (!OPERATOR_ACTIONS.has(kind)) return false;
    return pipeline.readOnly || props.busy || (props.live && !props.canOperateCorpus);
  }

  return (
    <div className="build-pipeline panel-stack">
      <RuntimeStrip
        pipeline={pipeline}
        live={props.live}
        databaseConnected={props.databaseConnected ?? null}
        schemaStatus={props.schemaStatus ?? null}
        schemaMessage={props.schemaMessage ?? null}
        writable={props.writable ?? null}
        answerModel={props.answerModel ?? null}
        onRunOperation={props.operationsAvailable && props.onRunOperation ? props.onRunOperation : null}
        onRefresh={props.onRefresh}
      />
      <NextStep pipeline={pipeline} handler={handler} disabled={disabled} onAsk={props.onAsk} onEvaluate={props.onEvaluate} onCompareSnapshots={props.onCompareSnapshots} onRefresh={props.onRefresh} onCancelJob={props.onCancelJob} />
      <ol className="stage-list" role="list" data-tour="stage-list">
        {pipeline.stages.map((stage) => (
          <StageCard
            key={stage.id}
            stage={stage}
            isNext={pipeline.next?.id === stage.id}
            readOnly={pipeline.readOnly}
            handler={handler}
            disabled={disabled}
            acquisition={props.acquisition}
            onAcquisitionChange={props.onAcquisitionChange}
            manifests={props.manifests}
            registryCounts={props.registryCounts ?? {}}
            onIngest={props.onIngest}
            onOpenDocuments={props.onOpenDocuments}
            onOpenJobs={props.onOpenJobs}
            onOpenStatus={props.onOpenStatus}
          />
        ))}
      </ol>
    </div>
  );
}

interface RuntimeStripProps {
  pipeline: Pipeline;
  live: boolean;
  databaseConnected: boolean | null;
  schemaStatus: string | null;
  schemaMessage: string | null;
  writable: boolean | null;
  answerModel: string | null;
  /** Set only when Local Operations can run the fix for a problem from the browser. */
  onRunOperation: ((commandId: string) => void) | null;
  onRefresh: () => void;
}

interface RuntimeProblem {
  reason: string;
  /** Command line shown when no local operator is attached. */
  fix: string;
  /** Operations registry commands that perform the fix, in order. */
  commands: Array<{ id: string; label: string }>;
}

function RuntimeStrip({ pipeline, live, databaseConnected, schemaStatus, schemaMessage, writable, answerModel, onRunOperation, onRefresh }: RuntimeStripProps) {
  if (pipeline.readOnly) {
    return <div className="runtime-strip"><div className="runtime-items"><span>Read-only portfolio · stored snapshots + live retrieval</span></div></div>;
  }
  const apiDown = isApiDown(pipeline);
  const items: string[] = [apiDown ? "API unavailable" : "API ok"];
  if (databaseConnected === true) items.push("Database connected");
  if (schemaStatus === "compatible") items.push("Schema compatible");
  if (writable === true) items.push("Writable");
  if (answerModel) items.push(`Answer model: ${answerModel}`);
  if (!apiDown && databaseConnected === null && schemaStatus === null && writable === null) items.push("Checking runtime…");

  const problems: RuntimeProblem[] = [];
  if (databaseConnected === false) {
    problems.push({ reason: schemaMessage || "The database is not connected.", fix: "docker compose up -d db", commands: [{ id: "db-start", label: "Start database" }] });
  } else if (schemaStatus === "drifted" || schemaStatus === "unavailable") {
    problems.push({ reason: schemaMessage || `Schema ${schemaStatus}.`, fix: "uv run python -m app.db.migrate --plan", commands: [{ id: "db-migrate-plan", label: "Plan migrations" }, { id: "db-migrate-apply", label: "Apply migrations" }] });
  }
  if (writable === false) {
    problems.push({ reason: "data/ is not writable, so downloads and ingest cannot save files. Set HOST_GID=$(id -g) in .env, then rebuild the app.", fix: "HOST_GID=$(id -g) docker compose up -d app", commands: [{ id: "app-start", label: "Rebuild app" }] });
  }

  return (
    <div className="runtime-strip">
      <div className="runtime-items">{items.map((item, index) => <Fragment key={item}>{index > 0 && <span className="sep" aria-hidden="true">·</span>}<span>{item}</span></Fragment>)}</div>
      <div className="runtime-actions">
        {live && onRunOperation && !problems.length && <button className="button ghost" type="button" onClick={() => onRunOperation("app-start")}>Rebuild app</button>}
        {live && <button className="button ghost" type="button" onClick={onRefresh}><RefreshCw size={14} /> Refresh</button>}
      </div>
      {problems.map((problem) => (
        <div className="notice error" role="alert" key={problem.fix}>
          <p>{problem.reason}</p>
          {onRunOperation
            ? <div className="action-row">{problem.commands.map((command) => <button className="button" type="button" key={command.id} onClick={() => onRunOperation(command.id)}>{command.label}</button>)}</div>
            : <code>{problem.fix}</code>}
        </div>
      ))}
    </div>
  );
}

interface NextStepProps {
  pipeline: Pipeline;
  handler: (kind: StageActionKind) => () => void;
  disabled: (kind: StageActionKind) => boolean;
  onAsk: () => void;
  onEvaluate: () => void;
  onCompareSnapshots: () => void;
  onRefresh: () => void;
  onCancelJob: (jobId: string) => void;
}

function NextStep({ pipeline, handler, disabled, onAsk, onEvaluate, onCompareSnapshots, onRefresh, onCancelJob }: NextStepProps) {
  const running = pipeline.stages.find((stage) => stage.status === "running") ?? null;
  const unknown = pipeline.stages.find((stage) => stage.status === "unknown") ?? null;
  const blocked = pipeline.stages.find((stage) => stage.status === "blocked") ?? null;
  const doneWithHint = pipeline.stages.find((stage) => stage.status === "done" && stage.hint) ?? null;

  let title: string;
  let text: string;
  let actions: React.ReactNode = null;

  if (running) {
    title = `Running · ${running.order} ${running.title}${running.statusDetail ? ` · ${running.statusDetail}` : ""}`;
    text = running.hint || "The job is in progress.";
    const job = running.job;
    actions = job && <button className="button" type="button" disabled={!job.can_cancel} onClick={() => onCancelJob(job.job_id)}>Cancel</button>;
  } else if (pipeline.next) {
    const stage = pipeline.next;
    title = `Next step · ${stage.order} ${stage.title}`;
    text = stage.hint;
    actions = stage.action && <ActionButton stage={stage} primary handler={handler} disabled={disabled} />;
  } else if (pipeline.readOnly) {
    title = "Explore";
    text = "This build is read-only. Ask a question against the published corpus or compare snapshots.";
    actions = <><button className="button primary" type="button" onClick={onAsk}>Ask a question</button><button className="button" type="button" onClick={onCompareSnapshots}>Compare snapshots</button></>;
  } else if (unknown) {
    const apiDown = isApiDown(pipeline);
    title = apiDown ? "API unavailable" : "Checking…";
    text = apiDown ? "The DocReview API did not answer. Start it, then refresh." : "Waiting for readiness and the administrator snapshot.";
    actions = <button className="button" type="button" onClick={onRefresh}><RefreshCw size={14} /> Refresh</button>;
  } else if (blocked) {
    title = `Blocked · ${blocked.order} ${blocked.title}${blocked.statusDetail ? ` · ${blocked.statusDetail}` : ""}`;
    text = blocked.hint;
    actions = blocked.action && <ActionButton stage={blocked} primary handler={handler} disabled={disabled} />;
  } else if (doneWithHint) {
    title = "All steps done";
    text = doneWithHint.hint;
    actions = doneWithHint.action && <ActionButton stage={doneWithHint} primary handler={handler} disabled={disabled} />;
  } else {
    title = "All steps done";
    text = "The corpus is ready. Ask a question or run an evaluation.";
    actions = <><button className="button primary" type="button" onClick={onAsk}>Ask a question</button><button className="button" type="button" disabled={disabled("evaluate")} onClick={onEvaluate}>Run quick evaluation</button></>;
  }

  return (
    <section className="next-step" data-tour="next-step" data-help="build.next-step">
      <h2>{title}</h2>
      {text && <p>{text}</p>}
      {actions && <div className="action-row">{actions}</div>}
    </section>
  );
}

function ActionButton({ stage, primary, handler, disabled }: { stage: Stage; primary: boolean; handler: (kind: StageActionKind) => () => void; disabled: (kind: StageActionKind) => boolean }) {
  if (!stage.action) return null;
  const { kind, label } = stage.action;
  return <button className={primary ? "button primary" : "button"} type="button" disabled={disabled(kind)} onClick={handler(kind)}>{label}</button>;
}

function StatusPill({ status, detail }: { status: StageStatus; detail: string }) {
  const label = stageStatusLabel(status);
  return <span className={`stage-status ${status}`}>{label}{detail && detail !== label && <em>{detail}</em>}</span>;
}

interface StageCardProps {
  stage: Stage;
  isNext: boolean;
  readOnly: boolean;
  handler: (kind: StageActionKind) => () => void;
  disabled: (kind: StageActionKind) => boolean;
  acquisition: AcquisitionForm;
  onAcquisitionChange: (next: AcquisitionForm) => void;
  manifests: ManifestSummary[];
  registryCounts: Record<string, number>;
  onIngest: (manifestName: string) => void;
  onOpenDocuments: () => void;
  onOpenJobs: () => void;
  onOpenStatus: () => void;
}

function manifestSummary(manifest: ManifestSummary, registryCounts: Record<string, number>): string {
  if (!manifest.valid) return "invalid manifest";
  const parts = [`${(manifest.documents ?? 0).toLocaleString("en-US")} entries`, `${(manifest.sources_present ?? 0).toLocaleString("en-US")} on disk`];
  if (manifest.registry && Object.hasOwn(registryCounts, manifest.registry)) parts.push(`${registryCounts[manifest.registry].toLocaleString("en-US")} ingested`);
  return parts.join(" · ");
}

function StageCard({ stage, isNext, readOnly, handler, disabled, acquisition, onAcquisitionChange, manifests, registryCounts, onIngest, onOpenDocuments, onOpenJobs, onOpenStatus }: StageCardProps) {
  const job = stage.job;
  const showHint = Boolean(stage.hint) && stage.hint !== job?.message;
  const readOnlyNote = readOnly && OPERATOR_STAGES.has(stage.id);
  const identifiers = splitList(acquisition.identifiers);
  const years = splitList(acquisition.years).map((year) => `FY${year}`);

  return (
    <li>
      <article id={`stage-${stage.order}`} className={`stage-card ${stage.status}${isNext ? " next" : ""}`} data-help={`build.stage.${stage.id}`}>
        <div className={`stage-index ${stage.status}`} aria-hidden="true">{stage.status === "done" ? <Check size={15} /> : stage.order}</div>
        <div className="stage-body">
          <div className="stage-head">
            <h3><span className="sr-only">Step {stage.order} · </span>{stage.title}</h3>
            <StatusPill status={stage.status} detail={stage.statusDetail} />
          </div>
          <p className="stage-description">{stage.description}</p>
          {stage.numbers.length > 0 && (
            <p className="stage-numbers">
              {stage.numbers.map((item, index) => <Fragment key={`${index}:${item}`}>{index > 0 && <span className="sep" aria-hidden="true">·</span>}<span>{item}</span></Fragment>)}
            </p>
          )}
          {stage.id === "filings" && (
            <p className="stage-summary">{[REGISTRY_LABELS[acquisition.registry], identifiers.join(", ") || "no tickers", years.join(", ") || "no fiscal years"].join(" · ")}</p>
          )}
          {job && (
            <div className="stage-job">
              <JobProgress job={job} />
              <p className="helper">{job.message} · {elapsedLabel(job)}</p>
            </div>
          )}
          <div className="stage-actions">
            {stage.action && <ActionButton stage={stage} primary={isNext} handler={handler} disabled={disabled} />}
            {stage.id === "index" && <button className="button ghost" type="button" onClick={onOpenDocuments}>Open Documents</button>}
            {stage.id === "answer_model" && stage.status !== "readonly" && <button className="button ghost" type="button" onClick={onOpenStatus}>Open System status</button>}
            {job && <button className="button ghost" type="button" onClick={onOpenJobs}>View all jobs</button>}
          </div>
          {showHint && <p className="stage-hint">{stage.hint}</p>}
          {readOnlyNote && <p className="stage-note">{READ_ONLY_NOTE}</p>}
          <details className="stage-why"><summary>Why this matters</summary><p>{stage.why}</p></details>
          {stage.id === "filings" && (
            <details className="stage-advanced">
              <summary>Change…</summary>
              <div>
                <Segmented
                  label="Registry"
                  options={[{ value: "sec", label: "SEC EDGAR" }, { value: "dart", label: "DART" }]}
                  value={acquisition.registry}
                  disabled={readOnly}
                  onChange={(registry) => onAcquisitionChange({ ...acquisition, registry })}
                />
                <div className="profile-grid">
                  <label>Tickers / stock codes<input value={acquisition.identifiers} disabled={readOnly} onChange={(event) => onAcquisitionChange({ ...acquisition, identifiers: event.target.value })} /></label>
                  <label>Fiscal years<input value={acquisition.years} disabled={readOnly} onChange={(event) => onAcquisitionChange({ ...acquisition, years: event.target.value })} /></label>
                </div>
                <p className="helper">{acquisition.registry === "sec" ? "EDGAR downloads need SEC_USER_AGENT in .env." : "DART downloads need DART_API_KEY in .env."}</p>
              </div>
            </details>
          )}
          {stage.id === "index" && (
            <details className="stage-advanced">
              <summary>Change…</summary>
              <div>
                {manifests.map((manifest) => (
                  <div className="manifest-row" key={manifest.name}>
                    <span>{manifest.name} · {(manifest.registry ?? "other").toUpperCase()} · {manifestSummary(manifest, registryCounts)}</span>
                    <button className="button" type="button" aria-label={`Ingest ${manifest.name}`} disabled={!manifest.valid || disabled("ingest_all")} onClick={() => onIngest(manifest.name)}>Ingest</button>
                  </div>
                ))}
                {!manifests.length && <p className="helper">No manifests found in data/corpus.</p>}
                <p className="helper">Ingest upserts documents from each manifest in order and recomputes BM25. Run Backfill embeddings afterwards (step 3).</p>
              </div>
            </details>
          )}
        </div>
      </article>
    </li>
  );
}
