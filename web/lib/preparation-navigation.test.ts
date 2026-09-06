import { expect, it } from "vitest";
import type { Readiness } from "./types";
import { preparationErrorTarget, preparationTarget } from "./preparation-navigation";

function readiness(values: Partial<Readiness["corpus"]>): Readiness {
  return { corpus: { database_connected: true, schema_status: "compatible", documents: 1, chunks: 3, pending_embeddings: 0, bm25_ready: true, ...values } } as Readiness;
}
it("chooses the earliest verified prerequisite", () => {
  expect(preparationTarget(readiness({ schema_status: "drifted", chunks: 0 }))).toBe("setup");
  expect(preparationTarget(readiness({ chunks: 0, pending_embeddings: 5 }))).toBe(2);
  expect(preparationTarget(readiness({ pending_embeddings: 5, bm25_ready: false }))).toBe(3);
  expect(preparationTarget(readiness({ bm25_ready: false }))).toBe(4);
});
it("keeps unknown infrastructure causes in setup diagnosis", () => {
  expect(preparationTarget(null)).toBe("setup");
  expect(preparationTarget(readiness({ database_connected: null }))).toBe("setup");
  expect(preparationTarget(readiness({}))).toBe("setup");
});

it("routes only typed source absence to acquisition", () => {
  expect(preparationErrorTarget("source_missing")).toBe(1);
  expect(preparationErrorTarget("sourcemissingerror")).toBe(1);
  expect(preparationErrorTarget("source_invalid")).toBe("setup");
  expect(preparationErrorTarget("worker_error")).toBe("setup");
});
