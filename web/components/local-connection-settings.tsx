"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, ExternalLink, Plug, RotateCcw, Unplug } from "lucide-react";
import { CodeBlock } from "@/components/code-block";
import { useI18n } from "@/lib/i18n";
import { addLocalLLMServer, diagnoseLocalLLM, disconnectLocalLLM, getLocalLLMConnection, selectLocalLLMServer } from "@/lib/api";
import type { LocalLLMConnection, LocalLLMDiagnostics, LocalLLMServer, Readiness, ReviewEngineState } from "@/lib/types";
import { localEngineStatus } from "@/lib/local-models";
import "./local-connection-settings.css";

const ADD_SERVER = "__add_server__";
const DIAGNOSE_COMMAND = "source ./rag-alias.sh\nrag-ollama-check";
const CONNECTION_SOURCES: Record<LocalLLMConnection["source"], string> = {
  default: "Application defaults", environment: "Environment defaults", dotenv: ".env file",
  saved: "Saved connection", disabled: "Disconnected", invalid: "Invalid saved settings",
};
const CHECK_LABELS = { configuration: "Server selection", connection: "Server connection", models: "Answer models" };
const CHECK_STATUS = { passed: "Passed", failed: "Failed", blocked: "Blocked", unknown: "Not confirmed" };
const CHECK_REASONS: Record<string, string> = {
  configured: "Server settings are ready to check.", disconnected: "Local answers are disconnected.", invalid: "The saved configuration could not be read.",
  reachable: "The app reached the model server.", dns: "The app could not resolve the server name.", refused: "The server refused the connection. Ollama may not be running or listening for this app.",
  timeout: "The server did not respond before the check timed out.", tls: "The server certificate could not be verified.", authentication: "The server rejected authentication.",
  invalid_response: "The address did not return the expected model API.", invalid_url: "The server address is invalid.", connection: "The app could not reach the model server.",
  answer_models_available: "An installed model is verified for answers.", no_answer_models: "The server responded, but no answer model is available.", unconfirmed: "Model availability has not been confirmed.",
};
const RECOVERY: Record<string, string> = {
  select_server: "Choose Default or a saved server, then Connect.",
  check_ollama_service: "Check that Ollama is running on the computer hosting your models.",
  check_ollama_models: "Use ollama list to inspect installed models. Prepare an answer model using the setup guide if none is available.",
  check_listener: "Check whether Ollama accepts connections from the app. A Docker app cannot reach a server bound only to the host loopback address.",
  check_network: "Check the selected computer, network route, and firewall before retrying.",
  review_protocol: "Check the protocol and the server's model API in connection details.",
  review_credentials: "Check this server's existing credentials locally; do not paste keys into a server address.",
  review_tls: "Use the correct HTTPS address and a trusted certificate; do not disable certificate checks.",
  run_connection_diagnostics: "Run rag-ollama-check in the repository terminal for host and Docker checks.",
};

/** Preserve older connection responses while newer servers provide a named catalog. */
function serverOptions(connection: LocalLLMConnection): LocalLLMServer[] {
  if (connection.servers?.length) return connection.servers;
  const defaults: LocalLLMServer = { id: "default", name: "Default", base_url: connection.initial_base_url, protocol: "auto", is_default: true };
  return connection.base_url && connection.base_url !== connection.initial_base_url
    ? [defaults, { id: "legacy", name: "Saved connection", base_url: connection.base_url, protocol: connection.protocol, is_default: false }]
    : [defaults];
}

/** Reject a malformed draft before either connection or diagnostic requests leave the form. */
function validServerUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return ["http:", "https:"].includes(url.protocol) && !!url.hostname && !url.username && !url.password && !url.search && !url.hash;
  } catch { return false; }
}

