"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { PRESETS_CHANGED } from "./saved-presets";
import { presetStorageKind, readPresetCatalog, serverPresetStorageKind, subscribeFilePresets, subscribePresetStorage } from "./preset-storage";
import { BUILTIN_PRESETS } from "./types";

/** Keep every selector on the same storage adapter and directory version. */
export function useSavedPresets() {
  const storageKind = useSyncExternalStore(subscribePresetStorage, presetStorageKind, serverPresetStorageKind);
  const [state, setState] = useState<ReturnType<typeof readPresetCatalog>>({ loaded: false, presets: [], builtins: BUILTIN_PRESETS, fileErrors: [], error: null });
  useEffect(() => {
    function refresh() {
      try { setState(readPresetCatalog()); }
      catch (reason) { setState(old => ({ ...old, error: reason instanceof Error ? reason.message : "Saved presets could not be read." })); }
    }
    refresh();
    const unsubscribe = storageKind === "file" ? subscribeFilePresets(refresh) : () => {};
    window.addEventListener(PRESETS_CHANGED, refresh);
    window.addEventListener("storage", refresh);
    return () => { unsubscribe(); window.removeEventListener(PRESETS_CHANGED, refresh); window.removeEventListener("storage", refresh); };
  }, [storageKind]);
  return { ...state, storageKind };
}
