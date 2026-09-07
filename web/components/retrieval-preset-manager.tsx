"use client";
import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useSavedPresets } from "@/lib/use-saved-presets";
import { retrievalError, savePreset, type SavedPreset } from "@/lib/saved-presets";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile, type RetrievalPreset, type RetrievalProfile } from "@/lib/types";
import { PresetDetails } from "./preset-details";
import { ProfileFields } from "./profile-fields";
import { presetDescription } from "./request-preview";
import "./review-controls.css";

/** Browse built-ins and edit browser-local copies without changing an active conversation. */
export function RetrievalPresetManager({ profile }: { profile?: RetrievalProfile } = {}) {
  const { t } = useI18n();
  const { presets, error: loadError } = useSavedPresets();
  const [draft, setDraft] = useState<SavedPreset | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const error = draft ? retrievalError(draft.retrieval) : null;
  const builtins: Array<[RetrievalPreset, string]> = [["balanced", "Balanced"], ["korean", "Korean"], ["accuracy", "Accuracy"]];
  return <section className="surface preset-manager">
    <h3>{t("Retrieval presets")}</h3><p className="helper">{t("Saved in this browser. Saving a preset does not change existing conversations; select it to apply its values.")}</p>
    {loadError && <p role="alert">{t(loadError)}</p>}
    {draft ? <form className="form-stack" onSubmit={event => {
      event.preventDefault();
      try { savePreset(draft); setDraft(null); setSaveError(null); setNotice("Preset saved. Choose it in the conversation selector to apply it."); }
      catch (reason) { setSaveError(reason instanceof Error ? reason.message : "Could not save the preset."); }
    }}>
      <button className="button ghost" type="button" onClick={() => { setDraft(null); setSaveError(null); }}>{t("Back to presets")}</button>
      <label>{t("Preset name")}<input required maxLength={80} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
      <ProfileFields conversation profile={draft.retrieval} onChange={retrieval => setDraft({ ...draft, retrieval })} />
      {(error || saveError) && <p role="alert">{t(error ?? saveError!)}</p>}
      <button className="button primary" type="submit" disabled={!!error || !!loadError || !draft.name.trim()}>{t("Save preset")}</button>
    </form> : <>
      {profile && <button type="button" className="button" onClick={() => { setNotice(null); setDraft({ id: crypto.randomUUID(), name: "", retrieval: structuredClone(profile) }); }}>{t("Save current search as a preset")}</button>}
      <div className="preset-list">{builtins.map(([id, label]) => <PresetDetails key={id} label={t(label)}><small>{t("Built-in")}</small><p>{t(presetDescription(DEFAULT_SESSION_PROFILE, id).purpose)}</p><pre>{JSON.stringify(resolvedRetrievalProfile({ ...DEFAULT_SESSION_PROFILE, retrieval_preset: id }), null, 2)}</pre><button className="button" type="button" onClick={() => { setNotice(null); setDraft({ id: crypto.randomUUID(), name: `${t(label)} ${t("copy")}`, retrieval: resolvedRetrievalProfile({ ...DEFAULT_SESSION_PROFILE, retrieval_preset: id }) }); }}>{t("Copy and edit")}</button></PresetDetails>)}</div>
      <h3>{t("Saved presets")}</h3>
      {!presets.length && <p className="helper">{t("Copy a built-in preset to create your first saved preset.")}</p>}
      {presets.map(p => <PresetDetails key={p.id} label={p.name}><p>{p.retrieval.strategy} · k {p.retrieval.k} · {t("Candidates")} {p.retrieval.candidate_k}</p><pre>{JSON.stringify(p.retrieval, null, 2)}</pre><button className="button" type="button" onClick={() => { setNotice(null); setDraft(structuredClone(p)); }}>{t("Edit preset")}</button></PresetDetails>)}
    </>}
    {notice && <p role="status">{t(notice)}</p>}
  </section>;
}
