"use client";
import { useI18n } from "@/lib/i18n";


import { useEffect, useRef, useState } from "react";
import { Plug, Unplug, RotateCcw } from "lucide-react";
import { disconnectLocalLLM, getLocalLLMConnection, resetLocalLLMConnection, saveLocalLLMConnection } from "@/lib/api";
import type { LocalLLMConnection, Readiness, ReviewEngineState } from "@/lib/types";
import { localEngineStatus } from "@/lib/local-models";

const CONNECTION_SOURCES: Record<LocalLLMConnection["source"], string> = {
  default: "Application defaults",
  environment: "Environment defaults",
  dotenv: ".env file",
  saved: "Saved connection",
  disabled: "Disconnected",
  invalid: "Invalid saved settings",
};

/** Probe a server before saving it; failed changes leave the working connection intact. */
export function LocalConnectionSettings({ readiness, onChanged }: {
  readiness?: Readiness | null;
  onChanged?: (local: ReviewEngineState) => void;
}) {
  const { t } = useI18n();
  const [connection, setConnection] = useState<LocalLLMConnection | null>(null);
  const [url, setUrl] = useState("");
  const [protocol, setProtocol] = useState<LocalLLMConnection["protocol"]>("auto");
  const [busy, setBusy] = useState(true);
  const [pendingAction, setPendingAction] = useState<"connect" | "disconnect" | "reset" | null>(null);
  const [error, setError] = useState<{ detail: string; appOwned: boolean; kept?: boolean } | null>(null);
  const [message, setMessage] = useState("");
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void getLocalLLMConnection(controller.signal).then((value) => {
      if (!mounted.current || controller.signal.aborted) return;
      setConnection(value);
      setUrl(value.base_url ?? value.initial_base_url);
      setProtocol(value.protocol);
    }).catch((reason) => {
      if (!controller.signal.aborted) setError({ detail: reason instanceof Error ? reason.message : "Connection settings could not be loaded.", appOwned: !(reason instanceof Error) });
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { mounted.current = false; controller.abort(); };
  }, []);

  useEffect(() => {
    const local = readiness?.review_engines?.local;
    if (local) setConnection((current) => current ? { ...current, local } : current);
  }, [readiness]);

  async function change(action: "connect" | "disconnect" | "reset") {
    if (busy) return;
    setPendingAction(action);
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const value = action === "connect" ? await saveLocalLLMConnection(url.trim(), protocol)
        : action === "disconnect" ? await disconnectLocalLLM() : await resetLocalLLMConnection();
      if (!mounted.current) return;
      setConnection(value);
      setUrl(value.base_url ?? value.initial_base_url);
      setProtocol(value.protocol);
      setMessage(action === "connect" ? "Connected and saved. Models refreshed."
        : action === "disconnect" ? "Disconnected. Local answers are disabled until you connect or reset."
        : "Saved override removed. Initial connection settings restored.");
      onChanged?.(value.local);
    } catch (reason) {
      if (!mounted.current) return;
      const detail = reason instanceof Error ? reason.message : "The connection could not be changed.";
      setError({ detail, appOwned: !(reason instanceof Error), kept: true });
    } finally {
      if (mounted.current) { setBusy(false); setPendingAction(null); }
    }
  }

  return <div className="local-connection-settings" aria-busy={busy}>
    <p className="helper">{t("Connect a separately installed model server. Saved settings take priority over the initial environment configuration and apply immediately.")}</p>
    <div className="connection-fields">
    <label>{t("Server URL")}<input type="url" value={url} placeholder="http://host.docker.internal:11434" spellCheck={false} autoCapitalize="none" disabled={busy} onChange={(event) => setUrl(event.target.value)} /></label>
    <label>{t("Protocol")}<select value={protocol} disabled={busy} onChange={(event) => setProtocol(event.target.value as LocalLLMConnection["protocol"])}><option value="auto">{t("Auto detect")}</option><option value="ollama">{t("Ollama")}</option><option value="openai_responses">{t("OpenAI Responses compatible")}</option></select></label>
    </div>
    <div className="connection-actions" role="group" aria-label={t("Connection actions")}>
      <button className="button primary" type="button" disabled={busy || !url.trim()} onClick={() => void change("connect")}><Plug size={16} aria-hidden="true" />{t(pendingAction === "connect" ? "Connecting…" : "Connect & save")}</button>
      <button className="button" type="button" disabled={busy || !connection || connection.source === "disabled"} onClick={() => void change("disconnect")}><Unplug size={16} aria-hidden="true" />{t(pendingAction === "disconnect" ? "Disconnecting…" : "Disconnect")}</button>
      <button className="button ghost" type="button" disabled={busy || !connection} onClick={() => void change("reset")}><RotateCcw size={16} aria-hidden="true" />{t(pendingAction === "reset" ? "Restoring…" : "Restore defaults")}</button>
    </div>
    <p className="helper connection-action-help">{t("Disconnect disables local answers. Restore defaults removes the saved override and uses the initial server configuration.")}</p>
    {busy && !connection && <p className="helper" role="status">{t("Loading connection settings…")}</p>}
    {error && <div className="notice error" role="alert"><strong>{t(error.kept ? "Connection change failed." : "Connection settings could not be loaded.")}</strong>{error.kept && <p>{t("Your previous connection setting was kept.")}</p>}<details><summary>{t("Technical details")}</summary><p>{error.appOwned ? t(error.detail) : error.detail}</p></details></div>}
    {message && <p className="notice" role="status">{t(message)}</p>}
    {connection && <>
      <section className="connection-summary" aria-labelledby="connection-summary-title">
      <h3 id="connection-summary-title">{t("Connection status")}</h3>
      <p className="helper" role="status">{t(localEngineStatus(connection.local))}</p>
      <dl className="connection-facts"><div><dt>{t("Configuration source")}</dt><dd>{t(CONNECTION_SOURCES[connection.source])}</dd></div><div><dt>{t("Active server")}</dt><dd><code>{connection.base_url ?? (connection.source === "disabled" ? t("Disconnected") : t("Unavailable"))}</code></dd></div><div><dt>{t("Initial server")}</dt><dd><code>{connection.initial_base_url}</code></dd></div></dl>
      {connection.error && <div className="notice error" role="alert"><strong>{t("Model server is unavailable.")}</strong><details><summary>{t("Technical details")}</summary><p>{connection.error}</p></details></div>}
      </section>
      <section className="connection-model-section" aria-labelledby="connection-models-title">
      <h3 id="connection-models-title">{t("Detected models")}</h3>
      <p className="helper">{t("Choose an answer model above the conversation input. Connecting a server does not change the embedding provider.")}</p>
      {connection.local.models?.length ? <ul className="connection-models">{connection.local.models.map((model) => <li key={model.name}><code>{model.name}</code><span className={model.selectable ? "model-usable" : ""}>{t(model.selectable ? "Available for answers" : "Unavailable for answers")}</span></li>)}</ul> : <p className="helper">{t("No models detected. Check the server connection and installed models.")}</p>}
      </section>
    </>}
  </div>;
}