/** Select a named server, checking it before any working connection is replaced. */
export function LocalConnectionSettings({ readiness, onChanged }: {
  readiness?: Readiness | null;
  onChanged?: (local: ReviewEngineState) => void;
}) {
  const { t, locale } = useI18n();
  const [connection, setConnection] = useState<LocalLLMConnection | null>(null);
  const [selected, setSelected] = useState("default");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [protocol, setProtocol] = useState<LocalLLMConnection["protocol"]>("auto");
  const [busy, setBusy] = useState(true);
  const [pendingAction, setPendingAction] = useState<"connect" | "disconnect" | "reset" | "diagnose" | null>(null);
  const [error, setError] = useState<{ detail: string; kept?: boolean } | null>(null);
  const [message, setMessage] = useState("");
  const [diagnostics, setDiagnostics] = useState<LocalLLMDiagnostics | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const mounted = useRef(true);
  const diagnosticRequest = useRef<AbortController | null>(null);
  const adding = selected === ADD_SERVER;
  const servers = connection ? serverOptions(connection) : [];
  const draftValid = !!name.trim() && name.trim().length <= 80 && name.trim().toLowerCase() !== "default"
    && !servers.some((server) => server.name.toLowerCase() === name.trim().toLowerCase()) && validServerUrl(url);
  const targetValid = !!connection && (!adding || draftValid);
  const guideHref = `/docreview-rag-agent/docs/${locale}/ollama/`;

  function accept(value: LocalLLMConnection) {
    setConnection(value);
    const options = serverOptions(value);
    setSelected(value.selected_server_id ?? options.find((item) => item.base_url === value.base_url)?.id ?? "default");
    setDiagnostics(null);
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    setBusy(true); setError(null);
    void getLocalLLMConnection(controller.signal).then((value) => {
      if (mounted.current && !controller.signal.aborted) accept(value);
    }).catch((reason) => {
      if (!controller.signal.aborted) setError({ detail: reason instanceof Error ? reason.message : "Connection settings could not be loaded." });
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { mounted.current = false; controller.abort(); diagnosticRequest.current?.abort(); };
  }, [loadAttempt]);

  useEffect(() => {
    const local = readiness?.review_engines?.local;
    if (local) setConnection((current) => current ? { ...current, local } : current);
  }, [readiness]);

  async function change(action: "connect" | "disconnect" | "reset") {
    if (busy || (action === "connect" && !targetValid)) return;
    setPendingAction(action); setBusy(true); setError(null); setMessage(""); setDiagnostics(null);
    try {
      const value = action === "connect"
        ? adding ? await addLocalLLMServer(name.trim(), url.trim(), protocol) : await selectLocalLLMServer(selected)
        : action === "disconnect" ? await disconnectLocalLLM() : await selectLocalLLMServer("default");
      if (!mounted.current) return;
      accept(value);
      setName(""); setUrl(""); setProtocol("auto");
      setMessage(action === "connect" ? "Connected and saved. Models refreshed."
        : action === "disconnect" ? "Disconnected. Local answers are disabled until you connect or reset."
        : "Default server restored. Your added servers are kept.");
      onChanged?.(value.local);
    } catch (reason) {
      if (mounted.current) setError({ detail: reason instanceof Error ? reason.message : "The connection could not be changed.", kept: true });
    } finally {
      if (mounted.current) { setBusy(false); setPendingAction(null); }
    }
  }

  async function diagnose() {
    if (busy || !targetValid) return;
    const controller = new AbortController(); diagnosticRequest.current = controller;
    setBusy(true); setPendingAction("diagnose"); setDiagnostics(null); setError(null); setMessage("");
    try {
      const value = await diagnoseLocalLLM(adding ? { base_url: url.trim(), protocol } : { server_id: selected }, controller.signal);
      if (mounted.current && !controller.signal.aborted) setDiagnostics(value);
    } catch (reason) {
      if (mounted.current && !controller.signal.aborted) setError({ detail: reason instanceof Error ? reason.message : "Connection diagnostics could not be completed." });
    } finally {
      if (mounted.current && !controller.signal.aborted) { setBusy(false); setPendingAction(null); }
    }
  }

  const local = connection?.local;
  const reachable = local?.enabled === true || local?.reason === "no_answer_models";
  const answerCount = local?.models?.filter((model) => model.selectable).length;
  const checked = local?.checked_at;
  const activeName = servers.find((server) => server.id === connection?.selected_server_id)?.name
    ?? servers.find((server) => server.base_url === connection?.base_url)?.name;
  const recovery = [...new Set(diagnostics?.checks.flatMap((check) => check.remediation) ?? [])];

  return <div className="local-connection-settings" aria-busy={busy}>
    <div className="connection-intro"><p>{t("Use Ollama on this computer. Choose Default to connect without entering a server address.")}</p>
      <a href={guideHref} target="_blank" rel="noopener noreferrer">{t("Set up Ollama on macOS or Linux")}<ExternalLink size={14} aria-hidden="true" /><span className="visually-hidden">{t("New tab")}</span></a>
    </div>
    <label className="connection-server-picker">{t("Model server")}<select value={selected} disabled={busy || !connection} onChange={(event) => { setSelected(event.target.value); setDiagnostics(null); setMessage(""); setError(null); }}>
      {servers.length ? servers.map((server) => <option key={server.id} value={server.id}>{server.is_default ? "Default" : server.name}</option>) : <option value="default">Default</option>}
      <option value={ADD_SERVER}>{t("Add a server…")}</option>
    </select></label>
    <p className="helper">{t("Default uses the server prepared for this DocReview environment, usually Ollama on this computer. DocReview handles the address; a server must still be running.")}</p>
    {adding && <fieldset className="connection-add-form"><legend>{t("Add a server")}</legend>
      <p className="helper">{t("Add another computer or a separately configured model server. It is saved only after the connection check succeeds.")}</p>
      <div className="connection-fields">
        <label>{t("Server name")}<input value={name} maxLength={80} placeholder={t("For example, Studio computer")} disabled={busy} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("Server URL")}<input type="url" value={url} placeholder="http://192.168.1.20:11434" spellCheck={false} autoCapitalize="none" disabled={busy} aria-invalid={!!url && !validServerUrl(url)} onChange={(event) => setUrl(event.target.value)} /></label>
        <label>{t("Protocol")}<select value={protocol} disabled={busy} onChange={(event) => setProtocol(event.target.value as LocalLLMConnection["protocol"])}><option value="auto">{t("Auto detect")}</option><option value="ollama">Ollama</option><option value="openai_responses">{t("OpenAI Responses compatible")}</option></select></label>
      </div>
      {!draftValid && <p className="helper" role="status">{t("Use a unique name other than Default and an HTTP or HTTPS address without credentials, query parameters, or a fragment.")}</p>}
      <button className="button ghost" type="button" disabled={busy} onClick={() => { setSelected(connection?.selected_server_id ?? "default"); setDiagnostics(null); setError(null); }}>{t("Cancel adding server")}</button>
    </fieldset>}
    <div className="connection-actions" role="group" aria-label={t("Connection actions")}>
      <button className="button primary" type="button" disabled={busy || !targetValid} onClick={() => void change("connect")}><Plug size={16} aria-hidden="true" />{t(pendingAction === "connect" ? "Connecting…" : adding ? "Add & connect" : "Connect")}</button>
      <button className={`button${pendingAction === "diagnose" ? " is-checking" : ""}`} type="button" disabled={busy || !targetValid} onClick={() => void diagnose()}><Activity size={16} aria-hidden="true" />{t(pendingAction === "diagnose" ? "Checking connection…" : "Run connection diagnostics")}</button>
      <button className="button ghost" type="button" disabled={busy || !connection || connection.source === "disabled"} onClick={() => void change("disconnect")}><Unplug size={16} aria-hidden="true" />{t(pendingAction === "disconnect" ? "Disconnecting…" : "Disconnect")}</button>
      <button className="button ghost" type="button" disabled={busy || !connection} onClick={() => void change("reset")}><RotateCcw size={16} aria-hidden="true" />{t(pendingAction === "reset" ? "Restoring…" : "Use Default")}</button>
    </div>
    <p className="helper connection-action-help">{t("Selecting a server does not change the active connection until you connect. Diagnostics only read server metadata; they do not generate an answer, install a model, or save settings.")}</p>
    {busy && !connection && <p className="helper" role="status">{t("Loading connection settings…")}</p>}
    {error && <div className="notice error" role="alert"><strong>{t(error.kept ? "Connection change failed." : pendingAction === null && connection ? "Connection diagnostics could not be completed." : "Connection settings could not be loaded.")}</strong>{error.kept && <p>{t("Your previous connection setting was kept.")}</p>}<details><summary>{t("Technical details")}</summary><p>{error.detail}</p></details>{!connection && <button type="button" className="button" onClick={() => setLoadAttempt((value) => value + 1)}>{t("Retry")}</button>}</div>}
    {message && <p className="notice" role="status">{t(message)}</p>}
    {diagnostics && <section className="connection-diagnostics" aria-label={t("Connection diagnostics")}>
      <h3>{t("Connection diagnostics")} · {diagnostics.server_id === null ? t("New server") : diagnostics.server_name}</h3>
      <p className="helper">{t("Last checked")}: {new Date(diagnostics.checked_at).toLocaleString(locale)}</p>
      <ol>{diagnostics.checks.map((check) => <li key={check.id} className={`connection-check is-${check.status}`}><span className="connection-status-dot" aria-hidden="true" /><div><strong>{t(CHECK_LABELS[check.id])}</strong><p>{t(CHECK_REASONS[check.code] ?? "Check the diagnostic details for the server response.")}</p></div><span>{t(CHECK_STATUS[check.status])}</span></li>)}</ol>
      <p className="helper">{t(diagnostics.available ? "The server has a verified answer model. Select it above the conversation input." : "Follow the setup guide for the failed step, then run diagnostics again. Your active connection has not changed.")}</p>
      {recovery.length > 0 && <div className="connection-recovery"><h4>{t("Next steps")}</h4><ul>{recovery.map((id) => <li key={id}>{t(RECOVERY[id] ?? "Open the setup guide for this diagnostic step.")}</li>)}</ul><a href={guideHref} target="_blank" rel="noopener noreferrer">{t("Ollama setup and recovery guide")}<ExternalLink size={14} aria-hidden="true" /></a></div>}
      <details><summary>{t("Diagnostic details")}</summary><ul>{diagnostics.checks.map((check) => <li key={check.id}><code>{check.id}: {check.code}</code></li>)}</ul></details>
    </section>}
    {connection && <>
      <section className="connection-summary" aria-labelledby="connection-summary-title">
        <h3 id="connection-summary-title">{t("Connection status")}</h3>
        <div className="connection-health-grid">
          <div><span>{t("Active server")}</span><strong>{connection.source === "disabled" ? t("Disconnected") : activeName === "Default" ? "Default" : activeName ?? t("Unavailable")}</strong></div>
          <div className={reachable ? "is-passed" : local?.reason === "unreachable" ? "is-failed" : "is-unknown"}><span>{t("Server connection")}</span><strong><span className="connection-status-dot" aria-hidden="true" />{t(reachable ? "Connected" : local?.reason === "unreachable" ? "Unreachable" : "Not confirmed")}</strong></div>
          <div><span>{t("Detected models")}</span><strong>{local?.models?.length ?? t("Not collected")}</strong></div>
          <div><span>{t("Answer models")}</span><strong>{answerCount ?? t("Not collected")}</strong></div>
        </div>
        <p className="helper" role="status">{t(localEngineStatus(local))}</p>
        <p className="helper">{t("Last checked")}: {checked && Number.isFinite(Date.parse(checked)) ? new Date(checked).toLocaleString(locale) : t("Not collected")}</p>
        <details className="connection-technical"><summary>{t("Connection details")}</summary><dl className="connection-facts"><div><dt>{t("Configuration source")}</dt><dd>{t(CONNECTION_SOURCES[connection.source])}</dd></div><div><dt>{t("Active address")}</dt><dd><code>{connection.base_url ?? t("Disconnected")}</code></dd></div><div><dt>{t("Default address")}</dt><dd><code>{connection.initial_base_url}</code></dd></div></dl>{connection.error && <p>{connection.error}</p>}</details>
      </section>
      <section className="connection-model-section" aria-labelledby="connection-models-title"><h3 id="connection-models-title">{t("Installed models and roles")}</h3><p className="helper">{t("Choose an answer model above the conversation input. Connecting a server does not change the embedding provider.")}</p>
        {local?.models?.length ? <ul className="connection-models">{local.models.map((model) => <li key={model.name}><code>{model.name}</code><span className={model.selectable ? "model-usable" : ""}>{t(model.selectable ? "Available for answers" : "Unavailable for answers")}</span></li>)}</ul> : <p className="helper">{t("No models detected. Check the server connection and installed models.")}</p>}
      </section>
    </>}
    <details className="connection-cli-help"><summary>{t("Diagnose from the terminal")}</summary><p className="helper">{t("Run these commands in the repository terminal. They inspect the current app and Ollama connection without changing services or models.")}</p><CodeBlock code={DIAGNOSE_COMMAND} language="bash" html={`<pre><code>${DIAGNOSE_COMMAND}</code></pre>`} /><a href={guideHref} target="_blank" rel="noopener noreferrer">{t("Ollama setup and recovery guide")}<ExternalLink size={14} aria-hidden="true" /></a></details>
  </div>;
}
