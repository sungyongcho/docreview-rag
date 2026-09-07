"use client";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { loadDefaultProfile, saveDefaultProfile } from "@/lib/storage";
import { conversationSettingsError } from "@/lib/saved-presets";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
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
  return <section className="surface default-run-limits"><h3>{t("New-conversation limits and evidence")}</h3>
    {summary ? <><p>{t("Run time: {seconds} seconds · output ceiling: {tokens} tokens · evidence: {characters} characters", { seconds: policy.workflow_budget.max_wall_clock_s, tokens: policy.workflow_budget.max_output_tokens, characters: policy.max_context_chars })}</p>{onOpen && <button type="button" className="button" onClick={onOpen}>{t("Edit default limits")}</button>}</> : <>
      <p className="helper">{t("Save defaults for new conversations only. Existing conversations and running requests keep their own values.")}</p>
      <RunLimitFields budget={policy.workflow_budget} speed={speed} onChange={workflow_budget => setPolicy({ ...policy, workflow_budget })} />
      <label>{t("Maximum evidence characters")}<input type="number" min={1000} max={100000} value={policy.max_context_chars} onChange={event => setPolicy({ ...policy, max_context_chars: Number(event.target.value) })} /></label>
      {(error || validation) && <p role="alert">{t(validation ?? error!)}</p>}
      <button type="button" className="button primary" disabled={!!validation} onClick={() => {
        try { const defaults = loadDefaultProfile(); saveDefaultProfile({ ...defaults, prompt_policy: { ...defaults.prompt_policy, max_context_chars: policy.max_context_chars, workflow_budget: policy.workflow_budget } }); setError(null); setNotice("Default limits saved for new conversations."); window.dispatchEvent(new Event("docreview:default-limits-changed")); }
        catch { setError("Default limits could not be saved."); }
      }}>{t("Save default limits")}</button>
      <button type="button" className="button" onClick={() => setPolicy({ ...policy, max_context_chars: DEFAULT_SESSION_PROFILE.prompt_policy.max_context_chars, workflow_budget: structuredClone(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget) })}>{t("Restore limit defaults")}</button>
      {notice && <p role="status">{t(notice)}</p>}
    </>}
  </section>;
}
