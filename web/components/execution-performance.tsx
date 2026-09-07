"use client";

import { useI18n } from "@/lib/i18n";
import type { ReviewExecution } from "@/lib/types";
import "./performance.css";

interface ModelCall {
  node?: string;
  model?: string;
  attempts?: number | null;
  elapsed_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cached_input_tokens?: number | null;
  cache_write_input_tokens?: number | null;
  reasoning_tokens?: number | null;
  provider?: string;
  timing_unavailable_reason?: string | null;
  local_timings?: Array<Record<string, number | null>>;
  provider_timing?: Array<Record<string, number | null>> | null;
}
interface StageTiming { node?: string; phase?: string; elapsed_ms?: number | null; status?: string }

const STAGE_LABELS: Record<string, string> = {
  gate: "Understand the question",
  route: "Resolve filing scope",
  retrieve: "Retrieve evidence",
  candidates: "Collect candidate evidence",
  grade: "Select relevant evidence",
  check: "Verify answer and citations",
  report: "Prepare the result",
  chat: "Reply to the conversation",
};
const STATUS_CODES: Record<string, string> = { completed: "OK", succeeded: "OK", failed: "ERR", cancelled: "STOP", running: "RUN" };
const BAR_WIDTH = 20;

/** Reject absent and invalid measurements without conflating a measured zero. */
function collectedNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

/** Keep subsecond measurements legible without rounding a positive duration to zero. */
function formatDuration(value: unknown, locale: string, missing: string): string {
  if (!collectedNumber(value)) return missing;
  if (value > 0 && value < 1) return "<1ms";
  if (value < 1000) return `${value.toLocaleString(locale, { maximumFractionDigits: 2 })}ms`;
  return `${(value / 1000).toLocaleString(locale, { maximumFractionDigits: 2 })}s`;
}

/** Use discrete relative bars for collected durations only; a measured zero stays empty. */
function durationBar(value: number, longest: number): string {
  const filled = longest > 0 ? Math.min(BAR_WIDTH, Math.round(value / longest * BAR_WIDTH)) : 0;
  return `[${"#".repeat(filled)}${".".repeat(BAR_WIDTH - filled)}]`;
}

/** Prefer the explicit contract while accepting historical Ollama timing records. */
function providerTimings(call: ModelCall) {
  const records = call.provider_timing ?? call.local_timings ?? [];
  return records.filter((record) => ["total_duration_ms", "load_duration_ms", "prompt_eval_duration_ms", "eval_duration_ms", "eval_count"].some((field) => collectedNumber(record[field])));
}

/** Show one provider-specific reason instead of an empty disclosure for each call. */
function timingReason(call: ModelCall): string | null {
  if (providerTimings(call).length) return null;
  if (["openai", "openai_responses"].includes(call.provider ?? "")) return "OpenAI does not report server-side timings.";
  if (call.provider === "ollama" || call.timing_unavailable_reason === "ollama_timing_not_recorded") return "Ollama timing fields were not recorded for this call.";
  return null;
}

