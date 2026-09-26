import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OpenAICallLimits, Readiness } from "@/lib/types";
import { DefaultRunLimits } from "./default-run-limits";
import { expectNoUnexpectedRequests, jsonResponse, stubHttp } from "@/lib/http-test-support";

const CAPS: OpenAICallLimits = {
  max_input_tokens: 12000, max_output_tokens: 600, max_cost_usd: "0.04",
  ceiling_max_input_tokens: 12000, ceiling_max_output_tokens: 600, ceiling_max_cost_usd: "0.04",
  source: "ceiling", editable: true, error: null,
};

const READINESS = {
  status: "ready", mode: "runtime", admin_mode: "live", policy_revision: "r", models: {}, review_enabled: true, active_review_model: "m",
  openai_call_limits: CAPS,
  corpus: { availability: "ready", database_connected: true, schema_status: "compatible", schema_message: null, documents: 1, chunks: 1, embedded_chunks: 1, pending_embeddings: 0, bm25_ready: true, writable: true },
} as unknown as Readiness;

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); expectNoUnexpectedRequests(); });

describe("DefaultRunLimits OpenAI per-call caps", () => {
  it("shows the ceiling read-only when the caps are not editable", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<DefaultRunLimits readiness={READINESS} capsEditable={false} />);
    expect(screen.getByRole("heading", { name: "OpenAI per-call caps" })).toBeInTheDocument();
    expect(screen.getByText("12,000")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save per-call caps" })).toBeNull();
    expect(screen.getByRole("heading", { name: "OpenAI per-call caps" }).parentElement).toHaveTextContent("raising them means editing .env");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("bounds the inputs by the ceiling and saves lower working values on the server", async () => {
    const saved = { ...CAPS, max_output_tokens: 300, source: "saved", ceiling_env_keys: {}, file_path: "data/local-settings/openai-limits.json" };
    const fetchMock = stubHttp({
      "GET /admin/openai/limits": () => jsonResponse({ ...CAPS, ceiling_env_keys: {}, file_path: "data/local-settings/openai-limits.json" }),
      "POST /admin/openai/limits": () => jsonResponse(saved),
    });
    render(<DefaultRunLimits readiness={READINESS} capsEditable />);
    const output = await screen.findByLabelText("Per-call output tokens");
    expect(output).toHaveAttribute("max", "600");
    fireEvent.change(output, { target: { value: "300" } });
    fireEvent.click(screen.getByRole("button", { name: "Save per-call caps" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Per-call caps saved on the server."));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(String(post[0])).toMatch(/\/admin\/openai\/limits\/?$/);
    expect(JSON.parse(String(post[1]?.body))).toEqual({ max_input_tokens: 12000, max_output_tokens: 300, max_cost_usd: "0.04" });
    expect(screen.getByText("Saved working value")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OpenAI per-call caps" }).parentElement).toHaveTextContent("cannot exceed the ceiling");
  });
});
