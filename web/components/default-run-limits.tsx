"use client";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { getOpenAILimits, resetOpenAILimits, saveOpenAILimits } from "@/lib/api";
import type { OpenAICallLimits, Readiness } from "@/lib/types";
import { loadDefaultProfile, saveDefaultProfile } from "@/lib/storage";
import { conversationSettingsError } from "@/lib/saved-presets";
import { DEFAULT_SESSION_PROFILE } from "@/lib/types";
import { notificationErrorMessage } from "@/lib/notification-registry";
import { LOCAL_CPU_STARTING_BUDGET, LOCAL_CPU_EVIDENCE_CHARS } from "@/lib/local-limit-suggestion";
import { RunLimitFields } from "./run-limit-fields";

/** Bold the .env keys and file paths inside translated guidance without changing the copy. */
export function emphasizeEnvKeys(text: string) {
  return text.split(/(DOCREVIEW_OPENAI_MAX_[A-Z_]+|data\/local-settings\/openai-limits\.json|\.env|rag-dev down\/up)/).map((part, index) => index % 2 === 1 ? <strong key={index}>{part}</strong> : part);
}

/** Accept only a complete caps payload; a stub or partial response must not render. */
function validCaps(value: unknown): value is OpenAICallLimits {
  const caps = value as Partial<OpenAICallLimits> | null;
  return !!caps && [caps.max_input_tokens, caps.max_output_tokens, caps.ceiling_max_input_tokens, caps.ceiling_max_output_tokens].every((item) => typeof item === "number") && typeof caps.max_cost_usd === "string" && typeof caps.ceiling_max_cost_usd === "string";
}

