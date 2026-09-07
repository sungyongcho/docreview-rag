"use client";
import { useI18n } from "@/lib/i18n";
import { useSavedPresets } from "@/lib/use-saved-presets";
import { sameRetrieval } from "@/lib/saved-presets";
import { applyRetrievalPreset, resolvedRetrievalProfile, type RetrievalPreset, type ReviewSessionDraft } from "@/lib/types";

/** Resolve saved presets to ordinary custom values without attaching storage IDs to requests. */
export function RetrievalPresetSelect({ profile, editable, onChange, onManage, onLocked, id }: { profile: ReviewSessionDraft; editable: boolean; onChange: (update: Partial<ReviewSessionDraft>) => void; onManage?: () => void; onLocked?: () => void; id?: string }) {
  const { t } = useI18n();
  const { presets, error } = useSavedPresets();
  const saved = editable && profile.retrieval_preset === "custom" ? presets.find(p => sameRetrieval(p.retrieval, resolvedRetrievalProfile(profile))) : null;
  return <><select id={id} data-help={id === "composer-retrieval-preset" ? "review.preset" : undefined} className="chip" aria-label={t("Retrieval preset")} value={saved ? `saved:${saved.id}` : profile.retrieval_preset} onChange={event => {
    const value = event.target.value;
    if (!editable && (value === "custom" || value.startsWith("saved:") || value === "manage")) { onLocked?.(); return; }
    if (value === "manage") { onManage?.(); return; }
    if (value.startsWith("saved:")) {
      if (!editable) return;
      const preset = presets.find(p => p.id === value.slice(6));
      if (preset) onChange({ retrieval_preset: "custom", custom_retrieval: structuredClone(preset.retrieval) });
    } else if (value !== "custom" || editable) onChange(applyRetrievalPreset(profile, value as RetrievalPreset));
  }}>
    <option value="balanced">{t("Balanced")}</option><option value="korean">{t("Korean")}</option><option value="accuracy">{t("Accuracy")}</option>
    {profile.retrieval_preset === "custom" && !saved && <option value="custom">{t("Custom")}</option>}
    {editable && presets.map(p => <option value={`saved:${p.id}`} key={p.id}>{p.name}</option>)}
    {editable && onManage && <option value="manage">{t("Manage presets…")}</option>}
  </select>{editable && error && <small role="alert">{t(error)}</small>}</>;
}
