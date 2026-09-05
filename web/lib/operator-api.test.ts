import { afterEach, expect, it, vi } from "vitest";
import { OperatorRequestError, previewWipe } from "./operator-api";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("preserves the legacy error message and structured reset diagnosis", async () => {
  vi.stubEnv("NEXT_PUBLIC_OPERATOR_BASE_URL", "http://127.0.0.1:18081");
  vi.stubEnv("NEXT_PUBLIC_OPERATOR_TOKEN", "local-test-token");
  const diagnosis = { code: "runtime_file_permission", details: { path: "data/local-settings/local-llm.json" }, remediation: ["Ask the file owner to grant access."] };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Runtime file cannot be removed by this operator", diagnosis }), { status: 409 }));
  vi.stubGlobal("fetch", fetch);
  const error = await previewWipe().catch((reason: unknown) => reason);
  expect(error).toBeInstanceOf(OperatorRequestError);
  expect(error).toMatchObject({ message: "Runtime file cannot be removed by this operator", diagnosis });
  expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:18081/wipe/preview", expect.objectContaining({ method: "POST" }));
});
