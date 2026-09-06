import { describe, expect, it } from "vitest";

import { STAGE_COPY, STAGE_ORDER } from "./pipeline";
import type { Pipeline, Stage, StageId, StageStatus } from "./pipeline";
import { diagnosePreparation } from "./preparation-diagnostics";
import type { PreparationRuntime } from "./preparation-diagnostics";

const HEALTHY: PreparationRuntime = { databaseConnected: true, schemaStatus: "ok", writable: true };

/** Build a stage snapshot without implying a command has run. */
function snapshot(id: StageId, status: StageStatus, overrides: Partial<Stage> = {}): Pipeline {
  return {
    source: "admin", readOnly: false, corpusReady: false, next: null,
    stages: STAGE_ORDER.map((stageId, order) => ({
      id: stageId, order: order + 1, ...STAGE_COPY[stageId], status: stageId === id ? status : "done",
      statusDetail: "", numbers: [], hint: "", action: null, job: null, progress: null, blockedBy: null,
      ...(stageId === id ? overrides : {}),
    })),
  };
}

describe("diagnosePreparation", () => {
  it.each(STAGE_ORDER)("reports observed completion and activity for %s", (id) => {
    expect(diagnosePreparation(id, snapshot(id, "done"), HEALTHY).state).toBe("complete");
    for (const status of ["running", "queued"] as const) {
      expect(diagnosePreparation(id, snapshot(id, status), HEALTHY).state).toBe("running");
    }
    expect(diagnosePreparation(id, snapshot(id, "unknown"), HEALTHY).state).toBe("checking");
  });

  it.each(STAGE_ORDER.filter((id) => id !== "answer_model"))("keeps a recheck of %s separate from executing it", (id) => {
    const pipeline = snapshot(id, "action");
    const first = diagnosePreparation(id, pipeline, HEALTHY);
    expect(first.state).toBe("ready");
    expect(first.returnTo).toBe(id);
    expect(first.terminalSteps).toEqual([]);
    expect(diagnosePreparation(id, pipeline, HEALTHY)).toEqual(first);
  });

  it.each([
    ["index", "filings"], ["embeddings", "index"], ["lexical", "index"],
    ["ask", "embeddings"], ["ask", "lexical"], ["evaluate", "index"],
    ["evaluate", "embeddings"], ["evaluate", "lexical"], ["evaluate", "answer_model"],
  ] as const)("routes %s to its reported prerequisite %s", (id, blockedBy) => {
    const diagnosis = diagnosePreparation(id, snapshot(id, "blocked", { blockedBy }), HEALTHY);
    expect(diagnosis.state).toBe("blocked");
    expect(diagnosis.returnTo).toBe(blockedBy);
    expect(diagnosis.detail).toContain(STAGE_COPY[blockedBy].title);
  });

  it("preserves schema drift while directing indexing to setup", () => {
    const diagnosis = diagnosePreparation("index", snapshot("index", "action"), { ...HEALTHY, schemaStatus: "drifted" });
    expect(diagnosis.returnTo).toBe("setup");
    expect(diagnosis.detail).toContain("cannot repair");
    expect(diagnosis.terminalSteps.map((step) => step.command)).toEqual(["uv run python -m scripts.schema_status check", "uv run python -m scripts.schema_status recover --return-stage index"]);
  });

  it("permits source acquisition during schema drift only with reachable job storage and writable files", () => {
    const pipeline = snapshot("filings", "action");
    const runtime = { ...HEALTHY, schemaStatus: "drifted" };
    expect(diagnosePreparation("filings", pipeline, runtime).state).toBe("ready");
    expect(diagnosePreparation("filings", pipeline, { ...runtime, writable: false }).state).toBe("blocked");
    expect(diagnosePreparation("filings", pipeline, { ...runtime, writable: null }).state).toBe("checking");
    expect(diagnosePreparation("filings", pipeline, { ...runtime, databaseConnected: false }).terminalSteps[0].command).toBe("rag-dev up --build -d");
  });

  it("prepares an empty schema without claiming that it was prepared", () => {
    const diagnosis = diagnosePreparation("index", snapshot("index", "action"), { ...HEALTHY, schemaStatus: "empty" });
    expect(diagnosis.state).toBe("blocked");
    expect(diagnosis.terminalSteps[0].command).toBe("uv run python -m scripts.schema_status prepare");
  });

  it("does not trust stale completion when database health is unavailable", () => {
    expect(diagnosePreparation("ask", snapshot("ask", "done"), { ...HEALTHY, databaseConnected: false }).state).toBe("blocked");
    expect(diagnosePreparation("index", snapshot("index", "done"), { ...HEALTHY, schemaStatus: null }).state).toBe("checking");
  });

  it("routes missing answer configuration to its independent stage", () => {
    const diagnosis = diagnosePreparation("answer_model", snapshot("answer_model", "blocked"), { databaseConnected: false, schemaStatus: null, writable: false });
    expect(diagnosis.returnTo).toBe("answer_model");
    expect(diagnosis.terminalSteps).toEqual([]);
  });

  it("reports failed jobs without claiming a repair or a successful retry", () => {
    const diagnosis = diagnosePreparation("embeddings", snapshot("embeddings", "failed", { hint: "Provider request failed." }), HEALTHY);
    expect(diagnosis.state).toBe("blocked");
    expect(diagnosis.detail).toBe("Provider request failed.");
    expect(diagnosis.returnTo).toBe("embeddings");
  });
});
