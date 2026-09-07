import type { Readiness, ReviewEngineState, ReviewSessionProfile } from "./types";

/** Why the local engine is not serving, in the reader's terms rather than the API's. */
export function localEngineStatus(engine: ReviewEngineState | undefined): string {
  if (!engine) return "Checking the local model server…";
  if (engine.enabled) return `Connected over ${engine.protocol ?? "its protocol"}. Model information refreshes automatically every 30 seconds while this tab is visible.`;
  switch (engine.reason) {
    case "disabled_in_prod": return "Disabled because MODE=prod. A production build never answers from a local model.";
    case "no_answer_models": return "Connected, but no verified answer model is available. Install an answer model or retry model discovery.";
    case "unreachable": return "Unavailable. Check that the separately installed model server is running and reachable from the app.";
    case "api_unavailable": return "Connection check failed. Displayed model details are from the last successful check.";
    case "disconnected": return "Disconnected. Open Settings › Local LLM to connect again.";
    default: return "Not configured. Open Settings › Local LLM to connect a server.";
  }
}

/** Return the discovered choice without replacing an explicit, now-missing model. */
export function selectedLocalModel(profile: ReviewSessionProfile, local: ReviewEngineState | undefined): string | null {
  if (profile.local_model) return profile.local_model;
  const available = local?.enabled ? local.models?.filter((model) => model.selectable) ?? [] : [];
  return available.length === 1 ? available[0].name : null;
}

/** Explain why the selected local engine must not receive a new question. */
export function localModelIssue(profile: ReviewSessionProfile, readiness: Readiness | null): string | null {
  if (profile.engine !== "local") return null;
  const local = readiness?.review_engines?.local;
  if (!local) return "Checking the local model server…";
  if (!local.enabled) return "Local LLM is unavailable. Check the server connection in Settings › Local LLM.";
  const selected = selectedLocalModel(profile, local);
  if (!selected) return "Choose a local answer model in the controls above the conversation input.";
  if (!local.models?.some((model) => model.name === selected && model.selectable)) {
    return "The selected local model is unavailable. Choose an available model in the controls above the conversation input.";
  }
  return null;
}

/** Below 15 generated tokens/s, a CPU model merits explicit run-limit/evidence guidance. */
export const SLOW_LOCAL_CPU_TOKENS_PER_SECOND = 15;

/** Use only recent server measurements for the selected, currently loaded Ollama model. */
export function localCpuWarning(profile: ReviewSessionProfile, local: ReviewEngineState | undefined, now = Date.now()): number | null {
  if (profile.engine !== "local" || !local?.enabled || local.protocol !== "ollama") return null;
  const model = local.models?.find((item) => item.name === selectedLocalModel(profile, local) && item.selectable && item.loaded === true);
  const sample = model?.cpu_performance;
  if (!sample || !Number.isFinite(sample.tokens_per_second) || sample.tokens_per_second <= 0 || sample.tokens_per_second >= SLOW_LOCAL_CPU_TOKENS_PER_SECOND) return null;
  const age = now - Date.parse(sample.measured_at);
  return Number.isFinite(age) && age >= 0 && age < 15 * 60 * 1000 ? sample.tokens_per_second : null;
}
