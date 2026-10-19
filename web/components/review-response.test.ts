import { describe, expect, it } from "vitest";

import { terminalMessage } from "./review-response";
import type { ReviewRun } from "@/lib/types";

const citation = {
  chunk_id: 7,
  doc_id: "AMD-FY2024",
  citation: "AMD FY2024 · Item 8",
  start_char: 0,
  end_char: 120,
  source_sha256: "a".repeat(64),
};

/** Build one finished run carrying a document review report. */
function run(report: Record<string, unknown>): ReviewRun {
  return { run_id: "run-1", status: "ok", report: { report_kind: "document_review", reasons: [], ...report } } as unknown as ReviewRun;
}

describe("terminal review message", () => {
  it("shows the server's period statement and keeps the citations of a period mismatch", () => {
    const message = terminalMessage(run({
      label: "PERIOD_MISMATCH",
      answer: "The cited evidence does not report this for 2024. The figures 22,680 are for 2023.",
      citations: [citation],
      rationale: "The cited figures belong to a different period than the question asks about.",
    }));

    expect(message.text).toBe("The cited evidence does not report this for 2024. The figures 22,680 are for 2023.");
    expect(message.evidenceLabel).toBe("Cited evidence — different period");
    expect(message.citations).toBe(1);
  });

  it("keeps supported answers and absence explanations unchanged", () => {
    expect(terminalMessage(run({ label: "SUPPORTED", answer: "Revenue grew.", citations: [citation], rationale: "Stated." })).text).toBe("Revenue grew.");
    const absent = terminalMessage(run({ label: "NOT_IN_DOCS", answer: "NOT_IN_DOCS", citations: [], rationale: "No evidence." }));
    expect(absent.text).toBe("No evidence.");
    expect(absent.evidenceLabel).toBe("Related evidence — not direct support");
  });
});
