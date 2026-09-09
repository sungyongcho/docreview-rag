import { expect, it } from "vitest";
import { CANNED_SUITES } from "./canned";
import { DEFAULT_PROFILE } from "./types";
import { evaluationDataset, evaluationSettings } from "./evaluation-labels";

it("keeps the filename and hash recorded at execution time", () => {
  const recorded = { golden_provenance: { filename: "original.json", dataset_id: "file:7", golden_revision_id: 7, golden_sha256: "old-hash" } };
  expect(evaluationDataset("sec-en", null, recorded, CANNED_SUITES, [])).toEqual({ key: "file:7", filename: "original.json", hash: "old-hash", builtin: false });
});
it("resolves old built-in records from their catalog but never guesses missing user filenames", () => {
  expect(evaluationDataset("dart-en", null, {}, CANNED_SUITES, []).filename).toBe("dart_retrieval.json");
  expect(evaluationDataset("dart-en", 99, {}, CANNED_SUITES, []).filename).toBeNull();
});
it("separates a file identity from changing contents", () => {
  const before = evaluationDataset("sec-en", null, { admin_identity: { golden_sha256: "before" } }, CANNED_SUITES, []);
  const after = evaluationDataset("sec-en", null, { admin_identity: { golden_sha256: "after" } }, CANNED_SUITES, []);
  expect(before.key).toBe(after.key);
  expect(before.hash).not.toBe(after.hash);
});
it("uses each recorded matrix arm instead of the job profile", () => {
  expect(evaluationSettings({ strategy: "lexical", lexical_ranker: "bm25", k: 9, target_tokens: 1024 }, "en", DEFAULT_PROFILE)).toBe("lexical · bm25 · k 9 · 1024 tokens");
  expect(evaluationSettings({}, "en")).toBe("Settings not recorded");
});
