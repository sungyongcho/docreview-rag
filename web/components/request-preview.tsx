"use client";

import "./review-controls.css";
import "./request-preview.css";
import { PublicRunLimits } from "./public-run-limits";
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

const POLICY_LABELS: Record<string, string> = { history_turns: "Conversation history turns", max_context_chars: "Maximum evidence characters", evidence_overfetch: "Evidence overfetch", max_hits_per_document: "Maximum hits per document", max_iterations: "Maximum iterations", max_input_tokens: "Maximum input tokens", max_output_tokens: "Maximum output tokens", max_wall_clock_s: "Maximum wall clock seconds" };

export type RequestPreviewSection = "filters" | "retrieval" | "evidence" | "limits";

/** Keep alternative preset descriptions in Search, separate from the next-request preview. */
export function RetrievalPresetComparison({ profile, editable }: { profile: ReviewSessionDraft; editable: boolean }) {
  const { t } = useI18n();
  return <details className="request-preview-disclosure"><summary>{t("Compare retrieval presets")}</summary>
    <div className="preset-list">{PRESETS.filter(([id]) => editable || id !== "custom").map(([id, label]) => {
      const description = presetDescription(profile, id);
      return <PresetDetails key={id} label={t(label)} selected={profile.retrieval_preset === id}>
        <p>{t(description.purpose)}</p><code>{description.settings}</code>
      </PresetDetails>;
    })}</div>
  </details>;
}

/** Summarize the next question and its selected inputs without editing or executing them. */
export function RequestPreviewContent({ profile, query, editable = true, onOpenSection }: {
  profile: ReviewSessionDraft; query: string; editable?: boolean; onOpenSection?: (section: RequestPreviewSection) => void;
}) {
  const { t, locale } = useI18n();
  const effective = resolvedRetrievalProfile(profile);
  const display = (value: unknown) => typeof value === "boolean" ? t(value ? "Enabled" : "Disabled") : value == null || value === "" ? t("None") : typeof value === "number" ? value.toLocaleString(locale) : String(value);
  const selectedFilters: Array<[string, string]> = [
    ["Corpus scope", profile.corpus_scope === "auto" ? t("Auto") : profile.corpus_scope.toUpperCase()],
    ...([
      ["Registries", profile.registries],
      ["Companies", profile.issuers],
      ["Fiscal years", profile.fiscal_years],
      ["Forms", profile.forms],
      ["Sections", profile.sections.map(value => value ?? "unsectioned")],
      ["Languages", profile.languages],
    ] as Array<[string, Array<string | number>]>).filter(([, values]) => values.length).map(([label, values]) => [label, values.join(", ")] as [string, string]),
    ...(profile.snapshot_id == null ? [] : [["Snapshot", String(profile.snapshot_id)] as [string, string]]),
  ];
  const facts = (rows: Array<[string, string]>) => <dl className="request-summary-facts">{rows.map(([label, value]) => <div key={label}><dt>{t(label)}</dt><dd>{value}</dd></div>)}</dl>;
  const action = (section: RequestPreviewSection, label: string) => onOpenSection ? <button className="inline-link" type="button" onClick={() => onOpenSection(section)}>{t(label)}</button> : null;
  const policyRows = [
    ...Object.entries(profile.prompt_policy).filter(([key]) => key !== "workflow_budget" && key !== "additional_instructions"),
    ...Object.entries(profile.prompt_policy.workflow_budget),
  ].map(([key, value]) => [POLICY_LABELS[key] ?? key, display(value)] as [string, string]);
  return <div className="settings-preview-content next-request-summary">
    <h3>{t("Next request preview")}</h3>
    <p className="request-preview-intro">{t("These are the next question’s settings, not the selected run’s recorded settings.")}</p>
    <section className="request-summary-panel">
      <div className="request-summary-heading"><h4>{t("Question")}</h4><span>{t("Answer engine")}: {profile.engine === "openai" ? "OpenAI" : profile.engine}{profile.engine === "local" && profile.local_model ? ` · ${profile.local_model}` : ""}</span></div>
      <p className="request-preview-question">{query || t("No question entered yet.")}</p>
    </section>
    <section className="request-summary-panel">
      <div className="request-summary-heading"><h4>{t("Filters")}</h4>{action("filters", "Edit filters")}</div>
      {facts(selectedFilters)}
      {profile.doc_ids.length > 0 && <details className="request-preview-disclosure"><summary>{t("Selected documents")} · {profile.doc_ids.length}</summary><ul className="request-preview-identifiers">{profile.doc_ids.map(id => <li key={id}><code>{id}</code></li>)}</ul></details>}
      <p className="request-preview-note">{t("These are your selected constraints. Automatic company and year resolution happens after sending.")}</p>
    </section>
    <section className="request-summary-panel">
      <div className="request-summary-heading"><h4>{t("Search settings")}</h4>{action("retrieval", "Edit search settings")}</div>
      {facts([
        ["Retrieval preset", t(PRESETS.find(([id]) => id === profile.retrieval_preset)?.[1] ?? profile.retrieval_preset)],
        ["Search strategy", effective.strategy],
        ["Results", display(effective.k)],
        ["Candidates", display(effective.candidate_k)],
        ...(effective.strategy !== "vector" ? [["Keyword ranking", display(effective.lexical_ranker)] as [string, string]] : []),
        ...(effective.strategy === "hybrid" ? [["Rank fusion constant", display(effective.rrf_k)], ["Reranker", display(effective.reranker)]] as Array<[string, string]> : []),
        ["Language routing", display(effective.route_by_language)],
      ])}
    </section>
    <section className="request-summary-panel">
      <div className="request-summary-heading"><h4>{t("Evidence and run limits")}</h4><div className="request-summary-actions">{action("evidence", editable ? "Edit evidence policy" : "View evidence policy")}{action("limits", editable ? "Edit run limits" : "View server limits")}</div></div>
      {editable ? <>{facts(policyRows)}<details className="request-preview-disclosure"><summary>{t("Additional instructions")}</summary><p className="request-preview-question">{profile.prompt_policy.additional_instructions || t("None")}</p></details></> : <PublicRunLimits view="summary" />}
    </section>
    <details className="request-preview-disclosure"><summary>{t("Prompt composition")}</summary><p className="request-preview-note">{t("Server policy + conversation history + question + retrieved evidence. The evidence is selected after execution begins.")}</p></details>
    <details className="request-preview-disclosure"><summary>{t("Request payload")}</summary><p className="request-preview-note">{t("Question and conversation settings only. History is attached when you send.")}</p><pre>{JSON.stringify({ query, session_profile: profile }, null, 2)}</pre></details>
    <p className="request-preview-note">{t("Preview of this next request. Server-applied settings appear with the completed result.")}</p>
  </div>;
}
