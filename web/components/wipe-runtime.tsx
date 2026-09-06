"use client";
import { LOCALE_KEY, useI18n } from "@/lib/i18n";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, ChevronDown, X } from "lucide-react";
import { useRetainedPanelActive } from "@/components/retained-panel";
import { getWipeCapability, getWipeStatus, operatorAvailable, OperatorRequestError, previewWipe, recoverWipe, startWipe, type WipeCapability, type WipeDiagnosis, type WipePreview, type WipeResult } from "@/lib/operator-api";

export function clearDocReviewBrowserData(storage: Storage) {
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index)).filter((key): key is string => key !== LOCALE_KEY && Boolean(key?.startsWith("docreview:") || key?.startsWith("docreview.")));
  keys.forEach((key) => storage.removeItem(key));
}

function ResetDiagnosis({ diagnosis }: { diagnosis: WipeDiagnosis }) {
  const { t } = useI18n();
  return <section className="wipe-diagnosis" aria-label={t("Reset diagnosis")}>
    <h3>{t("Why reset is blocked")}</h3>
    {diagnosis.code === "runtime_file_permission" && <p>{t("The local operator cannot access a runtime file with the required permissions. Review file ownership, directory permissions, and the operator identity below.")}</p>}
    <p><strong>{t("Blocking code")}</strong>: <code>{diagnosis.code}</code></p>
    <details><summary>{t("Permission and runtime details")}</summary><pre>{JSON.stringify(diagnosis.details, null, 2)}</pre></details>
    <h3>{t("How to resolve this")}</h3>
    <ol>{diagnosis.remediation.map((step, index) => <li key={index}>{step.startsWith("sudo ") ? <code>{step}</code> : t(step)}</li>)}</ol>
    <p>{t("No files or permissions were changed by this check. Apply only the changes you approve, then check again.")}</p>
  </section>;
}

