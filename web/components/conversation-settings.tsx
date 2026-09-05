"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { ProfileFields } from "@/components/profile-fields";
import type { ReviewSessionProfile } from "@/lib/types";
import { resolvedRetrievalProfile } from "@/lib/types";

export type ConversationSettingsTab = "filters" | "retrieval" | "evidence" | "limits";
interface Props {
  tab: ConversationSettingsTab;
  profile: ReviewSessionProfile;
  editable: boolean;
  onChange: (update: Partial<ReviewSessionProfile>) => void;
  onTabChange: (tab: ConversationSettingsTab) => void;
  onClose: () => void;
}

/** Keep conversation-level RAG controls next to the input and out of global Settings. */
export function ConversationSettings(props: Props) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { panel.current?.focus(); }, [props.tab]);
  const tabs: Array<[ConversationSettingsTab,string]> = [["filters","Filters"], ...(props.editable ? [["retrieval","Retrieval"], ["evidence","Evidence"], ["limits","Run limits"]] as Array<[ConversationSettingsTab,string]> : [])];
  const tab = tabs.some(([id]) => id === props.tab) ? props.tab : "filters";
  const budget = props.profile.prompt_policy.workflow_budget;
  function patch(update: Partial<ReviewSessionProfile>) { props.onChange(update); }
  function patchPolicy(update: Partial<ReviewSessionProfile["prompt_policy"]>) { patch({ prompt_policy: { ...props.profile.prompt_policy, ...update } }); }
  function patchBudget(update: Partial<typeof budget>) { patchPolicy({ workflow_budget: { ...budget, ...update } }); }
  return <div className="conversation-settings" role="region" aria-label="Conversation settings" tabIndex={-1} ref={panel} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); props.onClose(); } }}>
    <div className="conversation-settings-heading"><nav aria-label="Conversation settings sections">{tabs.map(([id,label]) => <button className="chip" key={id} type="button" aria-pressed={tab === id} onClick={() => props.onTabChange(id)}>{label}</button>)}</nav><button className="icon-button" type="button" aria-label="Close conversation settings" onClick={props.onClose}><X size={18} /></button></div>
    {tab === "filters" && <div className="profile-grid"><label>Companies<input value={props.profile.issuers.join(" ")} onChange={(event) => patch({ issuers: event.target.value.split(/[\s,]+/).filter(Boolean) })} /></label><label>Languages<input value={props.profile.languages.join(" ")} placeholder="en ko" onChange={(event) => patch({ languages: event.target.value.split(/[\s,]+/).filter((value): value is "en" | "ko" => value === "en" || value === "ko") })} /></label><label>Fiscal years<input value={props.profile.fiscal_years.join(" ")} onChange={(event) => patch({ fiscal_years: event.target.value.split(/[\s,]+/).map(Number).filter(Number.isInteger) })} /></label><label>Forms<input value={props.profile.forms.join(" ")} placeholder="10-K 사업보고서" onChange={(event) => patch({ forms: event.target.value.split(/[\s,]+/).filter(Boolean) })} /></label><label>Sections<input value={props.profile.sections.map((value) => value ?? "unsectioned").join(" ")} placeholder="7 7A unsectioned" onChange={(event) => patch({ sections: event.target.value.split(/[\s,]+/).filter(Boolean).map((value) => value === "unsectioned" ? null : value) })} /></label></div>}
    {tab === "retrieval" && props.editable && <div data-help="review.retrieval">
      <p className="helper">Changes apply to this conversation. Running requests keep the settings they started with.</p>
      {props.profile.retrieval_preset !== "custom" ? <button className="button" type="button" onClick={() => patch({ retrieval_preset: "custom", custom_retrieval: resolvedRetrievalProfile(props.profile) })}>Customize retrieval</button> : <ProfileFields conversation profile={resolvedRetrievalProfile(props.profile)} onChange={(custom_retrieval) => patch({ retrieval_preset: "custom", custom_retrieval })} helpPrefix="review.retrieval" />}
    </div>}
    {tab === "evidence" && props.editable && <div className="profile-grid" data-help="review.evidence-policy"><label>Conversation history turns<input type="number" min={0} max={6} value={props.profile.prompt_policy.history_turns} onChange={(event) => patchPolicy({ history_turns: Number(event.target.value) })} /></label><label>Maximum evidence characters<input type="number" min={1000} max={100000} value={props.profile.prompt_policy.max_context_chars} onChange={(event) => patchPolicy({ max_context_chars: Number(event.target.value) })} /></label><label>Evidence overfetch<input type="number" min={1} max={10} value={props.profile.prompt_policy.evidence_overfetch} onChange={(event) => patchPolicy({ evidence_overfetch: Number(event.target.value) })} /></label><label>Maximum hits per document<input type="number" min={1} max={100} value={props.profile.prompt_policy.max_hits_per_document} onChange={(event) => patchPolicy({ max_hits_per_document: Number(event.target.value) })} /></label></div>}
    {tab === "limits" && props.editable && <div className="profile-grid" data-help="review.run-limits">
      <label>Maximum iterations<input type="number" min={0} max={20} value={budget.max_iterations} onChange={(event) => patchBudget({ max_iterations: Number(event.target.value) })} /></label>
      <label>Maximum input tokens<input type="number" min={0} max={100000} value={budget.max_input_tokens} onChange={(event) => patchBudget({ max_input_tokens: Number(event.target.value) })} /></label>
      <label>Maximum output tokens<input type="number" min={0} max={4000} value={budget.max_output_tokens} onChange={(event) => patchBudget({ max_output_tokens: Number(event.target.value) })} /></label>
      <label>Maximum wall clock seconds<input type="number" min={1} max={600} value={budget.max_wall_clock_s} onChange={(event) => patchBudget({ max_wall_clock_s: Number(event.target.value) })} /></label>
      <p className="helper">These limits cover the entire run across all model calls. Zero blocks a resource for failure-path experiments; the wall clock must be at least one second.</p>
    </div>}
  </div>;
}
