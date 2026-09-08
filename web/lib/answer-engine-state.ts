import { localCpuWarning } from "./local-models";
import { DEFAULT_SESSION_PROFILE, type LocalModelInfo, type Readiness } from "./types";

export interface AnswerEngineState {
  id: "openai" | "local";
  label: "OpenAI" | "Local";
  light: "green" | "amber" | "grey";
  reason: string;
  model: string | null;
  keySlot?: string | null;
  server?: string;
  placement?: LocalModelInfo["placement"];
  speed?: number | null;
}

/** Derive display readiness; a null conversation choice requires selection when several models exist. */
export function answerEngineStates(readiness: Readiness | null, localModel?: string | null, now = Date.now()): AnswerEngineState[] {
  const engines = readiness?.review_engines;
  const openai = engines?.openai;
  // Older readiness snapshots omitted per-engine metadata.
  const openaiEnabled = openai?.enabled ?? (!engines && readiness?.review_enabled === true);
  const first: AnswerEngineState = {
    id: "openai", label: "OpenAI", light: "grey", reason: "Not configured",
    model: openai?.model ?? readiness?.active_review_model ?? null, keySlot: openai?.key_slot,
  };
  if (!readiness) first.reason = "Checking…";
  else if (openaiEnabled) { first.light = "green"; first.reason = "Ready to answer"; }
  else if (openai?.key_slot || openai?.model || openai?.protocol || openai?.reason) {
    first.light = "amber"; first.reason = openai.reason ?? "No API key";
  }
  const local = engines?.local;
  const models = local?.models?.filter((item) => item.selectable) ?? [];
  const name = localModel === null
    ? (models.length === 1 ? models[0].name : null)
    : localModel ?? local?.model ?? models.find((item) => item.loaded)?.name ?? models[0]?.name ?? null;
  const model = models.find((item) => item.name === name);
  const sample = model?.cpu_performance;
  const age = sample ? now - Date.parse(sample.measured_at) : NaN;
  const speed = model?.loaded && Number.isFinite(sample?.tokens_per_second) && sample!.tokens_per_second > 0 && age >= 0 && age < 15 * 60 * 1000 ? sample!.tokens_per_second : null;
  const second: AnswerEngineState = {
    id: "local", label: "Local", light: "grey", reason: "Not configured", model: name,
    server: local?.protocol === "ollama" ? "Ollama" : local?.protocol === "openai_responses" ? "OpenAI-compatible server" : undefined,
    placement: model?.placement, speed,
  };
  if (!readiness) second.reason = "Checking…";
  else if (local?.enabled) {
    second.light = "green"; second.reason = "Ready to answer";
    if (!name) { second.light = "amber"; second.reason = "Choose a model"; }
    else if (localModel && !model) { second.light = "amber"; second.reason = "Selected model unavailable"; }
    else if (model?.loaded === false) { second.light = "amber"; second.reason = "Model not loaded"; }
    else if (localCpuWarning({ ...DEFAULT_SESSION_PROFILE, engine: "local", local_model: name }, local, now) !== null) {
      second.light = "amber"; second.reason = "Slow CPU (below 15 tok/s)";
    }
  } else if (local?.reason && !["not_configured", "disconnected", "disabled_in_prod"].includes(local.reason)) {
    second.light = "amber";
    second.reason = ({ no_answer_models: "Model download required", unreachable: "Server unreachable", api_unavailable: "Connection check failed" } as Record<string, string>)[local.reason] ?? local.reason;
  } else if (local?.reason === "disabled_in_prod") second.reason = "Disabled in production";
  else if (local?.reason === "disconnected") second.reason = "Disconnected";
  return [first, second];
}

/** Name the ready engines and explain every limited or absent row. */
export function answerEngineSummary(engines: AnswerEngineState[]): string {
  const ready = engines.filter((engine) => engine.light === "green").length;
  return engines.map((engine) => engine.light === "green" ? `${engine.label} ${ready === 1 && engines.length > 1 ? "only ready" : "ready"}` : `${engine.label}: ${engine.reason}`).join(" · ");
}
