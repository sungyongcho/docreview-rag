import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); window.localStorage.clear(); });
import type { Readiness, LocalModelInfo } from "@/lib/types";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
it("hides the engine picker in public builds and reports checking in development", async () => {
  const { LocalEngineSettings } = await import("./local-engine-settings");
  render(<LocalEngineSettings profile={DEFAULT_SESSION_PROFILE} readiness={null} onChange={vi.fn()} />);
  expect(screen.queryByLabelText("Answer engine")).not.toBeInTheDocument();
  cleanup(); vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live"); vi.resetModules();
  const { LocalEngineSettings: LivePicker } = await import("./local-engine-settings");
  render(<LivePicker profile={DEFAULT_SESSION_PROFILE} readiness={null} onChange={vi.fn()} />);
  expect(screen.getByRole("option", { name: "Local LLM (Checking…)" })).toBeDisabled();
});
/** Two discovered answer models, including enough metadata to exercise selection. */
function model(name: string): LocalModelInfo {
  return { name, selectable: true, size_bytes: 123, family: "test", parameter_size: "4B", quantization_level: "Q4", capabilities: ["completion"], loaded: false };
}

it("disables an unavailable local engine and preserves a missing explicit model", async () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  vi.resetModules();
  const { LocalEngineSettings: OperatorSettings } = await import("./local-engine-settings");
  const onChange = vi.fn();
  const readiness: Readiness = {
    status: "ready", mode: "runtime", admin_mode: "live", policy_revision: "test", models: {},
    review_enabled: true, active_review_model: null,
    review_engines: { local: { enabled: true, models: [model("first"), model("second")] } },
    corpus: { availability: "ready", database_connected: true, schema_status: "compatible", schema_message: "ok", documents: 1, chunks: 1, embedded_chunks: 1, pending_embeddings: 0, bm25_ready: true, writable: true },
  };
  const props = { onChange };
  const { rerender } = render(<OperatorSettings {...props} readiness={readiness} profile={{ ...DEFAULT_SESSION_PROFILE, engine: "local" }} />);
  expect(screen.getByRole("option", { name: "Local LLM (Selected)" })).toBeEnabled();
  expect(screen.getByLabelText("Local model")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Local model"), { target: { value: "second" } });
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ local_model: "second" }));

  rerender(<OperatorSettings {...props} readiness={readiness} profile={{ ...DEFAULT_SESSION_PROFILE, engine: "local", local_model: "removed" }} />);
  expect(screen.getByLabelText("Local model")).toHaveValue("removed");
  expect(screen.getByRole("option", { name: "removed (Unavailable)" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("selected local model is unavailable");

  const offline = { ...readiness, review_engines: { local: { enabled: false, reason: "unreachable", models: [] } } };
  rerender(<OperatorSettings {...props} readiness={offline} profile={{ ...DEFAULT_SESSION_PROFILE, engine: "local", local_model: "second" }} />);
  expect(screen.getByRole("option", { name: "Local LLM (Unavailable)" })).toBeDisabled();
  expect(screen.getByLabelText("Local model")).toBeDisabled();
  expect(screen.getByLabelText("Answer engine")).toHaveValue("local");
});

it("preserves a long model identifier in the selector and selected status", async () => {
  vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
  vi.resetModules();
  const { LocalEngineSettings } = await import("./local-engine-settings");
  const name = "model_" + "x".repeat(200);
  const ready: Readiness = {
    status: "ready", mode: "runtime", admin_mode: "live", policy_revision: "test", models: {}, review_enabled: true, active_review_model: null,
    review_engines: { local: { enabled: true, protocol: "ollama", models: [model(name)] } },
    corpus: { availability: "ready", database_connected: true, schema_status: "compatible", schema_message: "ok", documents: 1, chunks: 1, embedded_chunks: 1, pending_embeddings: 0, bm25_ready: true, writable: true },
  };
  render(<div className="composer-controls"><LocalEngineSettings profile={{ ...DEFAULT_SESSION_PROFILE, engine: "local", local_model: name }} readiness={ready} onChange={vi.fn()} /></div>);
  expect(screen.getByLabelText("Local model")).toHaveValue(name);
  expect(screen.getByRole("status")).toHaveTextContent(name);
});
