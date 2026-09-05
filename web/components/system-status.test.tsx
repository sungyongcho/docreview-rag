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
  localStorage.clear();
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

  it("localizes runtime states and model roles while retaining model identifiers and schema detail", async () => {
    vi.stubEnv("NEXT_PUBLIC_ADMIN_MODE", "live");
    vi.resetModules();
    const { SystemStatus: OperatorStatus } = await import("./system-status");
    const { I18nProvider, LOCALE_KEY } = await import("@/lib/i18n");
    localStorage.setItem(LOCALE_KEY, "ko");
    const readiness = {
      ...READINESS,
      models: Object.fromEntries(["agent", "decomposition", "translation"].map((role) => [role, READINESS.models.review])),
      corpus: { ...READINESS.corpus, schema_message: "compatible: original schema detail" },
      review_engines: { local: { enabled: false, reason: "unreachable" } },
    };
    render(<I18nProvider><OperatorStatus localAllowed localModel="user-model:original" readiness={readiness} loading={false} error="original API failure" onRefresh={vi.fn()} /></I18nProvider>);
    expect(document.querySelector(".status-metrics")).toHaveTextContent("준비 완료");
    expect(document.querySelector(".status-metrics")).toHaveTextContent("연결됨");
    expect(document.querySelector(".status-metrics")).toHaveTextContent("호환됨");
    for (const role of ["에이전트", "질문 분해", "질문 번역"]) expect(screen.getByText(role)).toBeInTheDocument();
    expect(screen.getAllByText("22,367")).toHaveLength(2);
    expect(screen.getByText(/compatible: original schema detail/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("original API failure");
    expect(screen.getAllByText("gpt-5.6-terra")).toHaveLength(3);
    expect(screen.getAllByText(/user-model:original/)).toHaveLength(4);
    expect(screen.getByRole("status")).not.toHaveTextContent("Unavailable. Check");
    expect(screen.getByRole("status")).toHaveTextContent("모델 서버에 연결할 수 없습니다.");
  });
});
