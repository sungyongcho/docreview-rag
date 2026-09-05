import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Readiness, ReviewEngineState } from "@/lib/types";
import { SystemStatus } from "./system-status";

const READINESS: Readiness = {
  environment: "dev",
  status: "ready",
  mode: "runtime",
  admin_mode: "live",
  policy_revision: "2026-09-01",
  models: {
    review: { default: "gpt-5.6-terra", allowed: ["gpt-5.6-terra"], reasoning_effort: "medium", dimensions: null },
    embedding: { default: "text-embedding-3-large", allowed: ["text-embedding-3-large"], reasoning_effort: null, dimensions: 384 },
  },
  review_enabled: true,
  active_review_model: "gpt-5.6-terra",
  corpus: {
    availability: "ready", database_connected: true, schema_status: "compatible", schema_message: "ok",
    documents: 30, chunks: 22367, embedded_chunks: 22367, pending_embeddings: 0, bm25_ready: true, writable: true,
  },
};

function withLocal(local: ReviewEngineState): Readiness {
  return { ...READINESS, review_engines: { openai: { enabled: true }, local } };
}

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("SystemStatus", () => {
  it("omits the local policy panel from a build that cannot run a local model", () => {
    render(<SystemStatus readiness={withLocal({ enabled: true, model: "gemma4:e4b" })} loading={false} error="" onRefresh={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "OpenAI model policy" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Local model policy" })).toBeNull();
  });

  it("lists the roles a local model serves and locks the embedding row", async () => {
    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.resetModules();
    const operator = await import("./system-status");
    render(
      <operator.SystemStatus
        localAllowed
        readiness={withLocal({ enabled: true, model: "gemma4:e4b", protocol: "ollama" })}
        loading={false}
        error=""
        onRefresh={vi.fn()}
      />,
    );

    const panel = screen.getByRole("heading", { name: "Local model policy" }).closest("section")!;
    for (const role of ["review", "routing", "intent", "chat"]) {
      expect(within(panel).getByText(role)).toBeInTheDocument();
    }
    // Every served role names the same model, because the local engine has only one.
    expect(within(panel).getAllByText("gemma4:e4b")).toHaveLength(4);
    // Embedding identity is stored per vector, so this row reports OpenAI and says why.
    const locked = document.querySelector(".policy-locked");
    expect(locked).toHaveTextContent("embedding");
    expect(locked).toHaveTextContent("text-embedding-3-large");
    expect(locked).toHaveTextContent("never local");
    expect(screen.getByText(/Connected over ollama/)).toBeInTheDocument();
  });

  it("hides local policy when a dev bundle talks to a production runtime", async () => {
    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.resetModules();
    const operator = await import("./system-status");
    render(
      <operator.SystemStatus
        localAllowed
        readiness={{ ...withLocal({ enabled: false, reason: "disabled_in_prod" }), environment: "prod" }}
        loading={false}
        error=""
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.queryByRole("heading", { name: "Local model policy" })).not.toBeInTheDocument();
    expect(screen.getByText("PROD")).toBeInTheDocument();
  });
});
