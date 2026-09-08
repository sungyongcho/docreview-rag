"use client";
import { useI18n } from "@/lib/i18n";


import { answerEngineStates } from "@/lib/answer-engine-state";
import { AnswerEngineLight } from "@/components/answer-engine-light";
import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import { localModelIssue, selectedLocalModel } from "@/lib/local-models";
import type { Readiness, ReviewSessionDraft } from "@/lib/types";

/** Keep model selection beside the engine while exposing unavailable server states. */
export function LocalEngineSettings({ profile, readiness, onChange }: {
  profile: ReviewSessionDraft;
  readiness: Readiness | null;
  onChange: (update: Partial<ReviewSessionDraft>) => void;
}) {
  const { t, locale } = useI18n();
  if (!LOCAL_ENGINE_VISIBLE) return null;
  const local = readiness?.review_engines?.local;
  const available = local?.enabled === true;
  const models = local?.models?.filter((model) => model.selectable) ?? [];
  const selected = selectedLocalModel(profile, local);
  const engines = answerEngineStates(readiness, selected);
  const selectedEngine = engines.find((engine) => engine.id === profile.engine)!;
  const symbols = { green: "🟢", amber: "🟠", grey: "⚪" };
  const missing = selected && !models.some((model) => model.name === selected);
  const issue = localModelIssue(profile, readiness);
  const label = !local ? "Local LLM (Checking…)" : !available ? "Local LLM (Unavailable)" : profile.engine === "local" ? "Local LLM (Selected)" : "Local LLM";
  return <>
    <label className="composer-engine-field"><span className="composer-engine-label">{t("Answer engine")}</span><select data-answer-engine-select aria-label={t("Answer engine")} title={t(selectedEngine.reason)} value={profile.engine} onChange={(event) => onChange({ engine: event.target.value as ReviewSessionDraft["engine"], local_model: selected })}>
      <option value="openai" title={t(engines[0].reason)}>{symbols[engines[0].light]} {t("OpenAI API")}</option>
      <option value="local" title={t(engines[1].reason)} disabled={engines[1].light === "grey"}>{symbols[engines[1].light]} {t(label)}</option>
    </select><span className="composer-control-description"><AnswerEngineLight engine={selectedEngine} /></span></label>
    {profile.engine === "local" && <>
      <label className="composer-engine-field"><span className="composer-engine-label">{t("Local model")}</span><select value={selected ?? ""} disabled={!available} onChange={(event) => onChange({ local_model: event.target.value || null })}>
        <option value="" disabled>{t("Choose a model")}</option>
        {missing && <option value={selected} disabled>{selected}{" "}{t("(Unavailable)")}</option>}
        {models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
      </select></label>
      <p className="helper" role="status">{issue ? t(issue) : t("Selected: {p0}", { p0: selected ?? "" })}</p>
    </>}
  </>;
}
