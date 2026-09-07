"use client";

import "./review-controls.css";
import { RunLimitGuidance } from "./run-limit-guidance";
import { PresetDetails } from "./preset-details";
import { useI18n } from "@/lib/i18n";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile, type ReviewSessionDraft, type RetrievalPreset } from "@/lib/types";

const PRESETS: Array<[RetrievalPreset, string]> = [["balanced", "Balanced"], ["korean", "Korean"], ["accuracy", "Accuracy"], ["custom", "Custom"]];

/** Compare effective values, so preset descriptions cannot drift from request settings. */
export function presetChanges(profile: ReviewSessionDraft, preset: RetrievalPreset) {
  const baseline = resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE);
  const effective = resolvedRetrievalProfile({ ...profile, retrieval_preset: preset });
  return Object.entries(effective).filter(([key, value]) => value !== baseline[key as keyof typeof baseline]);
}

/** One description shared by the visible control and the full comparison. */
export function presetDescription(profile: ReviewSessionDraft, preset: RetrievalPreset) {
  const effective = resolvedRetrievalProfile({ ...profile, retrieval_preset: preset });
  const changes = presetChanges(profile, preset);
  return {
    purpose: preset === "custom" ? "Uses your explicit retrieval settings." : preset === "accuracy" ? "Ranks a wider candidate pool by relevance." : preset === "korean" ? "Uses language-aware retrieval across the selected filing corpus." : "Uses the default retrieval balance.",
    settings: changes.length ? changes.map(([key, value]) => `${key}: ${String(value)}`).join(" · ") : `strategy: ${effective.strategy} · k: ${effective.k} · candidate_k: ${effective.candidate_k}`,
  };
}

const POLICY_LABELS: Record<string, string> = { additional_instructions: "Additional instructions", history_turns: "Conversation history turns", max_context_chars: "Maximum evidence characters", evidence_overfetch: "Evidence overfetch", max_hits_per_document: "Maximum hits per document", max_iterations: "Maximum iterations", max_input_tokens: "Maximum input tokens", max_output_tokens: "Maximum output tokens", max_wall_clock_s: "Maximum wall clock seconds" };

/** Show the next request independently of any historical run in the surrounding panel. */
export function RequestPreviewContent({ profile, query }: { profile: ReviewSessionDraft; query: string }) {
  const { t } = useI18n();
  const effective = resolvedRetrievalProfile(profile);
  const filters = { corpus_scope: profile.corpus_scope, issuers: profile.issuers, fiscal_years: profile.fiscal_years, forms: profile.forms, sections: profile.sections, languages: profile.languages, snapshot_id: profile.snapshot_id };
  return <div className="settings-preview-content"><h3>{t("Next request preview")}</h3><RunLimitGuidance /><p className="helper">{t("These are the next question’s settings, not the selected run’s recorded settings.")}</p><p>{query || t("No question entered yet.")}</p>
      <h3>{t("Retrieval presets")}</h3>
      <div className="preset-list">{PRESETS.map(([id, label]) => {
        const description = presetDescription(profile, id);
        return <PresetDetails key={id} label={t(label)} selected={profile.retrieval_preset === id}>
          <p>{t(description.purpose)}</p>
          <code>{description.settings}</code>
        </PresetDetails>;
      })}</div>
      <dl className="request-facts">
        <div><dt>{t("Retrieval")}</dt><dd>{effective.strategy} · k {effective.k} · {t("Candidates")} {effective.candidate_k}</dd></div>
        <div><dt>{t("Reranker")}</dt><dd>{effective.reranker ?? t("None")}</dd></div>
        <div><dt>{t("Language routing")}</dt><dd>{t(effective.route_by_language ? "Enabled" : "Disabled")}</dd></div>
        <div><dt>{t("Answer engine")}</dt><dd>{profile.engine}{profile.engine === "local" && profile.local_model ? ` · ${profile.local_model}` : ""}</dd></div>
      </dl>
      <details><summary>{t("Filters")}</summary><pre>{JSON.stringify(filters, null, 2)}</pre></details>
      <h3>{t("Evidence and run limits")}</h3>
      <dl className="request-facts">{Object.entries(profile.prompt_policy).filter(([key]) => key !== "workflow_budget").map(([key, value]) => <div key={key}><dt>{t(POLICY_LABELS[key] ?? key)}</dt><dd>{String(value) || t("None")}</dd></div>)}{Object.entries(profile.prompt_policy.workflow_budget).map(([key, value]) => <div key={key}><dt>{t(POLICY_LABELS[key] ?? key)}</dt><dd>{String(value)}</dd></div>)}</dl>
      <details><summary>{t("Prompt composition")}</summary><p className="helper">{t("Server policy + conversation history + question + retrieved evidence. The evidence is selected after execution begins.")}</p><pre>{JSON.stringify({ question: query, prompt_policy: profile.prompt_policy }, null, 2)}</pre></details>
      <details><summary>{t("Request payload")}</summary><pre>{JSON.stringify({ query, session_profile: profile }, null, 2)}</pre></details>
      <p className="helper">{t("Preview of this next request. Server-applied settings appear with the completed result.")}</p>
</div>;
}
