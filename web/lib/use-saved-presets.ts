"use client";
import { useEffect, useState } from "react";
import { loadSavedPresets, PRESETS_CHANGED, type SavedPreset } from "./saved-presets";

/** Refresh saved names in every selector after a local save or another tab's update. */
export function useSavedPresets() {
  const [presets, setPresets] = useState<SavedPreset[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    function refresh() {
      try { setPresets(loadSavedPresets()); setError(null); }
      catch { setError("Saved presets could not be read."); }
    }
    refresh();
    window.addEventListener(PRESETS_CHANGED, refresh);
    window.addEventListener("storage", refresh);
    return () => { window.removeEventListener(PRESETS_CHANGED, refresh); window.removeEventListener("storage", refresh); };
  }, []);
  return { presets, error };
}
