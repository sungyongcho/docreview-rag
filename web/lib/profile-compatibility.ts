import type { Capabilities, ReviewSessionProfile } from "./types";
import { DEFAULT_SESSION_PROFILE } from "./types";

/** Preserve restored experiments while refusing to send a profile the server cannot accept. */
export function profileCompatibilityIssue(profile: ReviewSessionProfile, capabilities: Capabilities | null): string | null {
  if (!capabilities || !["dev", "prod"].includes(capabilities.environment)) return "Checking server permissions before sending…";
  const unsupported: string[] = [];
  const policy = profile.prompt_policy;
  const defaults = DEFAULT_SESSION_PROFILE.prompt_policy;
  if (profile.engine === "local" && (capabilities.environment !== "dev" || !capabilities.can_configure_local_llm)) unsupported.push("a local answer model");
  if (!capabilities.can_change_custom_retrieval && (profile.retrieval_preset === "custom" || profile.custom_retrieval !== null)) unsupported.push("custom retrieval");
  if (!capabilities.can_query_snapshot && profile.snapshot_id !== null) unsupported.push("a private snapshot");
  if (!capabilities.can_edit_prompt_policy && (policy.additional_instructions !== defaults.additional_instructions || policy.history_turns !== defaults.history_turns || policy.max_context_chars !== defaults.max_context_chars || policy.evidence_overfetch !== defaults.evidence_overfetch || policy.max_hits_per_document !== defaults.max_hits_per_document)) unsupported.push("custom prompt or evidence settings");
  if (!capabilities.can_edit_run_limits && Object.entries(defaults.workflow_budget).some(([key, value]) => policy.workflow_budget[key as keyof typeof policy.workflow_budget] !== value)) unsupported.push("custom run limits");
  return unsupported.length ? `This conversation uses ${unsupported.join(", ")}, which this environment does not allow. Open it in Dev or start a new review. Its saved settings have not been changed.` : null;
}
