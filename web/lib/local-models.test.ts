import { describe, expect, it } from "vitest";

import { localEngineStatus } from "./local-models";

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