export function WipeRuntime({ enabled }: { enabled: boolean }) {
  const { t } = useI18n();
  const dialog = useRef<HTMLElement>(null);
  const disclosure = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  const active = useRetainedPanelActive();
  const visible = open && active && enabled;
  const [preview, setPreview] = useState<WipePreview | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [result, setResult] = useState<WipeResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [capability, setCapability] = useState<WipeCapability | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<WipeDiagnosis | null>(null);
  const [checkVersion, setCheckVersion] = useState(0);
  const connected = operatorAvailable();
  const partial = result?.status === "failed" || result?.status === "interrupted";
  const canPreview = capability?.available === true && result?.status !== "running" && !result?.recovery_required && !(partial && result.retryable === false);
  useEffect(() => {
    let cancelled = false;
    setCapability(null); setPreview(null); setConfirmation(""); setDiagnosis(null);
    if (!enabled || !connected) { setResult(null); setChecking(false); return; }
    setChecking(true); setError("");
    void Promise.allSettled([getWipeCapability(), getWipeStatus()]).then(([availability, status]) => {
      if (cancelled) return;
      if (status.status === "fulfilled") {
        setResult(status.value.status === "idle" ? null : status.value);
        if (["running", "failed", "interrupted"].includes(status.value.status)) setOpen(true);
      }
      if (availability.status === "fulfilled" && status.status === "fulfilled") {
        setCapability(availability.value);
        setDiagnosis(availability.value.diagnosis ?? null);
        setCheckedAt(availability.value.checked_at ?? new Date().toISOString());
      } else {
        const reason = availability.status === "rejected" ? availability.reason : status.status === "rejected" ? status.reason : "";
        recordFailure(reason);
      }
      setChecking(false);
    });
    return () => { cancelled = true; };
  }, [enabled, connected, checkVersion]);
  useEffect(() => {
    if (!enabled || result?.status !== "running") return;
    let pending = false;
    let cancelled = false;
    const interval = window.setInterval(() => {
      if (pending) return;
      pending = true;
      void getWipeStatus().then((status) => {
        if (cancelled) return;
        setResult(status); setError("");
        if (status.status !== "running") { setCapability(null); setPreview(null); setConfirmation(""); }
      }).catch((reason) => {
        if (cancelled) return;
        setCapability(null); setPreview(null); setConfirmation("");
        setError(reason instanceof Error ? reason.message : String(reason));
      }).finally(() => { pending = false; });
    }, 1000);
    return () => { cancelled = true; window.clearInterval(interval); };
  }, [enabled, result?.status]);
  useEffect(() => {
    if (!preview) return;
    const timer = window.setTimeout(() => {
      setPreview(null); setConfirmation(""); setCapability(null);
      setError(t("The reset preview expired. Check availability and review a new preview."));
    }, Math.max(0, preview.expires * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [preview, t]);
  useEffect(() => {
    if (!visible) return;
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    return () => {
      const target = previous?.isConnected && !previous.matches(":disabled") ? previous : disclosure.current?.querySelector<HTMLElement>("summary");
      if (!target?.closest("[hidden], [inert]")) target?.focus();
    };
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    function key(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy && result?.status !== "running") close();
      if (event.key !== "Tab" || !dialog.current) return;
      const controls = [...dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), summary, a[href]')].filter((control) => !control.closest("details:not([open])") || control.tagName === "SUMMARY");
      const first = controls[0], last = controls.at(-1);
      if (!controls.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); };
  }, [visible, busy, result?.status]);
  function close() {
    setOpen(false); setPreview(null); setConfirmation("");
  }
  function recordFailure(reason: unknown) {
    const message = reason instanceof Error ? reason.message : String(reason);
    const detail = reason instanceof OperatorRequestError && reason.diagnosis ? reason.diagnosis : {
      code: "reset_check_failed",
      details: {},
      remediation: ["The cause is unknown. Review the operator error and local service status, then check reset availability again."],
    };
    const checked = new Date().toISOString();
    setError(message); setDiagnosis(detail); setCheckedAt(checked);
    setCapability({ available: false, reason: message, checked_at: checked, diagnosis: detail });
  }
  function recheck() {
    setCapability(null); setPreview(null); setConfirmation(""); setDiagnosis(null);
    setChecking(true); setError("");
    setCheckVersion((value) => value + 1);
  }
  async function verifyCapability() {
    setCapability(null);
    const availability = await getWipeCapability();
    setCapability(availability);
    setCheckedAt(availability.checked_at ?? new Date().toISOString());
    setDiagnosis(availability.diagnosis ?? null);
    if (!availability.available) throw new OperatorRequestError(availability.reason || t("Runtime reset is unavailable."), availability.diagnosis ?? undefined);
  }
  async function inspect() {
    if (!enabled || !canPreview || busy || checking) return;
    setOpen(true); setBusy(true); setError(""); setPreview(null); setConfirmation("");
    try { await verifyCapability(); setPreview(await previewWipe()); setResult(null); }
    catch (reason) { recordFailure(reason); }
    finally { setBusy(false); }
  }
  async function execute() {
    if (!enabled || !canPreview || !preview || confirmation !== preview.confirmation || busy || preview.expires * 1000 <= Date.now()) return;
    const selected = preview;
    setPreview(null); setConfirmation("");
    setBusy(true); setError("");
    try { await verifyCapability(); setResult(await startWipe(selected.token, confirmation)); setCapability(null); }
    catch (reason) {
      recordFailure(reason);
      try {
        const status = await getWipeStatus();
        if (status.status !== "idle") setResult(status);
      } catch (statusError) {
        const message = statusError instanceof Error ? statusError.message : String(statusError);
        setError((current) => `${current}\n${message}`);
      }
    }
    finally { setBusy(false); }
  }
  async function recover() {
    if (!enabled || !partial || !result.recovery_required || busy) return;
    setBusy(true); setCapability(null); setPreview(null); setConfirmation(""); setError("");
    try { setResult(await recoverWipe()); setCheckVersion((value) => value + 1); }
    catch (reason) { recordFailure(reason); }
    finally { setBusy(false); }
  }
  function finish() {
    if (result?.status !== "succeeded") return;
    try {
      clearDocReviewBrowserData(localStorage);
      window.location.assign("/docreview-rag-agent/");
    } catch (reason) { setError(String(reason)); }
  }
  if (!enabled) return null;
  return <section className="wipe-danger-zone">
    <details ref={disclosure}><summary><AlertTriangle size={16} aria-hidden="true" /><span>{t("Reset runtime data")}</span><ChevronDown className="wipe-disclosure-arrow" size={16} aria-hidden="true" /></summary>
      <div className="wipe-disclosure-body">
        <p>{t("Start over by clearing this local runtime. Source files and credentials are preserved.")}</p>
        <p>{t("After reset, download SEC/DART filings again, ingest them, generate embeddings, rebuild BM25, and configure your answer model in Build.")}</p>
        <p>{t("For a terminal reset followed by a full rebuild and restart, run rag-fresh-start. Run rag-help for the equivalent corpus commands.")}</p>
        <button className="button danger-button" type="button" disabled={!canPreview || busy || checking} onClick={() => void inspect()}>{t("Wipe everything")}</button>
        {!connected && <p>{t("Start the development stack with rag-dev to enable Local Operations.")}</p>}
        {connected && <>
          <p role="status" className="wipe-availability">{checking ? t("Checking reset availability…") : canPreview ? t("Reset is available. All preview checks passed.") : t("Reset is blocked.")}</p>
          {!checking && checkedAt && <p className="muted">{t("Last checked")}: <time dateTime={checkedAt}>{new Date(checkedAt).toLocaleString()}</time></p>}
          {!checking && !canPreview && !error && <p>{capability?.reason || t("Runtime reset is unavailable.")}</p>}
          {!open && error && <p role="alert" className="notice error">{error}</p>}
          {!open && !checking && diagnosis && <ResetDiagnosis diagnosis={diagnosis} />}
          <button type="button" className="button" disabled={busy || checking} onClick={() => { setOpen(true); recheck(); }}>{t("View reset status")}</button>
          <button type="button" className="button" disabled={busy || checking} onClick={recheck}>{t("Check reset availability")}</button>
        </>}
      </div>
    </details>
    {visible && createPortal(<div className="wipe-scrim"><section ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="wipe-title" aria-describedby="wipe-warning" className="wipe-dialog">
      <header><h2 id="wipe-title">{t("Delete all runtime data?")}</h2><button type="button" className="icon-button" aria-label={t("Close reset dialog")} disabled={busy || result?.status === "running"} onClick={close}><X size={18} /></button></header>
      <p id="wipe-warning" className="notice error"><strong>{t("No backup. This cannot be undone.")}</strong> {t("Database records, downloaded filings, generated evaluation artifacts, saved connections and DocReview browser data will be cleared.")}</p>
      {busy && <p role="status">{t("Checking the local runtime…")}</p>}
      {checking && <p role="status">{t("Checking reset availability…")}</p>}
      {!checking && !busy && !preview && !result && !error && <>
        <p role="status">{canPreview ? t("Reset is available. All preview checks passed.") : t("Reset is blocked.")}</p>
        {canPreview && <button type="button" className="button" onClick={() => void inspect()}>{t("Review a fresh deletion preview")}</button>}
      </>}
      {error && <p role="alert" className="notice error">{error}</p>}
      {diagnosis && <ResetDiagnosis diagnosis={diagnosis} />}
      {preview && <>
        <dl className="status-list"><div><dt>{t("Project")}</dt><dd>{preview.target.project}</dd></div><div><dt>{t("Database volume")}</dt><dd>{preview.target.volume}</dd></div><div><dt>{t("Runtime files")}</dt><dd>{preview.target.files.length}</dd></div></dl>
        <details><summary>{t("Exact deletion targets")}</summary><pre>{JSON.stringify({ tables: preview.target.tables, files: preview.target.files }, null, 2)}</pre></details>
        <p><strong>{t("Preserved:")}</strong> {t("code, keys and .env, tutorials and images, manifest/golden/profile sources, unrelated files.")}</p>
        <label>{t("Type the confirmation exactly")}<code>{preview.confirmation}</code><input autoComplete="off" spellCheck={false} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        <button type="button" className="button danger-button" disabled={!canPreview || busy || confirmation !== preview.confirmation} onClick={() => void execute()}>{t("Permanently clear this runtime")}</button>
      </>}
      {result && <>
        <p role="status">{result.status === "succeeded" ? t("Runtime reset completed successfully.") : `${result.status} · ${result.stage ?? ""}`}</p><p>{result.message}</p>
        <pre>{JSON.stringify({ completed: result.completed, removed_files: result.removed_files }, null, 2)}</pre>
        {result.status === "succeeded" && <button type="button" className="button primary" onClick={finish}>{t("Clear browser data and start again")}</button>}
        {partial && <>
          <p className="notice error">{t("The reset did not complete. Some data may already be deleted. Review the completed steps and recovery instructions before trying again.")}</p>
          {result.recovery?.length ? <><h3>{t("Recovery instructions")}</h3><ol>{result.recovery.map((step, index) => <li key={index}>{step}</li>)}</ol></> : null}
          {result.recovery_error && <p role="alert" className="notice error">{result.recovery_error}</p>}
          {result.recovery_required && <button type="button" className="button" disabled={busy || checking} onClick={() => void recover()}>{t("Release reset hold")}</button>}
        </>}
      </>}
      <footer className="wipe-dialog-actions">
        {error && !preview && <button type="button" className="button" disabled={busy || checking || result?.status === "running"} onClick={recheck}>{t("Check reset availability")}</button>}
        <button type="button" className="button" disabled={busy || result?.status === "running"} onClick={close}>{t("Cancel")}</button>
      </footer>
    </section></div>, document.body)}
  </section>;
}
