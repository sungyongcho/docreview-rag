import { RefreshCw } from "lucide-react";

import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import type { Readiness, ReviewEngineState } from "@/lib/types";

interface SystemStatusProps {
  readiness: Readiness | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  /** Inside the System workspace the host owns the page heading and the Refresh button. */
  embedded?: boolean;
  /** `data-help` topic id for Help mode. */
  helpId?: string;
}

function value(value: unknown) {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function SystemStatus({ readiness, loading, error, onRefresh, embedded = false, helpId }: SystemStatusProps) {
  const corpus = readiness?.corpus;
  const models = readiness?.models ?? {};
  return (
    <section className={embedded ? "status-page embedded" : "status-page"} data-help={helpId}>
      {!embedded && <div className="page-heading">
        <div><p className="eyebrow">System status</p><h1>Runtime readiness</h1></div>
        <button className="button" type="button" disabled={loading} onClick={onRefresh}>
          <RefreshCw size={15} /> {loading ? "Checking…" : "Refresh"}
        </button>
      </div>}
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="metric-grid status-metrics">
        <div className="metric"><span>Overall</span><strong>{readiness?.status ?? "Unknown"}</strong></div>
        <div className="metric"><span>Mode</span><strong>{readiness?.mode ?? "Unknown"}</strong></div>
        <div className="metric"><span>Database</span><strong>{value(corpus?.database_connected)}</strong></div>
        <div className="metric"><span>Schema</span><strong>{corpus?.schema_status ?? corpus?.availability ?? "Unknown"}</strong></div>
      </div>
      <div className="two-column status-columns">
        <section className="surface">
          <h2>Corpus</h2>
          <dl className="status-list">
            <div><dt>Availability</dt><dd>{corpus?.availability ?? "Unknown"}</dd></div>
            <div><dt>Documents</dt><dd>{value(corpus?.documents)}</dd></div>
            <div><dt>Chunks</dt><dd>{value(corpus?.chunks)}</dd></div>
            <div><dt>Embedded</dt><dd>{value(corpus?.embedded_chunks)}</dd></div>
            <div><dt>Pending embeddings</dt><dd>{value(corpus?.pending_embeddings)}</dd></div>
            <div><dt>BM25</dt><dd>{value(corpus?.bm25_ready)}</dd></div>
          </dl>
          {corpus?.schema_message && <p className="helper">{corpus.schema_message}</p>}
        </section>
        <section className="surface">
          <h2>OpenAI model policy</h2>
          <p className="helper">Revision {readiness?.policy_revision ?? "Unknown"}</p>
          <div className="policy-list">
            {Object.entries(models).map(([role, policy]) => (
              <div key={role}>
                <strong>{role}</strong>
                <span>{policy.default}</span>
                <small>{policy.reasoning_effort ? `reasoning ${policy.reasoning_effort}` : `${policy.dimensions ?? "?"} dimensions`}</small>
              </div>
            ))}
          </div>
          <p className="helper">Review capability: {readiness?.review_enabled ? readiness.active_review_model : "disabled"}</p>
        </section>
        {LOCAL_ENGINE_VISIBLE && <LocalModelPolicy readiness={readiness} />}
      </div>
    </section>
  );
}

/** Which roles the selected engine actually serves; a code-level fact, not a setting. */
const LOCAL_ROLES: ReadonlyArray<readonly [string, string]> = [
  ["review", "answers and citation checks"],
  ["routing", "query translation and scope"],
  ["intent", "review or conversation"],
  ["chat", "casual replies"],
];

/** Why the local engine is not serving, in the reader's terms rather than the API's. */
export function localEngineStatus(engine: ReviewEngineState | undefined): string {
  if (engine?.enabled) return `Reachable: ${engine.model ?? "configured"} over ${engine.protocol ?? "its protocol"}.`;
  switch (engine?.reason) {
    case "disabled_in_prod": return "Disabled because MODE=prod. A production build never answers from a local model.";
    case "model_unreachable_or_missing": return "The host did not report this model. Pull it, or check that the local-llm profile is up.";
    case "not_configured": return "Not configured. Set LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL to use one.";
    default: return "Not configured. Set LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL to use one.";
  }
}

function LocalModelPolicy({ readiness }: { readiness: Readiness | null }) {
  const local = readiness?.review_engines?.local;
  const model = local?.model ?? "—";
  const embedding = readiness?.models?.embedding?.default ?? "—";
  return (
    <section className="surface" data-help="system.local-policy">
      <h2>Local model policy</h2>
      <p className="helper">Not governed by the OpenAI model policy. The model is whatever LOCAL_LLM_MODEL names.</p>
      <div className="policy-list local-policy-list">
        {LOCAL_ROLES.map(([role, detail]) => (
          <div key={role}>
            <strong>{role}</strong>
            <span>{model}</span>
            <small>{detail}</small>
          </div>
        ))}
        <div className="policy-locked">
          <strong>embedding</strong>
          <span>{embedding}</span>
          <small>never local; vectors carry their embedding identity</small>
        </div>
      </div>
      <p className="helper">{localEngineStatus(local)}</p>
    </section>
  );
}
