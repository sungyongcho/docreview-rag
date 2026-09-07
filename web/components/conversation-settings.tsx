"use client";
import { useI18n } from "@/lib/i18n";


import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { RequestPreviewContent } from "./request-preview";
import { RetrievalPresetSelect } from "./retrieval-preset-select";
import { loadDefaultProfile } from "@/lib/storage";
import { conversationSettingsError } from "@/lib/saved-presets";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { RunLimitFields } from "./run-limit-fields";
import { ProfileFields } from "@/components/profile-fields";
import type { DocumentFacets, ReviewSessionDraft } from "@/lib/types";
import { getDocumentFacets, getPublishedDocumentFacets } from "@/lib/api";
import { TokenSelect } from "@/components/token-select";
import { resolvedRetrievalProfile } from "@/lib/types";
import { useRetainedPanelActive } from "@/components/retained-panel";
import { DevelopmentBadge } from "@/components/development-badge";
import "./conversation-settings.css";

export type ConversationSettingsTab = "filters" | "retrieval" | "evidence" | "limits" | "preview";
interface Props {
  tab: ConversationSettingsTab;
  profile: ReviewSessionDraft;
  editable: boolean;
  query?: string;
  speed?: number | null;
  onManagePresets?: () => void;
  onChange: (update: Partial<ReviewSessionDraft>) => void;
  onTabChange: (tab: ConversationSettingsTab) => void;
  onClose: () => void;
  onValidityChange?: (valid: boolean) => void;
}