/** Display measured execution in recorded order while keeping optional legacy data explicit. */
export function ExecutionPerformance({ data, state, embedded = false }: { data?: Record<string, unknown>; state: ReviewExecution; embedded?: boolean }) {
  const { t, locale } = useI18n();
  const callsCollected = Array.isArray(data?.model_calls);
  const calls = (callsCollected ? data.model_calls : []) as ModelCall[];
  const stages = (Array.isArray(data?.stages) ? data.stages : state.stageTimings ?? []) as StageTiming[];
  const measured = stages.flatMap((stage, index) => collectedNumber(stage.elapsed_ms) ? [{ ...stage, elapsed_ms: stage.elapsed_ms, order: index + 1 }] : []);
  const longest = measured.reduce((maximum, stage) => Math.max(maximum, stage.elapsed_ms), 0);
  const missing = t("Not collected");
  const duration = (value: unknown) => formatDuration(value, locale, missing);
  const count = (value: unknown) => collectedNumber(value) ? value.toLocaleString(locale) : missing;
  const attempts = calls.every((call) => collectedNumber(call.attempts)) ? calls.reduce((total, call) => total + call.attempts!, 0) : undefined;
  const stageLabel = (node?: string) => t(node && STAGE_LABELS[node] ? STAGE_LABELS[node] : "Unknown stage");
  const nodeWidth = Math.max(5, ...measured.map((stage) => (stage.node ?? "?").length));
  const sequenceWidth = Math.max(2, String(stages.length).length);
  const ascii = measured.map((stage) => `${String(stage.order).padStart(sequenceWidth, "0")} [${(STATUS_CODES[stage.status ?? ""] ?? "?").padEnd(4)}] ${(stage.node ?? "?").padEnd(nodeWidth)} ${durationBar(stage.elapsed_ms, longest)} ${duration(stage.elapsed_ms)}`).join("\n");

  const placement = data?.local_placement as { placement?: string; model?: string; reason?: string } | null | undefined;
  const placementLabels: Record<string, string> = { cpu: "CPU", gpu: "GPU", mixed: "CPU + GPU" };
  const placementReasons: Record<string, string> = {
    provider_does_not_report_placement: "This provider does not report CPU / GPU placement.",
    model_not_loaded: "The model was not loaded when Ollama placement was checked.",
    ollama_memory_fields_unavailable: "Ollama did not report the memory fields needed for placement.",
    ollama_placement_unavailable: "Ollama placement could not be checked after this run.",
  };
  const placementLabel = placement?.placement ? placementLabels[placement.placement] : undefined;
  const reasons = [...new Set(calls.map(timingReason).filter((reason): reason is string => reason !== null))];
  const content = <div className="performance-content">
      <dl className="performance-facts">
        <div><dt>{t("Request time")}</dt><dd>{duration(state.elapsedMs)}</dd></div>
        <div><dt>{t("Server execution")}</dt><dd>{duration(data?.total_elapsed_ms)}</dd></div>
        <div><dt>{t("Model calls / attempts")}</dt><dd>{callsCollected ? `${count(calls.length)} / ${count(attempts)}` : missing}</dd></div>
        <div><dt>{t("CPU / GPU placement")}</dt><dd>{placementLabel ?? (placement?.reason && placementReasons[placement.reason] ? t(placementReasons[placement.reason]) : missing)}{placementLabel && placement?.model && <code className="performance-identifier">{placement.model}</code>}</dd></div>
      </dl>

      <section className="performance-section">
        <h3>{t("Stage timings")}</h3>
        {measured.length > 0 && <pre className="performance-ascii" aria-hidden="true">{ascii}</pre>}
        {stages.length ? <div className="table-wrap performance-table-wrap"><table className="performance-table">
          <caption><strong>{t("Measured stage durations")}</strong><span>{t("Bar length is relative to the longest measured stage. Events remain in collection order.")}</span></caption>
          <thead><tr><th scope="col">{t("Order")}</th><th scope="col">{t("Stage")}</th><th scope="col">{t("Status")}</th><th scope="col">{t("Elapsed")}</th></tr></thead>
          <tbody>{stages.map((stage, index) => <tr key={index}>
            <td className="performance-order">{String(index + 1).padStart(2, "0")}</td>
            <td><span>{stageLabel(stage.node)}</span>{stage.node && <code className="performance-identifier">{stage.node}</code>}</td>
            <td><span className={`performance-status ${stage.status === "completed" || stage.status === "succeeded" ? "is-complete" : stage.status === "failed" ? "is-failed" : ""}`}>{stage.status ? t(stage.status) : t("Unknown status")}</span>{stage.status && <code className="performance-identifier">{stage.status}</code>}</td>
            <td className="performance-number" title={collectedNumber(stage.elapsed_ms) ? `${stage.elapsed_ms}ms` : undefined}>{duration(stage.elapsed_ms)}</td>
          </tr>)}</tbody>
        </table></div> : <p className="helper">{missing}</p>}
        {stages.length > 0 && measured.length === 0 && <p className="helper">{t("Stages were recorded, but no durations were collected.")}</p>}
      </section>

      <section className="performance-section">
        <h3>{t("Model timing")}</h3>
        {calls.length ? <>
          <div className="table-wrap performance-table-wrap"><table className="performance-table performance-calls">
            <caption><strong>{t("Measured model calls")}</strong><span>{t("Calls remain in collection order; repeated stages are separate calls.")}</span></caption>
            <thead><tr><th scope="col">{t("Order")}</th><th scope="col">{t("Stage")} / {t("Model")}</th><th scope="col">{t("Elapsed")}</th><th scope="col">{t("Attempts")}</th><th scope="col">{t("Input tokens")}</th><th scope="col">{t("Output tokens")}</th></tr></thead>
            <tbody>{calls.map((call, index) => <tr key={index}>
              <td className="performance-order">{String(index + 1).padStart(2, "0")}</td>
              <td><span>{stageLabel(call.node)}</span>{call.node && <code className="performance-identifier">{call.node}</code>}<code className="performance-model">{call.model ?? missing}</code></td>
              <td className="performance-number" title={collectedNumber(call.elapsed_ms) ? `${call.elapsed_ms}ms` : undefined}>{duration(call.elapsed_ms)}</td>
              <td className="performance-number">{count(call.attempts)}</td><td className="performance-number">{count(call.input_tokens)}</td><td className="performance-number">{count(call.output_tokens)}</td>
            </tr>)}</tbody>
          </table></div>
          {reasons.map((reason) => <p className="helper" key={reason}>{t(reason)}</p>)}
          {calls.map((call, index) => {
            const timings = providerTimings(call);
            const usage = [["Cached input tokens", call.cached_input_tokens], ["Cache write input tokens", call.cache_write_input_tokens], ["Reasoning tokens", call.reasoning_tokens]] as const;
            const collectedUsage = usage.filter(([, value]) => collectedNumber(value));
            const retries = collectedNumber(call.attempts) && call.attempts > 0 ? call.attempts - 1 : undefined;
            return <div key={index}>
              {(collectedUsage.length > 0 || (retries !== undefined && retries > 0)) && <details className="performance-provider">
                <summary><span className="performance-order">{String(index + 1).padStart(2, "0")}</span> {stageLabel(call.node)} · {t("Token usage and retries")}</summary>
                <dl className="performance-facts">
                  {collectedUsage.map(([label, value]) => <div key={label}><dt>{t(label)}</dt><dd>{count(value)}</dd></div>)}
                  {retries !== undefined && <div><dt>{t("Retries")}</dt><dd>{count(retries)}</dd></div>}
                </dl>
              </details>}
              {timings.length > 0 && <details className="performance-provider">
                <summary><span className="performance-order">{String(index + 1).padStart(2, "0")}</span> {stageLabel(call.node)} · {t("Provider timing breakdown")}</summary>
                {timings.map((timing, record) => {
                  const speed = collectedNumber(timing.eval_count) && timing.eval_count > 0 && collectedNumber(timing.eval_duration_ms) && timing.eval_duration_ms > 0 ? timing.eval_count / timing.eval_duration_ms * 1000 : undefined;
                  return <div className="performance-timing-record" key={record}>
                    <p className="helper">{t("Timing record {number}", { number: record + 1 })}</p>
                    <dl className="performance-facts">
                      <div><dt>{t("Provider total time")}</dt><dd>{duration(timing.total_duration_ms)}</dd></div>
                      <div><dt>{t("Model loading")}</dt><dd>{duration(timing.load_duration_ms)}</dd></div>
                      <div><dt>{t("Input processing")}</dt><dd>{duration(timing.prompt_eval_duration_ms)}</dd></div>
                      <div><dt>{t("Generation")}</dt><dd>{duration(timing.eval_duration_ms)}</dd></div>
                      <div><dt>{t("Generated tokens / speed")}</dt><dd>{count(timing.eval_count)} / {collectedNumber(speed) ? `${speed.toLocaleString(locale, { maximumFractionDigits: 1 })} tok/s` : missing}</dd></div>
                    </dl>
                  </div>;
                })}
              </details>}
            </div>;
          })}
        </> : <p className="helper">{callsCollected ? count(0) : missing}</p>}
      </section>
      {!embedded && <details className="performance-settings"><summary>{t("Server-applied settings")}</summary>{data?.effective_settings ? <pre>{JSON.stringify(data.effective_settings, null, 2)}</pre> : <p className="helper">{missing}</p>}</details>}
    </div>;
  return embedded ? <div className="execution-performance">{content}</div> : <details className="execution-performance"><summary>{t("Execution performance")}</summary>{content}</details>;
}
