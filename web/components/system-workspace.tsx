"use client";
import { useI18n } from "@/lib/i18n";


import { Activity, Beaker, Braces, Database, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { RetainedPanel } from "@/components/retained-panel";
import { DevelopmentBadge } from "@/components/development-badge";
import { Metric } from "@/components/metric";
import { useNotifications } from "@/components/notifications";
import { DesktopJobNotifications, RuntimeSettings } from "@/components/runtime-settings";
import { Operations } from "@/components/operations";
import { SystemStatus } from "@/components/system-status";
import { apiBase, getProviderUsage } from "@/lib/api";
import { presentationFetch } from "@/lib/production-preview";
import { loadExperimentDefaults } from "@/lib/storage";
import type { EvaluationRequest, ProviderUsage, Readiness } from "@/lib/types";
import { DEFAULT_PROFILE } from "@/lib/types";

export type SystemTab = "status" | "operations" | "api" | "usage";

export interface SystemWorkspaceProps {
  live: boolean;
  /** Runtime is healthy; raw administrator requests stay disabled while the API is down or degraded. */
  ready?: boolean;
  readiness: Readiness | null;
  localModel?: string | null;
  localAllowed?: boolean;
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
  providers: [],
  estimated_input_tokens: 0,
  unreported_input_requests: 0,
  unreported_cost_requests: 0,
};

/** A complete `EvaluationRequest` the operator can edit before posting it raw. */
function sampleEvaluationRequest(): EvaluationRequest {
  const defaults = loadExperimentDefaults();
  return {
    suite_id: defaults.suite_id,
    golden_revision_id: defaults.golden_revision_id,
    mode: defaults.mode,
    profile: DEFAULT_PROFILE,
    target_tokens: [1024, 2048],
    strategies: ["lexical", "vector", "hybrid"],
    lexical_rankers: ["ts_rank_cd", "bm25"],
  };
}

export function SystemWorkspace({ live, ready = true, readiness, localModel, localAllowed = false, checking, onRefresh, operationsAvailable, tab, onTabChange }: SystemWorkspaceProps) {
  const { t, locale } = useI18n();
  const tabs: Array<[SystemTab, string]> = [["status", "System status"]];
  if (live && operationsAvailable) tabs.push(["operations", "Operations"]);
  if (live) tabs.push(["api", "API inspector"], ["usage", "Usage"]);
  const activeTab: SystemTab = tabs.some(([id]) => id === tab) ? tab : "status";

  return (
    <section className="lab-shell system-workspace">
      <header className="page-heading">
        <div><p className="eyebrow">{t("System")}</p><h1>{t("Runtime readiness")}</h1></div>
        <div className="page-badges">
          {activeTab === "status" && <button className="button" type="button" disabled={checking} onClick={onRefresh}><RefreshCw size={15} /> {checking ? t("Checking…") : t("Refresh")}</button>}
          <Link href={`/docs/${locale}/`} className="button" data-tour="documentation">{t("User guide")}</Link>
        </div>
      </header>
      <nav className="lab-tabs" aria-label={t("System sections")}>
        {tabs.map(([id, label]) => (
          <button key={id} type="button" aria-pressed={activeTab === id} title={id !== "status" ? locale === "ko" ? "개발 모드 전용" : "DEV only" : undefined} data-tour={id === "operations" ? "operations" : undefined} onClick={() => onTabChange(id)}>{t(label)}{id !== "status" && <span aria-hidden="true"><DevelopmentBadge locale={locale} compact /></span>}</button>
        ))}
      </nav>

      <RetainedPanel active={activeTab === "status"}><SystemStatus readiness={readiness} localModel={localModel} localAllowed={localAllowed} loading={checking} error="" onRefresh={onRefresh} embedded helpId="system.status" /><RuntimeSettings readiness={readiness} live={live} /></RetainedPanel>
      {live && <RetainedPanel active={activeTab === "operations"}><DesktopJobNotifications />{operationsAvailable ? <Operations embedded helpId="system.operations" /> : <p className="helper">{t("Start rag-dev to connect Local Operations.")}</p>}</RetainedPanel>}
      {live && <RetainedPanel active={activeTab === "api"}><ApiInspector ready={ready} /></RetainedPanel>}
      {live && <RetainedPanel active={activeTab === "usage"}><UsagePanel /></RetainedPanel>}
    </section>
  );
}

function ApiInspector({ ready }: { ready: boolean }) {
  const { t, locale } = useI18n();
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
      const response = await presentationFetch(`${apiBase()}/admin/evaluations/runs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload: unknown = await response.json();
      setRawResponse(JSON.stringify(payload, null, 2));
      if (!response.ok) notify(t("The API rejected this request."), "error", "raw-request");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("Invalid JSON request."), "error", "raw-request");
    }
  }

  return (
    <div className="api-inspector" data-help="system.api">
      <section>
        <h2>{t("Request")}</h2>
        <textarea aria-label={t("API request body")} value={rawRequest} onChange={(event) => setRawRequest(event.target.value)} spellCheck={false} />
        <button className="button primary" type="button" disabled={!ready} onClick={() => void sendRawRequest()}><Braces size={15} />{t("Send to API")}</button>
        {!ready && <p className="notice" role="status">{t("Corpus not ready. Inspect the earliest verified prerequisite.")}</p>}
      </section>
      <section>
        <h2>{t("Response")}</h2>
        <pre>{rawResponse || t("The typed API response will appear here.")}</pre>
      </section>
    </div>
  );
}

const USAGE_ROLE_LABELS: Record<string, string> = { gate: "Classification", route: "Routing", retrieve: "Retrieval", chat: "Answer", grade: "Grading", check: "Checking", report: "Answer", embedding: "Embedding" };

function UsagePanel() {
  const { t, locale } = useI18n();
  const [usage, setUsage] = useState<ProviderUsage>(EMPTY_USAGE);
  const [usageError, setUsageError] = useState<{ detail: string; appOwned: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProviderUsage()
      .then((value) => { if (!cancelled) { setUsage(value); setUsageError(null); } })
      .catch((reason: unknown) => { if (!cancelled) setUsageError({ detail: reason instanceof Error ? reason.message : "Usage could not be loaded.", appOwned: !(reason instanceof Error) }); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="panel-stack" data-help="system.usage">
      {usageError && <div className="notice error" role="alert">{usageError.appOwned ? t(usageError.detail) : usageError.detail}</div>}
      <div className="metric-grid">
        <Metric icon={<Activity />} label={t("Runs")} value={usage.runs.toLocaleString(locale)} />
        <Metric icon={<Braces />} label={t("Requests")} value={usage.requests.toLocaleString(locale)} />
        <Metric icon={<Database />} label={t("Reported input")} value={usage.input_tokens.toLocaleString(locale)} />
        <Metric icon={<Beaker />} label={t("Estimated cost")} value={`$${usage.estimated_cost_usd}`} />
      </div>
      <section className="surface table-wrap usage-table">
        <h2>{t("Recorded model usage")}</h2>
        <p className="helper">{t("Recorded review calls and embedding backfills only. This does not query provider account billing.")}</p>
        <p className="helper">{t("Reported tokens and tokenizer estimates are shown separately. Unknown usage is excluded from numeric totals.")}</p>
        {(usage.providers?.length ? usage.providers : usage.models.length ? [{ ...usage, provider: "unknown", local: null, credential_slot: "unknown" }] : []).map((group) => (
          <section key={`${group.provider}:${group.local}:${group.credential_slot}`} aria-label={`${group.provider} · ${group.credential_slot}`}>
            <h3>{group.provider} · {t(group.local === true ? "Local · free" : group.local === false ? "External API" : "Unknown provider location")} · {group.credential_slot === "unknown" ? t("Unknown credential slot") : group.credential_slot === "none" ? t("No credential") : group.credential_slot}</h3>
            <table><thead><tr><th>{t("Role")}</th><th>{t("Model")}</th><th>{t("Requests")}</th><th>{t("Reported input")}</th><th>{t("Estimated input")}</th><th>{t("Cached")}</th><th>{t("Cache write")}</th><th>{t("Output")}</th><th>{t("Reasoning")}</th><th>{t("Estimated USD")}</th></tr></thead><tbody>
              {group.models.map((model, index) => <tr key={`${model.model_name}:${model.role}:${index}`}><td>{t(USAGE_ROLE_LABELS[model.role] || "Unknown role")}</td><td>{model.model_name}</td><td>{model.requests.toLocaleString(locale)}</td><td>{model.input_tokens.toLocaleString(locale)}{(model.unreported_input_requests ?? 0) > 0 && <small> · {t("Not reported: {count}", { count: model.unreported_input_requests })}</small>}</td><td>{(model.estimated_input_tokens ?? 0).toLocaleString(locale)}</td><td>{model.cached_input_tokens.toLocaleString(locale)}</td><td>{model.cache_write_input_tokens.toLocaleString(locale)}</td><td>{model.output_tokens.toLocaleString(locale)}</td><td>{model.reasoning_tokens.toLocaleString(locale)}</td><td>${model.estimated_cost_usd}{(model.unreported_cost_requests ?? 0) > 0 && <small> · {t("Incomplete estimate")}</small>}</td></tr>)}
            </tbody><tfoot><tr><th colSpan={2}>{t("Provider subtotal")}</th><td>{group.requests.toLocaleString(locale)}</td><td>{group.input_tokens.toLocaleString(locale)}</td><td>{(group.estimated_input_tokens ?? 0).toLocaleString(locale)}</td><td>{group.cached_input_tokens.toLocaleString(locale)}</td><td>{group.cache_write_input_tokens.toLocaleString(locale)}</td><td>{group.output_tokens.toLocaleString(locale)}</td><td>{group.reasoning_tokens.toLocaleString(locale)}</td><td>${group.estimated_cost_usd}</td></tr></tfoot></table>
            {(group.unreported_cost_requests ?? 0) > 0 && <p className="helper">{t("Cost was not reported for {count} requests; this subtotal is incomplete.", { count: group.unreported_cost_requests })}</p>}
          </section>
        ))}
        {!usage.models.length && <p className="helper">{t("No persisted model usage yet.")}</p>}
        {usage.latest_run_at && <p className="helper">{t("Latest run:")}{" "}{new Date(usage.latest_run_at).toLocaleString(locale)}</p>}
      </section>
    </div>
  );
}
