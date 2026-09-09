import { expect, it } from "vitest";
import { goldenCaseFormError, patchGoldenCaseType } from "./golden-case-form";
const absent = { question: "Question?", note: "Note", category: "absent", answers: [], expected_label: "NOT_IN_DOCS", reference_answer: "NOT_IN_DOCS" };
it("switches to supported without keeping an absent reference answer", () => {
  const positive = patchGoldenCaseType(absent, "exact_number");
  expect(positive.expected_label).toBe("SUPPORTED");
  expect(positive.reference_answer).toBe("");
  expect(goldenCaseFormError(positive)).toContain("Add at least one source span");
});
it("retains evidence when switching type and requires explicit removal for absent cases", () => {
  const value = patchGoldenCaseType({ ...absent, answers: [{ doc_id: "source" }] }, "absent");
  expect(value.answers).toHaveLength(1);
  expect(goldenCaseFormError(value)).toContain("must have no source spans");
});
it("accepts a complete positive question and rejects contradictory verdicts or invalid spans", () => {
  const value = { ...absent, category: "exact_number", expected_label: "SUPPORTED", reference_answer: "42", answers: [{ doc_id: "doc", source_sha256: "a".repeat(64), start_char: 0, end_char: 2 }] };
  expect(goldenCaseFormError(value)).toBeNull();
  expect(goldenCaseFormError({ ...value, expected_label: "NOT_IN_DOCS" })).toContain("SUPPORTED");
  expect(goldenCaseFormError({ ...value, answers: [{ ...value.answers[0], end_char: 0 }] })).toContain("end position");
  expect(goldenCaseFormError(absent)).toBeNull();
});