/** Keep one conversation editor independent of composer height and global Settings. */
export function ConversationSettings(props: Props) {
  const { t, locale } = useI18n();
  const active = useRetainedPanelActive();
  const [mode, setMode] = useState<"basic" | "advanced" | "preview">(props.tab === "preview" ? "preview" : props.editable && props.tab !== "filters" ? "advanced" : "basic");
  useEffect(() => { setMode(props.tab === "preview" ? "preview" : props.editable && props.tab !== "filters" ? "advanced" : "basic"); }, [props.tab, props.editable]);
  const settingsError = conversationSettingsError(props.profile);
  const [savedDefaults, setSavedDefaults] = useState(DEFAULT_SESSION_PROFILE);
  useEffect(() => {
    function refresh() { setSavedDefaults(loadDefaultProfile()); }
    refresh(); window.addEventListener("docreview:default-limits-changed", refresh);
    return () => window.removeEventListener("docreview:default-limits-changed", refresh);
  }, []);
  const baseline = savedDefaults.prompt_policy;
  const changes = Object.entries(props.profile.prompt_policy).filter(([key, value]) => key !== "workflow_budget" && value !== baseline[key as keyof typeof baseline]).length + Object.entries(props.profile.prompt_policy.workflow_budget).filter(([key, value]) => value !== baseline.workflow_budget[key as keyof typeof baseline.workflow_budget]).length + (props.profile.retrieval_preset === "custom" ? 1 : 0);
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const close = useRef(props.onClose);
  close.current = props.onClose;
  useEffect(() => {
    if (!active || !panel.current) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overlay = panel.current.parentElement;
    const background = [...document.body.children].filter((child) => child !== overlay);
    const inertBefore = background.map((child) => child.hasAttribute("inert"));
    background.forEach((child) => child.setAttribute("inert", ""));
    const overflowBefore = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    function controls() {
      return [...(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex="0"]') ?? [])].filter((element) => {
        if (element.closest("[hidden], [inert]")) return false;
        const collapsed = element.closest("details:not([open])");
        return !collapsed || element === collapsed.querySelector("summary");
      });
    }
    function key(event: KeyboardEvent) {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close.current(); return; }
      if (event.key !== "Tab") return;
      const items = controls();
      const first = items[0];
      const last = items.at(-1);
      const outside = !panel.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || outside)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || outside)) { event.preventDefault(); first?.focus(); }
    }
    function containFocus(event: FocusEvent) {
      if (!panel.current?.contains(event.target as Node)) closeButton.current?.focus();
    }
    document.addEventListener("keydown", key);
    document.addEventListener("focusin", containFocus);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("focusin", containFocus);
      background.forEach((child, index) => { if (!inertBefore[index]) child.removeAttribute("inert"); });
      document.body.style.overflow = overflowBefore;
      const target = previous?.isConnected ? previous : document.querySelector<HTMLElement>('button[data-help="review.rag"]');
      if (!target?.closest("[hidden], [inert]")) target?.focus({ preventScroll: true });
    };
  }, [active]);
  const tabs: Array<[ConversationSettingsTab,string]> = [["filters","Filters"], ...(props.editable ? [["retrieval","Search"], ["evidence","Evidence"], ["limits","Run limits"]] as Array<[ConversationSettingsTab,string]> : [])];
  const tab = tabs.some(([id]) => id === props.tab) ? props.tab : "filters";
  const budget = props.profile.prompt_policy.workflow_budget;
  function patch(update: Partial<ReviewSessionDraft>) { props.onChange(update); }
  function patchPolicy(update: Partial<ReviewSessionDraft["prompt_policy"]>) { patch({ prompt_policy: { ...props.profile.prompt_policy, ...update } }); }
  return createPortal(<div className="conversation-settings-overlay" hidden={!active} onMouseDown={(event) => { if (event.target === event.currentTarget) props.onClose(); }}>
    <div className="conversation-settings-dialog" role="dialog" aria-modal={active ? true : undefined} aria-labelledby={titleId} tabIndex={-1} ref={panel}>
    <header className="conversation-settings-header"><div><h2 id={titleId}>{t("Conversation settings")}</h2><p className="helper">{t("Changes apply to this conversation. Running requests keep the settings they started with.")}</p></div><button ref={closeButton} className="icon-button" type="button" aria-label={t("Close conversation settings")} onClick={props.onClose}><X size={20} /></button></header>
    <nav className="conversation-settings-sections settings-mode" aria-label={t("Settings view")}>{(["basic", ...(props.editable ? ["advanced"] : []), "preview"] as const).map(value => <button key={value} type="button" aria-pressed={mode === value} onClick={() => { if (value === "advanced" && tab === "filters") props.onTabChange("retrieval"); setMode(value as typeof mode); }}>{t(value === "basic" ? "Basic" : value === "advanced" ? "Advanced" : "Preview")}</button>)}</nav>
    {mode === "advanced" && <nav className="conversation-settings-sections" aria-label={t("Conversation settings sections")}>{tabs.map(([id,label]) => <button key={id} type="button" aria-pressed={tab === id} title={id !== "filters" ? locale === "ko" ? "개발 모드 전용" : "DEV only" : undefined} onClick={() => props.onTabChange(id)}>{t(label)}{id !== "filters" && <span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span>}</button>)}</nav>}
    <div className="conversation-settings-body">
    {settingsError && <p className="notice error" role="alert">{t(settingsError)}</p>}
    {mode === "preview" && <RequestPreviewContent profile={props.profile} query={props.query ?? ""} />}
    {mode === "basic" && <section className="settings-basic"><h3>{t("Retrieval preset")}</h3><RetrievalPresetSelect profile={props.profile} editable={props.editable} onChange={props.onChange} onManage={props.onManagePresets} />
      <p className="helper">{t("Advanced settings changed: {count}", { count: changes })}</p>
      <dl className="request-facts"><div><dt>{t("Maximum evidence characters")}</dt><dd>{props.profile.prompt_policy.max_context_chars.toLocaleString(locale)}</dd></div><div><dt>{t("Maximum wall clock seconds")}</dt><dd>{budget.max_wall_clock_s} {t("seconds")}</dd></div><div><dt>{t("Maximum input tokens")}</dt><dd>{budget.max_input_tokens.toLocaleString(locale)}</dd></div><div><dt>{t("Maximum output tokens")}</dt><dd>{budget.max_output_tokens.toLocaleString(locale)}</dd></div></dl>
      <h3>{t("Filters")}</h3>
    </section>}
    {(mode === "basic" || mode === "advanced" && tab === "filters") && <ConversationFilters profile={props.profile} editable={props.editable} onChange={props.onChange} onValidityChange={props.onValidityChange} />}
    {mode === "advanced" && tab === "retrieval" && props.editable && <div data-help="review.retrieval">
      {props.profile.retrieval_preset !== "custom" ? <button className="button" type="button" onClick={() => patch({ retrieval_preset: "custom", custom_retrieval: resolvedRetrievalProfile(props.profile) })}>{t("Customize retrieval")}</button> : <ProfileFields conversation profile={resolvedRetrievalProfile(props.profile)} onChange={(custom_retrieval) => patch({ retrieval_preset: "custom", custom_retrieval })} helpPrefix="review.retrieval" />}
    </div>}
    {mode === "advanced" && tab === "evidence" && props.editable && <div className="profile-grid" data-help="review.evidence-policy">{props.speed && props.profile.prompt_policy.max_context_chars > 1000 && <div className="notice warning limit-recommendation"><p>{t("Reducing evidence can reduce answer coverage. Review the limit before applying it.")}</p><button className="button" type="button" onClick={() => patchPolicy({ max_context_chars: Math.max(1000, Math.floor(props.profile.prompt_policy.max_context_chars / 2)) })}>{t("Reduce evidence: {before} → {after} characters", { before: props.profile.prompt_policy.max_context_chars, after: Math.max(1000, Math.floor(props.profile.prompt_policy.max_context_chars / 2)) })}</button></div>}<label>{t("Conversation history turns")}<input type="number" min={0} max={6} value={props.profile.prompt_policy.history_turns} onChange={(event) => patchPolicy({ history_turns: Number(event.target.value) })} /></label><label>{t("Maximum evidence characters")}<input type="number" min={1000} max={100000} value={props.profile.prompt_policy.max_context_chars} onChange={(event) => patchPolicy({ max_context_chars: Number(event.target.value) })} /></label><label>{t("Evidence overfetch")}<input type="number" min={1} max={10} value={props.profile.prompt_policy.evidence_overfetch} onChange={(event) => patchPolicy({ evidence_overfetch: Number(event.target.value) })} /></label><label>{t("Maximum hits per document")}<input type="number" min={1} max={100} value={props.profile.prompt_policy.max_hits_per_document} onChange={(event) => patchPolicy({ max_hits_per_document: Number(event.target.value) })} /></label></div>}
    {mode === "advanced" && tab === "limits" && props.editable && <RunLimitFields budget={budget} speed={props.speed} onChange={workflow_budget => patchPolicy({ workflow_budget })} />}

    {mode === "advanced" && props.editable && <section className="settings-policy-actions"><label>{t("Additional instructions")}<textarea maxLength={8000} value={props.profile.prompt_policy.additional_instructions} onChange={event => patchPolicy({ additional_instructions: event.target.value })} /></label><p className="helper">{t("Instructions, evidence policy and limits apply together to this conversation. Search presets only change retrieval.")}</p><button className="button" type="button" onClick={() => { const defaults = loadDefaultProfile(); patch({ retrieval_preset: defaults.retrieval_preset, custom_retrieval: structuredClone(defaults.custom_retrieval), prompt_policy: structuredClone(defaults.prompt_policy) }); }}>{t("Restore setting defaults")}</button><p className="helper">{t("Restores search, prompt, evidence and limits. Document filters stay unchanged.")}</p></section>}
    </div>
  </div></div>, document.body);
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
  return <div data-help="review.filters">
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
      <TokenSelect showDropdown label={t("Companies")} values={profile.issuers} options={companyOptions} invalidValues={invalidCompanies} disabled={!facets} placeholder={t("Search company name or code")} onValidityChange={(valid) => updateValidity("companies", valid)} onChange={(issuers) => onChange({ issuers })} />
      <TokenSelect showDropdown label={t("Languages")} values={profile.languages} options={languageOptions} quickOptions={languageOptions} invalidValues={invalidLanguages} disabled={!facets} placeholder={t("Choose document languages")} onValidityChange={(valid) => updateValidity("languages", valid)} onChange={(languages) => onChange({ languages: languages.filter((value): value is "en" | "ko" => value === "en" || value === "ko") })} />
      <TokenSelect showDropdown label={t("Fiscal years")} values={profile.fiscal_years.map(String)} options={yearOptions} quickOptions={yearOptions.slice(0, 5)} invalidValues={invalidYears} disabled={!facets} placeholder={t("Choose available fiscal years")} onValidityChange={(valid) => updateValidity("years", valid)} onChange={(years) => onChange({ fiscal_years: years.map(Number) })} />
      <TokenSelect showDropdown label={t("Forms")} values={profile.forms} options={formOptions} quickOptions={formOptions} invalidValues={invalidForms} disabled={!facets} placeholder={t("Choose report types")} onValidityChange={(valid) => updateValidity("forms", valid)} onChange={(forms) => onChange({ forms })} />
      <TokenSelect showDropdown label={t("Sections")} values={profile.sections.map((value) => value ?? "unsectioned")} options={facets?.sections?.map(value => ({ value: value.value, label: value.label ?? value.value })) ?? []} disabled={!facets} parseCustom={(value) => [value]} placeholder={t("7 7A unsectioned")} hint={t("Add section identifiers with Enter. Use unsectioned for documents without a section.")} onValidityChange={(valid) => updateValidity("sections", valid)} onChange={(sections) => onChange({ sections: sections.map((value) => value === "unsectioned" ? null : value) })} />
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
