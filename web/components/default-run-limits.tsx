"use client";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { loadDefaultProfile, saveDefaultProfile } from "@/lib/storage";
import { conversationSettingsError } from "@/lib/saved-presets";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { LOCAL_CPU_STARTING_BUDGET, LOCAL_CPU_EVIDENCE_CHARS } from "@/lib/local-limit-suggestion";
import { RunLimitFields } from "./run-limit-fields";

/** Edit only new-conversation evidence and limits, preserving other saved defaults. */
export function DefaultRunLimits({ summary = false, onOpen, speed }: { summary?: boolean; onOpen?: () => void; speed?: number | null }) {
  const { t } = useI18n();
  const [policy, setPolicy] = useState(DEFAULT_SESSION_PROFILE.prompt_policy);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    function refresh() { setPolicy(loadDefaultProfile().prompt_policy); }
    refresh(); window.addEventListener("docreview:default-limits-changed", refresh); window.addEventListener("docreview:storage-restored", refresh);
    return () => { window.removeEventListener("docreview:default-limits-changed", refresh); window.removeEventListener("docreview:storage-restored", refresh); };
  }, []);
  const validation = conversationSettingsError({ ...DEFAULT_SESSION_PROFILE, prompt_policy: policy });
  return <section className={`surface default-run-limits${summary ? " default-run-limits-summary" : ""}`}><h3>{t("New conversation defaults")}</h3>
    {summary ? <><p>{t("Run time: {seconds} seconds · output ceiling: {tokens} tokens · evidence: {characters} characters", { seconds: policy.workflow_budget.max_wall_clock_s, tokens: policy.workflow_budget.max_output_tokens, characters: policy.max_context_chars })}</p>{onOpen && <button type="button" className="button" onClick={onOpen}>{t("Edit default limits")}</button>}</> : <>
      <p className="helper">{t("Save defaults for new conversations only. Existing conversations and running requests keep their own values.")}</p>
      <RunLimitFields evidenceChars={policy.max_context_chars} onEvidenceChange={max_context_chars => { setNotice(null); setPolicy({ ...policy, max_context_chars }); }} onApplyCpuPreset={() => setPolicy({ ...policy, workflow_budget: { ...LOCAL_CPU_STARTING_BUDGET }, max_context_chars: LOCAL_CPU_EVIDENCE_CHARS })} budget={policy.workflow_budget} speed={speed} onChange={workflow_budget => { setNotice(null); setPolicy({ ...policy, workflow_budget }); }} />
      <div className="run-limit-actions">
      <button type="button" className="button primary" disabled={!!validation} onClick={() => {
        try { const defaults = loadDefaultProfile(); saveDefaultProfile({ ...defaults, prompt_policy: { ...defaults.prompt_policy, max_context_chars: policy.max_context_chars, workflow_budget: policy.workflow_budget } }); setError(null); setNotice("Default limits saved for new conversations."); window.dispatchEvent(new Event("docreview:default-limits-changed")); }
        catch { setError("Default limits could not be saved."); }
      }}>{t("Save default limits")}</button>
      <button type="button" className="button" onClick={() => { setNotice(null); setError(null); setPolicy({ ...policy, max_context_chars: DEFAULT_SESSION_PROFILE.prompt_policy.max_context_chars, workflow_budget: structuredClone(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget) }); }}>{t("Restore limit defaults")}</button>
      {(error || validation) ? <p role="alert">{t(validation ?? error!)}</p> : notice && <p role="status">{t(notice)}</p>}
      </div>
    </>}
  </section>;
}
