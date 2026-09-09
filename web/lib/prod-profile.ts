import { DEFAULT_SESSION_PROFILE, type ReviewSessionDraft } from "./types";

/** Public request defaults matching the server's accepted PromptPolicy contract.
 * Per-call spending limits are enforced by the server and displayed from /limits.
 */
export function newProdProfile(policy?: ReviewSessionDraft["prompt_policy"]): ReviewSessionDraft {
  return {
    ...structuredClone(DEFAULT_SESSION_PROFILE),
    engine: "openai",
    local_model: null,
    snapshot_id: null,
    retrieval_preset: "balanced",
    custom_retrieval: null,
    applied_from_evaluation: null,
    prompt_policy: policy ? structuredClone(policy) : {
      additional_instructions: "",
      history_turns: 6,
      max_context_chars: 12000,
      evidence_overfetch: 3,
      max_hits_per_document: 2,
      workflow_budget: { max_iterations: 6, max_input_tokens: 60000, max_output_tokens: 4000, max_wall_clock_s: 120 },
    },
  };
}

/** Project saved experiments onto public policy without mutating their stored source. */
export function applyProdPolicy(saved: ReviewSessionDraft, policy: ReviewSessionDraft["prompt_policy"]): ReviewSessionDraft {
  return {
    ...saved,
    engine: "openai",
    local_model: null,
    prompt_policy: structuredClone(policy),
    snapshot_id: null,
    applied_from_evaluation: null,
    retrieval_preset: saved.retrieval_preset === "custom" ? "balanced" : saved.retrieval_preset,
    custom_retrieval: null,
  };
}
