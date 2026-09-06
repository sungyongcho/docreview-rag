import type { Pipeline, StageId } from "./pipeline";

export interface TerminalStep {
  reason: string;
  command: string;
  expected: string;
}

export interface Diagnosis {
  state: "checking" | "ready" | "complete" | "blocked" | "running";
  title: string;
  detail: string;
  returnTo: StageId | "setup" | null;
  terminalSteps: TerminalStep[];
}

export interface PreparationRuntime {
  databaseConnected: boolean | null;
  schemaStatus: string | null;
  writable: boolean | null;
}

const CHECK_SCHEMA: TerminalStep = {
  reason: "Inspect the database layout without changing stored data.",
  command: "uv run python -m scripts.schema_status check",
  expected: "Read the reported schema status, then re-check this step.",
};

/** Diagnose observed preparation state; terminal commands are suggestions, never evidence. */
export function diagnosePreparation(stageId: StageId, pipeline: Pipeline, runtime: PreparationRuntime): Diagnosis {
  const stage = pipeline.stages.find((item) => item.id === stageId);
  const result = (state: Diagnosis["state"], title: string, detail: string, returnTo: Diagnosis["returnTo"] = null, terminalSteps: TerminalStep[] = []): Diagnosis => ({ state, title, detail, returnTo, terminalSteps });
  if (!stage || pipeline.source === "pending" || stage.statusDetail === "API unavailable") {
    return result("checking", "Waiting for current state", "Refresh runtime status before deciding what to prepare.");
  }
  if (pipeline.readOnly || stage.status === "readonly") {
    return result("blocked", "Read-only workspace", "Preparation actions require a live administrator workspace.", "setup");
  }
  if (stage.status === "running" || stage.status === "queued") {
    return result("running", stage.status === "queued" ? "This step is queued" : "This step is running", "Follow the existing job. Re-check after it finishes; do not start a duplicate.", stageId);
  }
  // Answer configuration is independent of the corpus database and source directory.
  if (stageId !== "answer_model") {
    if (runtime.databaseConnected === false) {
      return result("blocked", "Database is unreachable", "The app needs a reachable database, including storage for preparation jobs.", "setup", [{
        reason: "Start the local development stack and inspect its startup output.",
        command: "rag-dev up --build -d",
        expected: "The database and app should become reachable. Re-check to verify their actual state.",
      }]);
    }
    if (runtime.databaseConnected === null) {
      return result("checking", "Database state is unknown", "Wait for a current database health response.");
    }
    // Acquisition writes source files; schema compatibility gates indexing, not files.
    if (stageId !== "filings") {
      if (runtime.schemaStatus === "drifted") {
        return result("blocked", "Database schema is incompatible", "A rebuild or restart cannot repair an incompatible database layout. Preserve the database and follow the setup recovery guide before indexing.", "setup", [CHECK_SCHEMA, { reason: "Create a separate recovery checkout; preserve the original database and files.", command: "uv run python -m scripts.schema_status recover --return-stage " + stageId, expected: "Open the printed recovery URL and re-check this step. The original schema remains unchanged." }]);
      }
      if (runtime.schemaStatus === "empty") {
        return result("blocked", "Database schema is empty", "Prepare the empty database schema, then re-check this step.", "setup", [{
          reason: "Create the schema only when the database is empty.",
          command: "uv run python -m scripts.schema_status prepare",
          expected: "The command should report a compatible schema. Re-check to confirm; existing incompatible data is not reset.",
        }]);
      }
      if (runtime.schemaStatus === "unavailable") {
        return result("blocked", "Database schema is unavailable", "Inspect the schema status and resolve the reported error before continuing.", "setup", [CHECK_SCHEMA]);
      }
      if (runtime.schemaStatus !== "ok" && runtime.schemaStatus !== "compatible") {
        return result("checking", "Schema state is unknown", "Wait for a current schema status before preparing this step.");
      }
    } else if (runtime.writable !== true) {
      return runtime.writable === null
        ? result("checking", "Source directory state is unknown", "Wait for the source directory write check.")
        : result("blocked", "Source directory is not writable", "Check the data directory permissions and HOST_GID configuration in the setup guide, then re-check.", "setup");
    }
  }
  if (stage.status === "unknown") {
    return result("checking", "Waiting for current state", "This step has not received enough current information yet.");
  }
  if (stage.status === "done") {
    return result("complete", "This step is already complete", "The current application state satisfies this step. No preparation command is needed.", stageId);
  }
  if (stage.blockedBy) {
    const predecessor = pipeline.stages.find((item) => item.id === stage.blockedBy);
    return result("blocked", "Prepare the required step first", predecessor ? `Open ${predecessor.title} and inspect its current state.` : "Inspect the required earlier step.", stage.blockedBy);
  }
  if (stageId === "answer_model") {
    return result("blocked", "Configure an answer model", "Choose and configure an available answer model. Evidence-only search remains available without one.", "answer_model");
  }
  if (stage.status === "blocked") {
    return result("blocked", "This step needs attention", stage.hint || "Inspect the reported prerequisite before continuing.", stageId);
  }
  if (stage.status === "failed") {
    return result("blocked", "The previous job did not complete", stage.hint || "Inspect the job error before retrying. Re-checking does not run or repair the job.", stageId);
  }
  return result("ready", "This step is ready to run", "The current prerequisites are available. Return to this step and run its action; re-checking does not execute it.", stageId);
}
