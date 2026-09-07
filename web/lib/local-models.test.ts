import { describe, expect, it } from "vitest";

import { localCpuWarning, localEngineStatus } from "./local-models";
import { DEFAULT_SESSION_PROFILE, type ReviewEngineState } from "./types";

describe("localEngineStatus", () => {
  it("translates every reason the readiness probe can report", () => {
    expect(localEngineStatus({ enabled: true, model: "gemma4:e4b", protocol: "ollama" })).toContain("Connected over ollama");
    expect(localEngineStatus({ enabled: false, reason: "disabled_in_prod" })).toContain("MODE=prod");
    expect(localEngineStatus({ enabled: false, reason: "unreachable" })).toContain("separately installed model server");
    expect(localEngineStatus({ enabled: false, reason: "not_configured" })).toContain("Settings › Local LLM");
    // An unknown or absent engine reads as unconfigured rather than as an internal enum.
    expect(localEngineStatus(undefined)).toContain("Checking");
  });
});


const now = Date.parse("2026-09-07T12:00:00Z");
const measuredLocal: ReviewEngineState = { enabled: true, protocol: "ollama", models: [
  { name: "answer", selectable: true, loaded: true, size_bytes: 100, family: null, parameter_size: null, quantization_level: null, capabilities: ["completion"], cpu_performance: { tokens_per_second: 10, measured_at: new Date(now - 1000).toISOString() } },
] };

describe("localCpuWarning", () => {
  it("warns only for the selected model using the strict 15 tok/s threshold", () => {
    const profile = { ...DEFAULT_SESSION_PROFILE, engine: "local" as const };
    expect(localCpuWarning(profile, measuredLocal, now)).toBe(10);
    expect(localCpuWarning({ ...profile, local_model: "other" }, measuredLocal, now)).toBeNull();
    expect(localCpuWarning(DEFAULT_SESSION_PROFILE, measuredLocal, now)).toBeNull();
  });

  it.each([15, 20, 0, -1, NaN, Infinity])("does not warn for fast or invalid speed %s", (speed) => {
    const model = measuredLocal.models![0];
    const local = { ...measuredLocal, models: [{ ...model, cpu_performance: { ...model.cpu_performance!, tokens_per_second: speed } }] };
    expect(localCpuWarning({ ...DEFAULT_SESSION_PROFILE, engine: "local" }, local, now)).toBeNull();
  });

  it.each([900000, 900001, -1, NaN])("rejects stale, future or malformed measurement age %s", (age) => {
    const model = measuredLocal.models![0];
    const measured_at = Number.isNaN(age) ? "unknown" : new Date(now - age).toISOString();
    const local = { ...measuredLocal, models: [{ ...model, cpu_performance: { ...model.cpu_performance!, measured_at } }] };
    expect(localCpuWarning({ ...DEFAULT_SESSION_PROFILE, engine: "local" }, local, now)).toBeNull();
  });

  it("requires a ready Ollama server with a loaded, selectable model and actual measurement", () => {
    const model = measuredLocal.models![0];
    const cases = [undefined, { ...measuredLocal, enabled: false }, { ...measuredLocal, protocol: "openai_responses" },
      ...[{ loaded: false }, { selectable: false }, { cpu_performance: null }].map((patch) => ({ ...measuredLocal, models: [{ ...model, ...patch }] })),
    ];
    for (const local of cases) expect(localCpuWarning({ ...DEFAULT_SESSION_PROFILE, engine: "local" }, local, now)).toBeNull();
  });
});