/** Edit only new-conversation evidence and limits, preserving other saved defaults. */
export function DefaultRunLimits({ summary = false, onOpen, speed, readiness = null, capsEditable = false }: { summary?: boolean; onOpen?: () => void; speed?: number | null; readiness?: Readiness | null; capsEditable?: boolean }) {
  const { t, locale } = useI18n();
  const [caps, setCaps] = useState<OpenAICallLimits | null>(validCaps(readiness?.openai_call_limits) ? readiness!.openai_call_limits! : null);
  const [capsForm, setCapsForm] = useState<{ max_input_tokens: number; max_output_tokens: number; max_cost_usd: string } | null>(null);
  const [capsNotice, setCapsNotice] = useState<string | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [capsBusy, setCapsBusy] = useState(false);
  useEffect(() => { if (validCaps(readiness?.openai_call_limits)) setCaps(readiness!.openai_call_limits!); }, [readiness?.openai_call_limits]);
  useEffect(() => {
    if (summary || !capsEditable) return;
    const controller = new AbortController();
    getOpenAILimits(controller.signal).then((live) => { if (validCaps(live)) setCaps(live); }).catch(() => undefined);
    return () => controller.abort();
  }, [summary, capsEditable]);
  useEffect(() => { if (caps && !capsForm) setCapsForm({ max_input_tokens: caps.max_input_tokens, max_output_tokens: caps.max_output_tokens, max_cost_usd: caps.max_cost_usd }); }, [caps, capsForm]);
  async function applyCaps(action: () => Promise<OpenAICallLimits>, notice: string) {
    setCapsBusy(true); setCapsNotice(null); setCapsError(null);
    try { const saved = await action(); if (!validCaps(saved)) throw new Error("OpenAI per-call caps response is incomplete."); setCaps(saved); setCapsForm({ max_input_tokens: saved.max_input_tokens, max_output_tokens: saved.max_output_tokens, max_cost_usd: saved.max_cost_usd }); setCapsNotice(notice); }
    catch (reason) { setCapsError(reason instanceof Error ? notificationErrorMessage(reason) : "OpenAI per-call caps could not be saved."); }
    finally { setCapsBusy(false); }
  }
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
      <p className="helper">{t("Whole-run budget for one question, applied to every answer engine (OpenAI or local). Server per-call caps are separate and shown below. Saved for new conversations only; existing conversations and running requests keep their own values.")}</p>
      <RunLimitFields evidenceChars={policy.max_context_chars} onEvidenceChange={max_context_chars => { setNotice(null); setPolicy({ ...policy, max_context_chars }); }} onApplyCpuPreset={() => { setNotice(null); setPolicy({ ...policy, workflow_budget: { ...LOCAL_CPU_STARTING_BUDGET }, max_context_chars: LOCAL_CPU_EVIDENCE_CHARS }); }} budget={policy.workflow_budget} speed={speed} onChange={workflow_budget => { setNotice(null); setPolicy({ ...policy, workflow_budget }); }} />
      <div className="run-limit-actions">
      <button type="button" className="button primary" disabled={!!validation} onClick={() => {
        try { const defaults = loadDefaultProfile(); saveDefaultProfile({ ...defaults, prompt_policy: { ...defaults.prompt_policy, max_context_chars: policy.max_context_chars, workflow_budget: policy.workflow_budget } }); setError(null); setNotice("Default limits saved for new conversations."); window.dispatchEvent(new Event("docreview:default-limits-changed")); }
        catch { setError("Default limits could not be saved."); }
      }}>{t("Save default limits")}</button>
      <button type="button" className="button" onClick={() => { setNotice(null); setError(null); setPolicy({ ...policy, max_context_chars: DEFAULT_SESSION_PROFILE.prompt_policy.max_context_chars, workflow_budget: structuredClone(DEFAULT_SESSION_PROFILE.prompt_policy.workflow_budget) }); }}>{t("Restore limit defaults")}</button>
      {(error || validation) ? <p role="alert">{t(validation ?? error!)}</p> : notice && <p role="status">{t(notice)}</p>}
      </div>
      {caps && <div className="openai-call-caps"><h3>{t("OpenAI per-call caps")}</h3>
        <dl className="request-facts"><div><dt>{t("Ceiling input tokens")}</dt><dd>{caps.ceiling_max_input_tokens.toLocaleString(locale)}</dd></div><div><dt>{t("Ceiling output tokens")}</dt><dd>{caps.ceiling_max_output_tokens.toLocaleString(locale)}</dd></div><div><dt>{t("Ceiling cost cap")}</dt><dd>${caps.ceiling_max_cost_usd}</dd></div><div><dt>{t("Cap source")}</dt><dd>{t(caps.source === "saved" ? "Saved working value" : caps.source === "invalid" ? "Invalid file, ceiling applies" : "Ceiling")}</dd></div></dl>
        {capsEditable && capsForm && <>
          <div className="run-limit-grid">
            <label><span>{t("Per-call input tokens")}</span><span className="run-limit-input"><input type="number" aria-label={t("Per-call input tokens")} min={1} max={caps.ceiling_max_input_tokens} step={1} value={capsForm.max_input_tokens} onChange={event => { setCapsNotice(null); setCapsForm({ ...capsForm, max_input_tokens: Number(event.target.value) }); }} /><span aria-hidden="true">{t("tokens")}</span></span><small>1–{caps.ceiling_max_input_tokens.toLocaleString(locale)} {t("tokens")}</small></label>
            <label><span>{t("Per-call output tokens")}</span><span className="run-limit-input"><input type="number" aria-label={t("Per-call output tokens")} min={1} max={caps.ceiling_max_output_tokens} step={1} value={capsForm.max_output_tokens} onChange={event => { setCapsNotice(null); setCapsForm({ ...capsForm, max_output_tokens: Number(event.target.value) }); }} /><span aria-hidden="true">{t("tokens")}</span></span><small>1–{caps.ceiling_max_output_tokens.toLocaleString(locale)} {t("tokens")}</small></label>
            <label><span>{t("Per-call cost cap")}</span><span className="run-limit-input"><input type="number" aria-label={t("Per-call cost cap")} min={0.001} max={Number(caps.ceiling_max_cost_usd)} step="any" value={capsForm.max_cost_usd} onChange={event => { setCapsNotice(null); setCapsForm({ ...capsForm, max_cost_usd: event.target.value }); }} /><span aria-hidden="true">USD</span></span><small>≤ ${caps.ceiling_max_cost_usd}</small></label>
          </div>
          <div className="run-limit-actions">
            <button type="button" className="button primary" disabled={capsBusy} onClick={() => void applyCaps(() => saveOpenAILimits(capsForm), "Per-call caps saved on the server.")}>{t("Save per-call caps")}</button>
            <button type="button" className="button" disabled={capsBusy} onClick={() => void applyCaps(resetOpenAILimits, "Per-call caps restored to the ceiling.")}>{t("Restore ceiling")}</button>
            {capsError ? <p role="alert">{capsError}</p> : capsNotice && <p role="status">{t(capsNotice)}</p>}
          </div>
        </>}
        <p className="helper">{emphasizeEnvKeys(t(capsEditable ? "Working values for DEV only, saved on the server at data/local-settings/openai-limits.json. The web cannot exceed the ceiling: to raise it, edit DOCREVIEW_OPENAI_MAX_INPUT_TOKENS, DOCREVIEW_OPENAI_MAX_OUTPUT_TOKENS or DOCREVIEW_OPENAI_MAX_COST_USD in .env and restart with rag-dev down/up. Public PROD always uses the ceiling." : "These caps apply to each OpenAI call and come from .env on the server. They can be lowered only in a DEV build; raising them means editing .env and restarting the stack."))}</p>
      </div>}
    </>}
  </section>;
}
