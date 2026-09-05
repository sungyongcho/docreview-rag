"use client";

import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import { localModelIssue, selectedLocalModel } from "@/lib/local-models";
import type { Readiness, ReviewSessionProfile } from "@/lib/types";

/** Keep model selection beside the engine while exposing unavailable server states. */
export function LocalEngineSettings({ profile, readiness, onChange }: {
  profile: ReviewSessionProfile;
  readiness: Readiness | null;
  onChange: (update: Partial<ReviewSessionProfile>) => void;
}) {
  if (!LOCAL_ENGINE_VISIBLE) return null;
  const local = readiness?.review_engines?.local;
  const available = local?.enabled === true;
  const models = local?.models?.filter((model) => model.selectable) ?? [];
  const selected = selectedLocalModel(profile, local);
  const missing = selected && !models.some((model) => model.name === selected);
  const issue = localModelIssue(profile, readiness);
  const label = !local ? "Local LLM (Checking…)" : !available ? "Local LLM (Unavailable)" : profile.engine === "local" ? "Local LLM (Selected)" : "Local LLM";
  return <>
    <label>Answer engine<select value={profile.engine} onChange={(event) => onChange({ engine: event.target.value as ReviewSessionProfile["engine"], local_model: selected })}>
      <option value="openai">OpenAI API</option>
      <option value="local" disabled={!available}>{label}</option>
    </select></label>
    {profile.engine === "local" && <>
      <label>Local model<select value={selected ?? ""} disabled={!available} onChange={(event) => onChange({ local_model: event.target.value || null })}>
        <option value="" disabled>Choose a model</option>
        {missing && <option value={selected} disabled>{selected} (Unavailable)</option>}
        {models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
      </select></label>
      <p className="helper" role="status">{issue ?? `Selected: ${selected}`}</p>
    </>}
  </>;
}
