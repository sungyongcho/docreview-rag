import { describe, expect, it } from "vitest";

import { verdictPill } from "./review-message";
import { terminalMessage } from "./review-response";
import { KO } from "@/lib/messages-ko";
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

  it("shows the server's hold notice for withheld figures, distinct from absence", () => {
    const notice = "The cited evidence names this item, but the currency of its figures could not be confirmed, so no figure is reported.";
    const message = terminalMessage(run({
      label: "UNVERIFIED",
      answer: notice,
      citations: [citation],
      rationale: "The comparison did not establish the currency.",
      reasons: [{ code: "figures_withheld", causes: ["currency"], figures: ["25,785"] }],
    }));

    expect(message.text).toBe(notice);
    expect(message.text).not.toContain("25,785");
    expect(message.evidenceLabel).toBe("Cited evidence — figures withheld");
    expect(message.evidenceLabel).not.toBe("Related evidence — not direct support");
    expect(message.citations).toBe(1);
    const pill = verdictPill({ id: "a", role: "assistant", ...message });
    expect(pill?.text).toBe("Currency not confirmed");
    expect(pill?.className).toContain("withheld");
  });

  it.each([
    [["scale"], "Unit not confirmed", "단위 미확인"],
    [["currency"], "Currency not confirmed", "통화 미확인"],
    [["direction"], "Gain/loss direction not confirmed", "손익 방향 미확인"],
    [["scale", "currency"], "Unit and currency not confirmed", "단위·통화 미확인"],
    [["scale", "direction"], "Unit and gain/loss direction not confirmed", "단위·손익 방향 미확인"],
    [["currency", "direction"], "Currency and gain/loss direction not confirmed", "통화·손익 방향 미확인"],
    [["scale", "currency", "direction"], "Unit, currency and gain/loss direction not confirmed", "단위·통화·손익 방향 미확인"],
  ])("keeps typed causes %j and localizes only their notice", (causes, english, korean) => {
    const message = terminalMessage(run({
      label: "UNVERIFIED", answer: "Server notice", citations: [citation], rationale: "Checked",
      reasons: [{ code: "figures_withheld", figures: ["25,785"], causes }],
    }));
    expect(message.withholdingCauses).toEqual(causes);
    const pill = verdictPill({ id: "a", role: "assistant", ...message });
    expect(pill?.text).toBe(english);
    expect(KO[pill!.text]).toBe(korean);
  });

  it("gives every report label its own verdict pill", () => {
    const pills = ["SUPPORTED", "PERIOD_MISMATCH", "UNVERIFIED", "NOT_IN_DOCS"].map((label) => {
      const absent = label === "NOT_IN_DOCS";
      const message = terminalMessage(run({ label, answer: absent ? "NOT_IN_DOCS" : "Notice.", citations: absent ? [] : [citation], rationale: "Reason." }));
      return verdictPill({ id: label, role: "assistant", ...message })?.text;
    });
    expect(pills).toEqual(["Supported · 1 citation", "Different period", "Figures withheld", "Not in documents"]);
  });

  it("keeps supported answers and absence explanations unchanged", () => {
    expect(terminalMessage(run({ label: "SUPPORTED", answer: "Revenue grew.", citations: [citation], rationale: "Stated." })).text).toBe("Revenue grew.");
    const absent = terminalMessage(run({ label: "NOT_IN_DOCS", answer: "NOT_IN_DOCS", citations: [], rationale: "No evidence." }));
    expect(absent.text).toBe("No evidence.");
    expect(absent.evidenceLabel).toBe("Related evidence — not direct support");
  });
});
