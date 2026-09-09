"use client";
import { useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useSavedPresets } from "@/lib/use-saved-presets";
import { parsePresetJSON, presetError, type SavedPreset } from "@/lib/saved-presets";
import { deleteStoredPreset, saveStoredPreset, PREVIEW_PRESET_NOTICE, PENDING_PRESET_NOTICE } from "@/lib/preset-storage";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile, type RetrievalProfile } from "@/lib/types";
import { PresetDetails } from "./preset-details";
import { ProfileFields } from "./profile-fields";
import "./review-controls.css";

/** One editor and list serve DEV files, deployed browser storage and preview. */
export function RetrievalPresetManager({ profile, onApply, canApply = true }: { profile?: RetrievalProfile; onApply?: (profile: RetrievalProfile) => void; canApply?: boolean } = {}) {
  const { t } = useI18n();
  const { presets, builtins, fileErrors, error: loadError, storageKind } = useSavedPresets();
  const [draft, setDraft] = useState<SavedPreset | null>(null);
  const [jsonMode, setJSONMode] = useState(false);
  const [json, setJSON] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const preview = storageKind === "preview";
  const pending = storageKind === "pending";
  const readOnly = preview || pending;
  let parsed = draft, error = draft ? presetError(draft) : null;
  if (draft && jsonMode) {
    try { parsed = parsePresetJSON(json); error = parsed.id !== draft.id || parsed.builtin ? "The editor cannot change a preset ID or built-in status." : null; }
    catch (reason) { error = reason instanceof Error ? reason.message : "Enter valid JSON."; }
  }
  function edit(preset?: SavedPreset, copy = false) {
    const next: SavedPreset = preset ? { ...structuredClone(preset), ...(copy ? { id: crypto.randomUUID(), name: `${t(preset.name)} ${t("copy")}`, builtin: false, updated_at: null } : {}) } : { id: crypto.randomUUID(), name: "", description: "", retrieval: structuredClone(builtins.find(p => p.id === "balanced")?.retrieval ?? resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE)) };
    setDraft(next); setJSON(JSON.stringify(next, null, 2)); setJSONMode(false); setSaveError(null); setNotice(null);
  }
  function failure(reason: unknown) { setSaveError(reason instanceof Error ? reason.message : "Could not save the preset."); setBusy(false); }
  function finish() { setDraft(null); setBusy(false); setSaveError(null); setNotice("Preset saved. Choose it in the conversation selector to apply it."); }
  function save() {
    if (!parsed || error || readOnly || busy) return;
    try { const pending = saveStoredPreset(parsed); if (pending) { setBusy(true); void pending.then(finish).catch(failure); } else finish(); }
    catch (reason) { failure(reason); }
  }
  function remove(id: string) {
    try { const pending = deleteStoredPreset(id); setDeleting(null); if (pending) { setBusy(true); void pending.then(() => setBusy(false)).catch(failure); } }
    catch (reason) { failure(reason); }
  }
  function exportPreset(preset: SavedPreset) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(preset, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `${preset.id}.json`; link.click(); URL.revokeObjectURL(url);
  }
  const writeTitle = preview ? t(PREVIEW_PRESET_NOTICE) : pending ? t(PENDING_PRESET_NOTICE) : undefined;
  const row = (p: SavedPreset) => <PresetDetails key={p.id} label={p.builtin ? t(p.name) : p.name} summary={`${p.retrieval.strategy} · k ${p.retrieval.k} · ${t("Candidates")} ${p.retrieval.candidate_k} · ${p.retrieval.lexical_ranker ?? "—"}`} source={t(p.builtin ? "Built-in" : storageKind === "file" ? "File" : "Browser")}>
    {p.description && <p>{p.description}</p>}<pre>{JSON.stringify(p.builtin ? { id: "", name: p.name, description: p.description ?? "", retrieval: p.retrieval } : p.retrieval, null, 2)}</pre>
    <div className="action-row">
      {!p.builtin && <button className="button" type="button" disabled={!onApply || !canApply || readOnly} title={!canApply ? t("Current server policy does not allow custom retrieval.") : undefined} onClick={() => onApply?.(structuredClone(p.retrieval))}>{t("Select for conversation")}</button>}
      <button className="button" type="button" disabled={readOnly || busy} title={writeTitle} onClick={() => edit(p, true)}>{t(p.builtin ? "Copy and edit" : "Copy preset")}</button>
      {!p.builtin && <><button className="button" type="button" disabled={readOnly || busy} title={writeTitle} onClick={() => edit(p)}>{t("Edit preset")}</button><button className="button ghost" type="button" disabled={readOnly || busy} title={writeTitle} onClick={() => setDeleting(p.id)}>{t("Delete preset")}</button><button className="button ghost" type="button" onClick={() => exportPreset(p)}>{t("Export preset JSON")}</button></>}
    </div>
    {deleting === p.id && <div className="notice" role="alert"><p>{t("Delete this saved preset? Existing conversations keep their values.")}</p><div className="action-row"><button className="button danger" type="button" disabled={busy} onClick={() => remove(p.id)}>{t("Confirm delete")}</button><button className="button ghost" type="button" onClick={() => setDeleting(null)}>{t("Cancel")}</button></div></div>}
  </PresetDetails>;
  return <section className="surface preset-manager">
    <div className="preset-manager-heading"><h3>{t("Retrieval presets")}</h3>{storageKind === "file" && <span className="mode-badge">DEV</span>}</div>
    <p className="helper">{t(storageKind === "file" ? "Saved as JSON files in data/presets/. File changes appear automatically." : "Saved in this browser. Saving a preset does not change existing conversations; select it to apply its values.")}</p>
    {preview && <p className="notice warning" role="note">{t(PREVIEW_PRESET_NOTICE)}</p>}
    {pending && <p className="notice" role="status">{t(PENDING_PRESET_NOTICE)}</p>}
    {loadError && <p className="notice error" role="alert">{t(loadError)}</p>}
    {!!fileErrors.length && <div className="notice error" role="alert"><strong>{t("Some preset files could not be read.")}</strong><ul>{fileErrors.map(item => <li key={item.file}><code>{item.file}</code>: {t(item.error)}</li>)}</ul></div>}
    {draft ? <form className="form-stack" onSubmit={event => { event.preventDefault(); save(); }}>
      <button className="button ghost" type="button" disabled={busy} onClick={() => { setDraft(null); setSaveError(null); }}>{t("Back to presets")}</button>
      <div className="action-row"><button className="button" type="button" aria-pressed={!jsonMode} disabled={!!error && jsonMode} onClick={() => { if (parsed && !error) setDraft(parsed); setJSONMode(false); }}>{t("Form editor")}</button><button className="button" type="button" aria-pressed={jsonMode} onClick={() => { if (!jsonMode) setJSON(JSON.stringify(draft, null, 2)); setJSONMode(true); }}>JSON</button></div>
      {jsonMode ? <><label>{t("Preset JSON")}<textarea className="preset-json-editor" rows={20} value={json} disabled={busy} aria-invalid={!!error} onChange={event => setJSON(event.target.value)} /></label><button className="button ghost" type="button" disabled={!!error} onClick={() => void navigator.clipboard.writeText(JSON.stringify(parsed, null, 2)).then(() => setNotice("JSON copied.")).catch(failure)}>{t("Copy JSON")}</button></> : <><label>{t("Preset name")}<input required maxLength={80} value={draft.name} disabled={busy} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label><label>{t("Preset description")}<textarea maxLength={2000} value={draft.description ?? ""} disabled={busy} onChange={event => setDraft({ ...draft, description: event.target.value })} /></label><fieldset disabled={busy}><ProfileFields conversation profile={draft.retrieval} onChange={retrieval => setDraft({ ...draft, retrieval })} /></fieldset></>}
      {error && <p role="alert">{t(error)}</p>}
      <button className="button primary" type="submit" title={writeTitle} disabled={!!error || !!loadError || readOnly || busy}>{t(busy ? "Saving…" : "Save preset")}</button>
    </form> : <>
      <div className="action-row preset-toolbar"><button type="button" className="button primary" disabled={readOnly || busy} title={writeTitle} onClick={() => edit({ id: crypto.randomUUID(), name: "", description: "", retrieval: structuredClone(profile ?? resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE)) })}>{t("Save current search as a preset")}</button><button type="button" className="button" disabled={readOnly || busy} title={writeTitle} onClick={() => edit()}>{t("Register new preset")}</button><button type="button" className="button ghost" disabled={readOnly || busy} title={writeTitle} onClick={() => input.current?.click()}>{t("Import preset JSON")}</button></div>
      <input ref={input} type="file" accept="application/json,.json" hidden aria-label={t("Import preset JSON")} onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; if (!file) return; if (file.size > 64000) { failure(new Error("Preset files must not exceed 64 KB.")); return; } void file.text().then(text => { edit(parsePresetJSON(text), true); }).catch(failure); }} />
      <div className="preset-list">{builtins.map(row)}</div><h3>{t("Saved presets")}</h3>
      {!presets.length && <p className="helper">{t("Copy a built-in preset to create your first saved preset.")}</p>}<div className="preset-list">{presets.map(row)}</div>
    </>}
    {saveError && <p className="notice error" role="alert">{t(saveError)}</p>}{notice && <p role="status">{t(notice)}</p>}
  </section>;
}
