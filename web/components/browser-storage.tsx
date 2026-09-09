"use client";
import { TriangleAlert } from "lucide-react";
import { HoverBubble } from "./hover-bubble";
import { useConfirmation } from "./use-confirmation";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { DOCUMENTATION_BASE } from "@/lib/documentation-registry.mjs";
import { browserStorage, browserStorageBreakdown, exportBrowserSettings, importBrowserSettings, productionBrowserStorageEnabled, STORAGE_NOTICE_KEY, STORAGE_WARNING_BYTES, subscribeStorageWarnings, validateBrowserSettings } from "@/lib/storage";
import { useNotifications } from "./notifications";
import "./browser-storage.css";

const OPEN_NOTICE = "docreview:open-storage-notice";

/** Keep quota and recovery warnings in the existing non-modal notification region. */
export function BrowserStorageSupport({ enabled }: { enabled: boolean }) {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!enabled) { setOpen(false); return; }
    setOpen(browserStorage().getItem(STORAGE_NOTICE_KEY) !== "done");
    const reopen = () => setOpen(true);
    window.addEventListener(OPEN_NOTICE, reopen);
    const unsubscribe = subscribeStorageWarnings(({ reason }) => {
      const message = reason === "quota" ? "Browser storage is full. Changes remain available in this tab; export a backup before closing it."
        : reason === "unavailable" ? "Browser storage is unavailable. Changes remain available in this tab only."
          : "Some saved browser data could not be read. The original data is preserved for export; defaults are used for this session.";
      notify(t(message), "warning", "browser-storage-warning", 0, { event: "browser-storage-warning-warning" });
    });
    return () => { unsubscribe(); window.removeEventListener(OPEN_NOTICE, reopen); };
  }, [enabled, notify, t]);
  /** Remember only an explicit dismissal; there is no timer or modal focus capture. */
  function dismiss() { browserStorage().setItem(STORAGE_NOTICE_KEY, "done"); setOpen(false); }
  if (!enabled || !open) return null;
  return <aside className="browser-storage-notice" role="status" aria-label={t("Browser storage")} onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); dismiss(); } }}>
    <strong>{t("⚠️ Settings and conversations are saved only in this browser")}</strong>
    <p>{t("They are not synced and can be removed when you clear browser data.")}</p>
    <div><a href={`${DOCUMENTATION_BASE}/docs/${locale}/settings/#browser-storage`} target="_blank" rel="noreferrer">{t("Learn more")}</a><button className="button" type="button" onClick={dismiss}>{t("Got it")}</button></div>
  </aside>;
}

/** Show estimates as binary units without claiming a fixed browser-specific quota. */
function sizeLabel(bytes: number): string { return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1024 / 1024).toFixed(2)} MiB`; }

/** Export exact local payloads and confirm a fully validated import before overwriting. */
export function BrowserStorageSettings({ disabled = false }: { disabled?: boolean }) {
  const { confirm, confirmationDialog } = useConfirmation();
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const input = useRef<HTMLInputElement>(null);
  const [revision, setRevision] = useState(0);
  const [working, setWorking] = useState(false);
  if (!productionBrowserStorageEnabled()) return null;
  const rows = browserStorageBreakdown();
  const total = rows.reduce((sum, row) => sum + row.bytes, 0);
  /** Download through a short-lived object URL; settings never leave the browser. */
  function download() {
    const url = URL.createObjectURL(new Blob([exportBrowserSettings()], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "docreview-browser-settings.json";
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 0);
    notify(t("Browser settings exported."), "success", "browser-export", undefined, { event: "browser-export" });
  }
  /** Reject malformed files before asking permission or touching any stored entry. */
  async function restore(file?: File) {
    if (!file) return;
    setWorking(true);
    try {
      const text = await file.text(); validateBrowserSettings(text);
      if (!await confirm(t("Replace this browser's DocReview settings and conversations with this file?"))) return;
      const persisted = importBrowserSettings(text, true);
      setRevision(value => value + 1);
      if (persisted) notify(t("Browser settings imported."), "success", "browser-storage-import", undefined, { event: "browser-storage-import-notice" });
    } catch { notify(t("This browser settings file is invalid or unsupported. Nothing was imported."), "error", "browser-storage-import", undefined, { event: "browser-storage-import-error" }); }
    finally { setWorking(false); if (input.current) input.current.value = ""; }
  }
  return <section className="browser-storage-settings" aria-label={t("Browser storage")} data-revision={revision}>{confirmationDialog}
    <header><h3>{t("Browser storage")}</h3><HoverBubble pinnable showClose={false} width={360} align="end" placement="below" label={t("Browser storage")} bubble={<><strong>{t("Settings and conversations are saved only in this browser")}</strong><p>{t("They are not synced and can be removed when you clear browser data.")}</p><a className="inline-link" href={`${DOCUMENTATION_BASE}/docs/${locale}/settings/#browser-storage`} target="_blank" rel="noreferrer">{t("Learn more")}</a></>}><button className="icon-button browser-storage-info" type="button" aria-label={t("Show browser storage notice")}><TriangleAlert size={18} aria-hidden="true" /></button></HoverBubble></header>
    <p>{t("Estimated browser storage: {size}", { size: sizeLabel(total) })}</p>
    {total >= STORAGE_WARNING_BYTES && <p role="status">{t("Browser storage is nearing a common limit. Export a backup; the actual quota depends on your browser.")}</p>}
    <details><summary>{t("Storage by key")}</summary><dl>{rows.map(row => <div key={row.key}><dt><code>{row.key}</code></dt><dd>{sizeLabel(row.bytes)}</dd></div>)}</dl></details>
    <div className="action-row"><button className="button" type="button" onClick={download}>{t("Export browser settings")}</button><button className="button" type="button" disabled={disabled || working} onClick={() => input.current?.click()}>{t("Import browser settings")}</button></div>
    <input ref={input} type="file" accept="application/json,.json" hidden aria-label={t("Browser settings file")} onChange={event => void restore(event.target.files?.[0])} />
    {disabled && <p className="helper">{t("Finish the current request before importing settings.")}</p>}
    <p className="helper">{t("Exports include conversations and prompt text. Keep your backup private.")}</p>
  </section>;
}
