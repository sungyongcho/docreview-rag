"use client";

import { useEffect, useRef, useState } from "react";
import { disconnectLocalLLM, getLocalLLMConnection, resetLocalLLMConnection, saveLocalLLMConnection } from "@/lib/api";
import type { LocalLLMConnection, Readiness, ReviewEngineState } from "@/lib/types";
import { localEngineStatus } from "@/lib/local-models";

/** Probe a server before saving it; failed changes leave the working connection intact. */
export function LocalConnectionSettings({ readiness, onChanged }: {
  readiness?: Readiness | null;
  onChanged?: (local: ReviewEngineState) => void;
}) {
  const [connection, setConnection] = useState<LocalLLMConnection | null>(null);
  const [url, setUrl] = useState("");
  const [protocol, setProtocol] = useState<LocalLLMConnection["protocol"]>("auto");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
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
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Connection settings could not be loaded.");
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { mounted.current = false; controller.abort(); };
  }, []);

  useEffect(() => {
    const local = readiness?.review_engines?.local;
    if (local) setConnection((current) => current ? { ...current, local } : current);
  }, [readiness]);

  async function change(action: "connect" | "disconnect" | "reset") {
    if (busy) return;
    setBusy(true);
    setError("");
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
      setError(`${detail} Your previous connection setting was kept.`);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <div className="settings-form local-connection-settings">
    <p className="helper">Connect a separately installed model server. Saved settings take priority over the initial environment configuration and apply immediately.</p>
    <label>Server URL<input type="url" value={url} placeholder="http://host.docker.internal:11434" disabled={busy} onChange={(event) => setUrl(event.target.value)} /></label>
    <label>Protocol<select value={protocol} disabled={busy} onChange={(event) => setProtocol(event.target.value as LocalLLMConnection["protocol"])}><option value="auto">Auto detect</option><option value="ollama">Ollama</option><option value="openai_responses">OpenAI Responses compatible</option></select></label>
    <div className="action-row"><button className="button primary" type="button" disabled={busy || !url.trim()} onClick={() => void change("connect")}>{busy ? "Checking…" : "Connect & save"}</button><button className="button" type="button" disabled={busy || !connection || connection.source === "disabled"} onClick={() => void change("disconnect")}>Disconnect</button><button className="button" type="button" disabled={busy || !connection} onClick={() => void change("reset")}>Reset to initial connection</button></div>
    {error && <p className="notice error" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    {connection && <>
      <dl className="status-list"><div><dt>Configuration source</dt><dd>{connection.source}</dd></div><div><dt>Active server</dt><dd>{connection.base_url ?? (connection.source === "disabled" ? "Disconnected" : "Unavailable")}</dd></div><div><dt>Initial server</dt><dd>{connection.initial_base_url}</dd></div></dl>
      <p className="helper" role="status">{localEngineStatus(connection.local)}</p>
      {connection.error && <p className="notice error" role="alert">{connection.error}</p>}
      <p className="helper">Models refresh every 30 seconds while the tab is visible. Choose an answer model below the conversation input.</p>
      {!!connection.local.models?.length && <ul>{connection.local.models.map((model) => <li key={model.name}>{model.name}{model.selectable ? "" : " · Unavailable for answers"}</li>)}</ul>}
    </>}
  </div>;
}
