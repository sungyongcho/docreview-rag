"use client";

import { Activity, Beaker, Braces, Database, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Metric } from "@/components/metric";
import { useNotifications } from "@/components/notifications";
import { Operations } from "@/components/operations";
import { SystemStatus } from "@/components/system-status";
import { apiBase, getProviderUsage } from "@/lib/api";
import { loadExperimentDefaults } from "@/lib/storage";
import type { EvaluationRequest, ProviderUsage, Readiness } from "@/lib/types";
import { DEFAULT_PROFILE } from "@/lib/types";

export type SystemTab = "status" | "operations" | "api" | "usage";

export interface SystemWorkspaceProps {
  live: boolean;
  /** Runtime is healthy; raw administrator requests stay disabled while the API is down or degraded. */
  ready?: boolean;
  readiness: Readiness | null;
  checking: boolean;
  onRefresh: () => void;
  operationsAvailable: boolean;
  tab: SystemTab;
  onTabChange: (tab: SystemTab) => void;
}

const EMPTY_USAGE: ProviderUsage = {
  runs: 0,
  requests: 0,
  input_tokens: 0,
  cached_input_tokens: 0,
  cache_write_input_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
  estimated_cost_usd: "0",
  latest_run_at: null,
  models: [],
};

/** A complete `EvaluationRequest` the operator can edit before posting it raw. */
function sampleEvaluationRequest(): EvaluationRequest {
  const defaults = loadExperimentDefaults();
  return {
    suite_id: defaults.suite_id,
    golden_revision_id: defaults.golden_revision_id,
    mode: defaults.mode,
    profile: DEFAULT_PROFILE,
    target_text_chars: [500, 1200],
    strategies: ["lexical", "vector", "hybrid"],
    lexical_rankers: ["ts_rank_cd", "bm25"],
  };
}

export function SystemWorkspace({ live, ready = true, readiness, checking, onRefresh, operationsAvailable, tab, onTabChange }: SystemWorkspaceProps) {
  const tabs: Array<[SystemTab, string]> = [["status", "System status"]];
  if (operationsAvailable) tabs.push(["operations", "Operations"]);
  if (live) tabs.push(["api", "API inspector"], ["usage", "Usage"]);
  const activeTab: SystemTab = tabs.some(([id]) => id === tab) ? tab : "status";

  return (
    <section className="lab-shell system-workspace">
      <header className="page-heading">
        <div><p className="eyebrow">System</p><h1>Runtime readiness</h1></div>
        <div className="page-badges">
          {activeTab === "status" && <button className="button" type="button" disabled={checking} onClick={onRefresh}><RefreshCw size={15} /> {checking ? "Checking…" : "Refresh"}</button>}
          <Link href="/docs/" target="_blank" rel="noreferrer" className="button" data-tour="documentation">Documentation</Link>
        </div>
      </header>
      <nav className="lab-tabs" aria-label="System sections">
        {tabs.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={activeTab === id} data-tour={id === "operations" ? "operations" : undefined} onClick={() => onTabChange(id)}>{label}</button>
        ))}
      </nav>

      {activeTab === "status" && <SystemStatus readiness={readiness} loading={checking} error="" onRefresh={onRefresh} embedded helpId="system.status" />}
      {activeTab === "operations" && operationsAvailable && <Operations embedded helpId="system.operations" />}
      {activeTab === "api" && live && <ApiInspector ready={ready} />}
      {activeTab === "usage" && live && <UsagePanel />}
    </section>
  );
}

function ApiInspector({ ready }: { ready: boolean }) {
  const { notify } = useNotifications();
  const [rawRequest, setRawRequest] = useState("");
  const [rawResponse, setRawResponse] = useState("");

  // Stored experiment defaults live in localStorage, so the prefill waits for the client.
  useEffect(() => {
    setRawRequest(JSON.stringify(sampleEvaluationRequest(), null, 2));
  }, []);

  async function sendRawRequest() {
    try {
      const body = JSON.parse(rawRequest) as Record<string, unknown>;
      const response = await fetch(`${apiBase()}/admin/evaluations/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload: unknown = await response.json();
      setRawResponse(JSON.stringify(payload, null, 2));
      if (!response.ok) notify("The API rejected this request.", "error", "raw-request");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Invalid JSON request.", "error", "raw-request");
    }
  }

  return (
    <div className="api-inspector" data-help="system.api">
      <section>
        <h2>Request</h2>
        <textarea aria-label="API request body" value={rawRequest} onChange={(event) => setRawRequest(event.target.value)} spellCheck={false} />
        <button className="button primary" type="button" disabled={!ready} onClick={() => void sendRawRequest()}><Braces size={15} /> Send to API</button>
      </section>
      <section>
        <h2>Response</h2>
        <pre>{rawResponse || "The typed API response will appear here."}</pre>
      </section>
    </div>
  );
}

function UsagePanel() {
  const [usage, setUsage] = useState<ProviderUsage>(EMPTY_USAGE);
  const [usageError, setUsageError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getProviderUsage()
      .then((value) => { if (!cancelled) { setUsage(value); setUsageError(""); } })
      .catch((reason: unknown) => { if (!cancelled) setUsageError(reason instanceof Error ? reason.message : "Usage could not be loaded."); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="panel-stack" data-help="system.usage">
      {usageError && <div className="notice error" role="alert">{usageError}</div>}
      <div className="metric-grid">
        <Metric icon={<Activity />} label="Runs" value={String(usage.runs)} />
        <Metric icon={<Braces />} label="Requests" value={String(usage.requests)} />
        <Metric icon={<Database />} label="Input tokens" value={usage.input_tokens.toLocaleString()} />
        <Metric icon={<Beaker />} label="Estimated cost" value={`$${usage.estimated_cost_usd}`} />
      </div>
      <section className="surface table-wrap usage-table">
        <h2>Recorded model usage</h2>
        <p className="helper">Local application traces only. This does not query OpenAI account billing.</p>
        <table><thead><tr><th>Model</th><th>Requests</th><th>Input</th><th>Cached</th><th>Cache write</th><th>Output</th><th>Reasoning</th><th>Estimated USD</th></tr></thead><tbody>
          {usage.models.map((model) => <tr key={model.model_name}><td>{model.model_name}</td><td>{model.requests}</td><td>{model.input_tokens.toLocaleString()}</td><td>{model.cached_input_tokens.toLocaleString()}</td><td>{model.cache_write_input_tokens.toLocaleString()}</td><td>{model.output_tokens.toLocaleString()}</td><td>{model.reasoning_tokens.toLocaleString()}</td><td>${model.estimated_cost_usd}</td></tr>)}
        </tbody></table>
        {!usage.models.length && <p className="helper">No persisted provider traces yet.</p>}
        {usage.latest_run_at && <p className="helper">Latest run: {new Date(usage.latest_run_at).toLocaleString()}</p>}
      </section>
    </div>
  );
}
