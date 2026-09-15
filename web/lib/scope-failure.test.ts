import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { translate } from "./i18n";
import { isReviewLimitation, reviewLimitationMessage, scopeFailurePatch, scopeFailureProgress } from "./scope-failure";
import type { ReviewPathDecision } from "./types";
import { finishReviewProgress, initialReviewProgress, phaseStatus } from "@/components/review-progress";

const decision: ReviewPathDecision = {
  intent: "document_review", source: "classifier", matched_rule: "classifier_review", rationale: "Company analysis",
  history_turns: 0, selected_scope: "auto", resolved_scope: null, routing_queries: {}, retrieval_query: "SanDisk growth drivers",
  scope_outcome: "empty", stopping_reason: "unknown_issuer", stopping_stage: "gate", missing_issuers: ["SanDisk"], suggested_scope: null,
};

describe("expected request limitations", () => {
  it.each(["en", "ko"] as const)("localizes missing-company guidance and preserves the company (%s)", (locale) => {
    const message = reviewLimitationMessage(decision, (key, values) => translate(locale, key, values));
    expect(message).toContain("SanDisk");
    expect(message).toContain(locale === "ko" ? "공시가 없어" : "do not cover");
    expect(message).not.toContain("unknown_issuer");
  });

  it.each(["path", "gate"] as const)("stops at the explicit %s stage and leaves all later stages unrun", (stage) => {
    const path = { ...decision, stopping_stage: stage, stopping_reason: stage === "path" ? "unsupported_request" : "unknown_issuer" };
    const error = new ApiError(422, path.stopping_reason, "Policy guidance", path);
    const result = finishReviewProgress(scopeFailureProgress(error, initialReviewProgress()), "failed", 42);
    expect(result.outcome).toBe("limited");
    expect([0, 1, 2, 3, 4].map(index => phaseStatus(result, index))).toEqual(stage === "path" ? Array(5).fill("not-run") : ["limited", "not-run", "not-run", "not-run", "not-run"]);
    expect(scopeFailurePatch(error, false)).toMatchObject({ text: "Policy guidance", evidence: [] });
    expect(scopeFailurePatch(error, true)?.failureFix).toBeUndefined();
  });

  it("retains stage-zero guidance when a stored conversation report completes", () => {
    const path = { ...decision, intent: "service_help", stopping_stage: "path", stopping_reason: "service_guidance" };
    const result = finishReviewProgress(initialReviewProgress(), "completed", 42, { path_decision: path, model_calls: [] }, { report_kind: "conversation" });
    expect(result.outcome).toBe("limited");
    expect(phaseStatus(result, 4)).toBe("not-run");
    expect(result.steps).toBe(0);
  });

  it("does not reclassify historical stops or catalog/provider failures", () => {
    expect(isReviewLimitation({ ...decision, stopping_stage: undefined })).toBe(false);
    for (const reason of ["query_scope_unavailable", "provider_failure", "classifier_timeout"]) {
      expect(isReviewLimitation({ ...decision, stopping_reason: reason })).toBe(false);
    }
  });
});
