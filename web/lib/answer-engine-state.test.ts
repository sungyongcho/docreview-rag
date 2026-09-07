import { describe, expect, it } from "vitest";
import { answerEngineStates, answerEngineSummary } from "./answer-engine-state";
import { translate } from "./i18n";
import type { Readiness, ReviewEngineState } from "./types";

const now = Date.parse("2026-09-08T12:00:00Z");
const local: ReviewEngineState = { enabled: true, protocol: "ollama", model: "gemma", models: [{ name: "gemma", selectable: true, loaded: true, placement: "cpu", cpu_performance: { tokens_per_second: 20, measured_at: new Date(now - 1000).toISOString() }, size_bytes: 100, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"] }] };
/** Keep the matrix focused on existing readiness facts. */
function ready(openai: ReviewEngineState, engine: ReviewEngineState): Readiness {
  return { status: "ready", mode: "runtime", admin_mode: "live", models: {}, policy_revision: "test", review_enabled: Boolean(openai.enabled || engine.enabled), active_review_model: null, review_engines: { openai, local: engine }, corpus: { availability: "ready", database_connected: true, schema_status: "compatible", schema_message: null, documents: 1, chunks: 1, embedded_chunks: 1, pending_embeddings: 0, bm25_ready: true, writable: true } };
}
const absent = { enabled: false, reason: "not_configured" };
const openai = { enabled: true, model: "gpt", key_slot: "dev" };
describe("answer engine matrix", () => {
  it.each([
    ["both", openai, local, ["green", "green"]],
    ["OpenAI only", openai, absent, ["green", "grey"]],
    ["local only", {}, local, ["grey", "green"]],
    ["neither", {}, absent, ["grey", "grey"]],
    ["slow CPU", openai, { ...local, models: [{ ...local.models![0], cpu_performance: { tokens_per_second: 10, measured_at: new Date(now - 1000).toISOString() } }] }, ["green", "amber"]],
    ["unloaded", openai, { ...local, models: [{ ...local.models![0], loaded: false }] }, ["green", "amber"]],
    ["missing key", { enabled: false, protocol: "responses", model: null, key_slot: null }, absent, ["amber", "grey"]],
    ["empty server", openai, { enabled: false, protocol: "ollama", reason: "no_answer_models", models: [] }, ["green", "amber"]],
  ])("derives %s", (_name, first, second, lights) => {
    expect(answerEngineStates(ready(first as ReviewEngineState, second as ReviewEngineState), null, now).map((row) => row.light)).toEqual(lights);
  });
  it("names serving engines and translates the limited reason", () => {
    const both = answerEngineStates(ready(openai, local), null, now);
    expect(answerEngineSummary(both)).toBe("OpenAI ready · Local ready");
    expect(translate("ko", answerEngineSummary(both))).toBe("OpenAI 준비 · 로컬 준비");
    const unloaded = answerEngineStates(ready(openai, { ...local, models: [{ ...local.models![0], loaded: false }] }), null, now);
    expect(answerEngineSummary(unloaded)).toBe("OpenAI only ready · Local: Model not loaded");
    expect(translate("ko", answerEngineSummary(unloaded))).toBe("OpenAI만 준비 · 로컬: 모델 미적재");
    expect(unloaded[1].speed).toBeNull();
  });
  it("expires CPU timing and preserves explicit missing selections", () => {
    expect(answerEngineStates(ready(openai, local), null, now + 900000)[1].speed).toBeNull();
    expect(answerEngineStates(ready(openai, local), "removed", now)[1]).toMatchObject({ light: "amber", reason: "Selected model unavailable", model: "removed" });
  });
});
