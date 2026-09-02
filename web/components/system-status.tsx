import { RefreshCw } from "lucide-react";

import type { Readiness } from "@/lib/types";

interface SystemStatusProps {
  readiness: Readiness | null;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  /** Inside the System workspace the host owns the page heading and the Refresh button. */
  embedded?: boolean;
}

function value(value: unknown) {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function SystemStatus({ readiness, loading, error, onRefresh, embedded = false }: SystemStatusProps) {
  const corpus = readiness?.corpus;
  const models = readiness?.models ?? {};
  return (
    <section className={embedded ? "status-page embedded" : "status-page"}>
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
      </div>
    </section>
  );
}
