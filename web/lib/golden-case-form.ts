/** Keep positive and absent evaluation questions consistent without discarding authored evidence. */
export function patchGoldenCaseType(value: Record<string, unknown>, category: string): Record<string, unknown> {
  const absent = category === "absent";
  return { ...value, category, expected_label: absent ? "NOT_IN_DOCS" : "SUPPORTED", reference_answer: absent ? "NOT_IN_DOCS" : value.reference_answer === "NOT_IN_DOCS" ? "" : value.reference_answer };
}

/** Explain common authoring omissions before sending a save request; the API remains authoritative. */
export function goldenCaseFormError(value: Record<string, unknown> | null): string | null {
  if (!value) return "Enter valid question JSON.";
  if (typeof value.question !== "string" || !value.question.trim()) return "Enter the evaluation question.";
  if (typeof value.note !== "string" || !value.note.trim()) return "Enter a review note for this question.";
  const answers = Array.isArray(value.answers) ? value.answers : [];
  if (value.category === "absent") {
    if (answers.length) return "An absent-evidence question must have no source spans. Remove the spans or choose a supported question type.";
    if (value.expected_label !== "NOT_IN_DOCS" || value.reference_answer !== "NOT_IN_DOCS") return "An absent-evidence question must use NOT_IN_DOCS for its verdict and reference answer.";
    return null;
  }
  if (!answers.length) return "Add at least one source span for this question type: document ID, SHA-256, start and end positions.";
  if (value.expected_label !== "SUPPORTED") return "This question type must expect SUPPORTED.";
  if (typeof value.reference_answer !== "string" || !value.reference_answer.trim() || value.reference_answer === "NOT_IN_DOCS") return "Enter the reference answer supported by the original document.";
  for (const answer of answers) {
    const span = answer && typeof answer === "object" ? answer as Record<string, unknown> : {};
    if (typeof span.doc_id !== "string" || !span.doc_id.trim()) return "Enter a document ID for every source span.";
    if (typeof span.source_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(span.source_sha256)) return "Each source span needs a valid 64-character SHA-256.";
    if (!Number.isInteger(span.start_char) || !Number.isInteger(span.end_char) || Number(span.start_char) < 0 || Number(span.end_char) <= Number(span.start_char)) return "The source span end position must be greater than its nonnegative start position.";
  }
  return null;
}
