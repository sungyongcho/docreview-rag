import { getFilePresets, putFilePreset, deleteFilePreset } from "./api";
import { previewState } from "./production-preview";
import { loadSavedPresets, savePreset, deletePreset, PRESETS_CHANGED, presetError, type SavedPreset } from "./saved-presets";
import { BUILTIN_PRESETS, type Capabilities } from "./types";

export interface PresetCatalog { presets_version: string; unchanged?: boolean; presets: SavedPreset[]; errors: Array<{ file: string; error: string }> }
export const PREVIEW_PRESET_NOTICE = "Presets are not saved in preview (memory only). On the deployed screen, they are saved in this browser.";
export const PENDING_PRESET_NOTICE = "Preset storage is unavailable until server permissions are confirmed.";
export type PresetStorageKind = "file" | "browser" | "preview" | "pending";
type PresetPermissions = Pick<Capabilities, "environment" | "can_change_custom_retrieval">;
let permissions: PresetPermissions | null = null;
let permissionRevision = 0;
const permissionListeners = new Set<() => void>();

/** Receive effective server permissions; a live bundle alone grants no file access. */
export function configurePresetStorage(value: PresetPermissions | null): void {
  if (permissions?.environment === value?.environment && permissions?.can_change_custom_retrieval === value?.can_change_custom_retrieval) return;
  permissions = value ? { environment: value.environment, can_change_custom_retrieval: value.can_change_custom_retrieval } : null;
  permissionRevision += 1;
  for (const listener of permissionListeners) listener();
}

/** Wake all mounted selectors when confirmed runtime permissions change. */
export function subscribePresetStorage(listener: () => void): () => void {
  permissionListeners.add(listener);
  return () => { permissionListeners.delete(listener); };
}

/** Hydration starts without a server-side claim of local administrator access. */
export function serverPresetStorageKind(): PresetStorageKind {
  return process.env.NEXT_PUBLIC_ADMIN_MODE === "live" ? "pending" : "browser";
}

/** Preview and effective PROD never reach the DEV file API, including in a live bundle. */
export function presetStorageKind(): PresetStorageKind {
  if (previewState().mode !== "normal") return "preview";
  if (process.env.NEXT_PUBLIC_ADMIN_MODE !== "live" || permissions?.environment === "prod") return "browser";
  return permissions?.environment === "dev" && permissions.can_change_custom_retrieval ? "file" : "pending";
}

let catalog: PresetCatalog | null = null;
let error: string | null = null;
let inflight: Promise<void> | null = null;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

/** All mounted selectors share one visible-only metadata request every three seconds. */
export function refreshFilePresets(): Promise<void> {
  if (inflight) return inflight;
  if (presetStorageKind() !== "file") return Promise.resolve();
  const revision = permissionRevision;
  inflight = getFilePresets(catalog?.presets_version).then(next => {
    if (revision !== permissionRevision || presetStorageKind() !== "file") return;
    if (!next.unchanged) {
      if (!Array.isArray(next.presets) || next.presets.some(p => presetError(p)) || !Array.isArray(next.errors)) throw new Error("Saved presets could not be read.");
      catalog = next;
      for (const builtin of BUILTIN_PRESETS) {
        const found = next.presets.find(p => p.id === builtin.id && p.builtin);
        if (found) builtin.retrieval = found.retrieval;
      }
    }
    error = null;
  }).catch(reason => { if (revision === permissionRevision && presetStorageKind() === "file") error = reason instanceof Error ? reason.message : "Saved presets could not be read."; }).finally(() => {
    inflight = null;
    for (const listener of listeners) listener();
  });
  return inflight;
}

/** Watch metadata only while a component is using the file adapter. */
export function subscribeFilePresets(listener: () => void): () => void {
  listeners.add(listener);
  if (!timer) {
    void refreshFilePresets();
    timer = setInterval(() => { if (document.visibilityState === "visible") void refreshFilePresets(); }, 3000);
    document.addEventListener("visibilitychange", visibilityRefresh);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size && timer) {
      clearInterval(timer); timer = null;
      document.removeEventListener("visibilitychange", visibilityRefresh);
    }
  };
}

/** Refresh immediately after returning to the page, without hidden-tab polling. */
function visibilityRefresh() { if (document.visibilityState === "visible") void refreshFilePresets(); }

export function readPresetCatalog() {
  if (presetStorageKind() === "pending") return { presets: [], builtins: BUILTIN_PRESETS, fileErrors: [], error: null };
  if (presetStorageKind() === "file") return { presets: catalog?.presets.filter(p => !p.builtin) ?? [], builtins: catalog ? BUILTIN_PRESETS.flatMap(builtin => catalog!.presets.filter(p => p.builtin && p.id === builtin.id)) : BUILTIN_PRESETS, fileErrors: catalog?.errors ?? [], error };
  return { presets: loadSavedPresets(), builtins: BUILTIN_PRESETS, fileErrors: [], error: null };
}

/** Preserve synchronous browser updates and return a completion promise for file writes. */
export function saveStoredPreset(preset: SavedPreset): void | Promise<void> {
  const kind = presetStorageKind();
  if (kind === "preview") throw new Error(PREVIEW_PRESET_NOTICE);
  if (kind === "pending") throw new Error(PENDING_PRESET_NOTICE);
  const invalid = presetError(preset);
  if (invalid) throw new Error(invalid);
  if (preset.builtin) throw new Error("Built-in presets can only be copied.");
  if (kind === "browser") return savePreset({ ...preset, updated_at: new Date().toISOString() });
  return putFilePreset(preset).then(async () => { await inflight; catalog = null; await refreshFilePresets(); window.dispatchEvent(new Event(PRESETS_CHANGED)); });
}

export function deleteStoredPreset(id: string): void | Promise<void> {
  const kind = presetStorageKind();
  if (kind === "preview") throw new Error(PREVIEW_PRESET_NOTICE);
  if (kind === "pending") throw new Error(PENDING_PRESET_NOTICE);
  if (kind === "browser") return deletePreset(id);
  return deleteFilePreset(id).then(async next => { await inflight; catalog = next; error = null; window.dispatchEvent(new Event(PRESETS_CHANGED)); for (const listener of listeners) listener(); });
}
