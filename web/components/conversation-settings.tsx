"use client";
import { useI18n } from "@/lib/i18n";


import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ProfileFields } from "@/components/profile-fields";
import type { DocumentFacets, ReviewSessionProfile } from "@/lib/types";
import { getDocumentFacets, getPublishedDocumentFacets } from "@/lib/api";
import { TokenSelect } from "@/components/token-select";
import { resolvedRetrievalProfile } from "@/lib/types";

export type ConversationSettingsTab = "filters" | "retrieval" | "evidence" | "limits";
interface Props {
  tab: ConversationSettingsTab;
  profile: ReviewSessionProfile;
  editable: boolean;
  onChange: (update: Partial<ReviewSessionProfile>) => void;
  onTabChange: (tab: ConversationSettingsTab) => void;
  onClose: () => void;
  onValidityChange?: (valid: boolean) => void;
}

/** Keep conversation-level RAG controls next to the input and out of global Settings. */
export function ConversationSettings(props: Props) {
  const { t } = useI18n();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { panel.current?.focus(); }, [props.tab]);
  const tabs: Array<[ConversationSettingsTab,string]> = [["filters","Filters"], ...(props.editable ? [["retrieval","Retrieval"], ["evidence","Evidence"], ["limits","Run limits"]] as Array<[ConversationSettingsTab,string]> : [])];
  const tab = tabs.some(([id]) => id === props.tab) ? props.tab : "filters";
  const budget = props.profile.prompt_policy.workflow_budget;
  function patch(update: Partial<ReviewSessionProfile>) { props.onChange(update); }
  function patchPolicy(update: Partial<ReviewSessionProfile["prompt_policy"]>) { patch({ prompt_policy: { ...props.profile.prompt_policy, ...update } }); }
  function patchBudget(update: Partial<typeof budget>) { patchPolicy({ workflow_budget: { ...budget, ...update } }); }
  return <div className="conversation-settings" role="region" aria-label={t("Conversation settings")} tabIndex={-1} ref={panel} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); props.onClose(); } }}>
    <div className="conversation-settings-heading"><nav aria-label={t("Conversation settings sections")}>{tabs.map(([id,label]) => <button className="chip" key={id} type="button" aria-pressed={tab === id} onClick={() => props.onTabChange(id)}>{t(label)}</button>)}</nav><button className="icon-button" type="button" aria-label={t("Close conversation settings")} onClick={props.onClose}><X size={18} /></button></div>
    {tab === "filters" && <ConversationFilters profile={props.profile} editable={props.editable} onChange={props.onChange} onValidityChange={props.onValidityChange} />}
    {tab === "retrieval" && props.editable && <div data-help="review.retrieval">
      <p className="helper">{t("Changes apply to this conversation. Running requests keep the settings they started with.")}</p>
      {props.profile.retrieval_preset !== "custom" ? <button className="button" type="button" onClick={() => patch({ retrieval_preset: "custom", custom_retrieval: resolvedRetrievalProfile(props.profile) })}>{t("Customize retrieval")}</button> : <ProfileFields conversation profile={resolvedRetrievalProfile(props.profile)} onChange={(custom_retrieval) => patch({ retrieval_preset: "custom", custom_retrieval })} helpPrefix="review.retrieval" />}
    </div>}
    {tab === "evidence" && props.editable && <div className="profile-grid" data-help="review.evidence-policy"><label>{t("Conversation history turns")}<input type="number" min={0} max={6} value={props.profile.prompt_policy.history_turns} onChange={(event) => patchPolicy({ history_turns: Number(event.target.value) })} /></label><label>{t("Maximum evidence characters")}<input type="number" min={1000} max={100000} value={props.profile.prompt_policy.max_context_chars} onChange={(event) => patchPolicy({ max_context_chars: Number(event.target.value) })} /></label><label>{t("Evidence overfetch")}<input type="number" min={1} max={10} value={props.profile.prompt_policy.evidence_overfetch} onChange={(event) => patchPolicy({ evidence_overfetch: Number(event.target.value) })} /></label><label>{t("Maximum hits per document")}<input type="number" min={1} max={100} value={props.profile.prompt_policy.max_hits_per_document} onChange={(event) => patchPolicy({ max_hits_per_document: Number(event.target.value) })} /></label></div>}
    {tab === "limits" && props.editable && <div className="profile-grid" data-help="review.run-limits">
      <label>{t("Maximum iterations")}<input type="number" min={0} max={20} value={budget.max_iterations} onChange={(event) => patchBudget({ max_iterations: Number(event.target.value) })} /></label>
      <label>{t("Maximum input tokens")}<input type="number" min={0} max={100000} value={budget.max_input_tokens} onChange={(event) => patchBudget({ max_input_tokens: Number(event.target.value) })} /></label>
      <label>{t("Maximum output tokens")}<input type="number" min={0} max={4000} value={budget.max_output_tokens} onChange={(event) => patchBudget({ max_output_tokens: Number(event.target.value) })} /></label>
      <label>{t("Maximum wall clock seconds")}<input type="number" min={1} max={600} value={budget.max_wall_clock_s} onChange={(event) => patchBudget({ max_wall_clock_s: Number(event.target.value) })} /></label>
      <p className="helper">{t("These limits cover the entire run across all model calls. Zero blocks a resource for failure-path experiments; the wall clock must be at least one second.")}</p>
    </div>}
  </div>;
}

/** Load choices from the complete visible corpus whenever its registry or permissions change. */
function ConversationFilters({ profile, editable, onChange, onValidityChange }: Pick<Props, "profile" | "editable" | "onChange" | "onValidityChange">) {
  const { t } = useI18n();
  const [result, setResult] = useState<{ registry: string | undefined; editable: boolean; facets: DocumentFacets } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [validity, setValidity] = useState({ companies: true, languages: true, years: true, forms: true, sections: true });
  const validityCallback = useRef(onValidityChange);
  validityCallback.current = onValidityChange;
  const inputsValid = Object.values(validity).every(Boolean);
  const updateValidity = useCallback((field: keyof typeof validity, valid: boolean) => {
    setValidity((previous) => previous[field] === valid ? previous : { ...previous, [field]: valid });
  }, []);
  useEffect(() => { onValidityChange?.(inputsValid); }, [inputsValid, onValidityChange]);
  // Closing the panel or changing tabs explicitly discards local drafts, as the notice explains.
  useEffect(() => () => { validityCallback.current?.(true); }, []);
  const registry = profile.corpus_scope === "auto" ? undefined : profile.corpus_scope;
  const facets = result && result.registry === registry && result.editable === editable ? result.facets : null;

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setResult(null);
    setError(null);
    void (editable ? getDocumentFacets : getPublishedDocumentFacets)(registry, controller.signal).then((response) => {
      if (!isFilterFacets(response)) throw new Error("Invalid document filter response");
      if (current) setResult({ registry, editable, facets: response });
    }).catch((reason: unknown) => {
      if (current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
    });
    return () => { current = false; controller.abort(); };
  }, [registry, editable, refresh]);

  const companyOptions = facets?.issuers.map((facet) => ({ value: facet.value, label: facet.label ?? facet.value })) ?? [];
  const languageOptions = facets?.languages.filter((facet) => facet.value === "en" || facet.value === "ko").map((facet) => ({ value: facet.value, label: facet.value === "en" ? t("English (en)") : t("Korean (ko)") })) ?? [];
  const yearOptions = facets?.years.map((facet) => ({ value: facet.value, label: facet.value })) ?? [];
  const formOptions = facets?.forms.map((facet) => ({ value: facet.value, label: facet.label ?? facet.value })) ?? [];

  /** Keep incompatible selections visible until the user deliberately removes them. */
  function unavailable(values: string[], options: Array<{ value: string }>) {
    return facets ? values.filter((value) => !options.some((option) => option.value === value)) : [];
  }

  const invalidCompanies = unavailable(profile.issuers, companyOptions);
  const invalidLanguages = unavailable(profile.languages, languageOptions);
  const invalidYears = unavailable(profile.fiscal_years.map(String), yearOptions);
  const invalidForms = unavailable(profile.forms, formOptions);
  const hasUnavailable = invalidCompanies.length + invalidLanguages.length + invalidYears.length + invalidForms.length > 0;
  return <div>
    <p className="conversation-filter-scope">{t("Choices from {scope}. Empty selections search all documents in this scope.", { scope: registry ? registry.toUpperCase() : t("SEC + DART") })}</p>
    {!inputsValid && <p className="token-error" role="status">{t("Resolve the highlighted filters before sending. Switching tabs or closing this panel discards unfinished entries; selected filters stay unchanged.")}</p>}
    {!facets && !error && <div className="conversation-facet-status" role="status"><p className="helper">{t("Loading available filters…")}</p></div>}
    {error && <div className="conversation-facet-status" role="alert"><div><p>{t("Could not load available filters.")}</p><p className="helper">{error}</p></div><button className="button" type="button" onClick={() => setRefresh((value) => value + 1)}>{t("Retry")}</button></div>}
    {hasUnavailable && <div className="conversation-facet-status"><p className="helper">{t("Selections outside this scope are kept until you remove them.")}</p><button className="button" type="button" onClick={() => onChange({
      issuers: profile.issuers.filter((value) => !invalidCompanies.includes(value)),
      languages: profile.languages.filter((value) => !invalidLanguages.includes(value)),
      fiscal_years: profile.fiscal_years.filter((value) => !invalidYears.includes(String(value))),
      forms: profile.forms.filter((value) => !invalidForms.includes(value)),
    })}>{t("Remove unavailable selections")}</button></div>}
    <div className="profile-grid conversation-filters">
      <TokenSelect label={t("Companies")} values={profile.issuers} options={companyOptions} invalidValues={invalidCompanies} disabled={!facets} placeholder={t("Search company name or code")} onValidityChange={(valid) => updateValidity("companies", valid)} onChange={(issuers) => onChange({ issuers })} />
      <TokenSelect label={t("Languages")} values={profile.languages} options={languageOptions} quickOptions={languageOptions} invalidValues={invalidLanguages} disabled={!facets} placeholder={t("Choose document languages")} onValidityChange={(valid) => updateValidity("languages", valid)} onChange={(languages) => onChange({ languages: languages.filter((value): value is "en" | "ko" => value === "en" || value === "ko") })} />
      <TokenSelect label={t("Fiscal years")} values={profile.fiscal_years.map(String)} options={yearOptions} quickOptions={yearOptions.slice(0, 5)} invalidValues={invalidYears} disabled={!facets} placeholder={t("Choose available fiscal years")} onValidityChange={(valid) => updateValidity("years", valid)} onChange={(years) => onChange({ fiscal_years: years.map(Number) })} />
      <TokenSelect label={t("Forms")} values={profile.forms} options={formOptions} quickOptions={formOptions} invalidValues={invalidForms} disabled={!facets} placeholder={t("Choose report types")} onValidityChange={(valid) => updateValidity("forms", valid)} onChange={(forms) => onChange({ forms })} />
      <TokenSelect label={t("Sections")} values={profile.sections.map((value) => value ?? "unsectioned")} options={[]} parseCustom={(value) => [value]} placeholder={t("7 7A unsectioned")} hint={t("Add section identifiers with Enter. Use unsectioned for documents without a section.")} onValidityChange={(valid) => updateValidity("sections", valid)} onChange={(sections) => onChange({ sections: sections.map((value) => value === "unsectioned" ? null : value) })} />
    </div>
  </div>;
}

/** Validate the facet fields this panel uses before accepting network data. */
function isFilterFacets(value: unknown): value is DocumentFacets {
  if (!value || typeof value !== "object") return false;
  return ["issuers", "languages", "years", "forms"].every((key) => {
    const entries = (value as Record<string, unknown>)[key];
    return Array.isArray(entries) && entries.every((entry) => entry && typeof entry === "object" && typeof entry.value === "string" && typeof entry.count === "number" && (entry.label == null || typeof entry.label === "string"));
  });
}
