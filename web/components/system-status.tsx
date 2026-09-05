import { RefreshCw } from "lucide-react";

import { LOCAL_ENGINE_VISIBLE } from "@/lib/build-mode";
import { localEngineStatus } from "@/lib/local-models";
import type { Readiness } from "@/lib/types";

interface SystemStatusProps {
  readiness: Readiness | null;
  localModel?: string | null;
  localAllowed?: boolean;
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

export function SystemStatus({ readiness, localModel, localAllowed = false, loading, error, onRefresh, embedded = false, helpId }: SystemStatusProps) {
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
        <div className="metric"><span>Mode</span><strong>{readiness?.environment?.toUpperCase() ?? "Unknown"}</strong></div>
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
        {LOCAL_ENGINE_VISIBLE && localAllowed && readiness?.environment === "dev" && <LocalModelPolicy readiness={readiness} selected={localModel} />}
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

function LocalModelPolicy({ readiness, selected }: { readiness: Readiness | null; selected?: string | null }) {
  const local = readiness?.review_engines?.local;
  const unavailable = selected && (!local?.enabled || !local.models?.some((item) => item.name === selected && item.selectable));
  const model = unavailable ? `${selected} (Unavailable)` : selected ?? local?.model ?? (local?.enabled ? "Select a model" : "Unavailable");
  const embedding = readiness?.models?.embedding?.default ?? "—";
  return (
    <section className="surface" data-help="system.local-policy">
      <h2>Local model policy</h2>
      <p className="helper">The selected local model serves these roles when the conversation uses Local LLM.</p>
      <p className="helper" role="status">{localEngineStatus(local)}</p>
      {local?.checked_at && <p className="helper">Last checked: {new Date(local.checked_at).toLocaleTimeString()}</p>}
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
      {!!local?.models?.length && <>
        <h3>Installed models</h3>
        <div className="policy-list local-policy-list local-model-inventory">
          {local.models.map((item) => <div key={item.name}>
            <strong>{item.name}</strong>
            <span>{item.size_bytes === null ? "Size not provided" : `${(item.size_bytes / 1_000_000_000).toFixed(2)} GB`}</span>
            <small>{[item.family, item.parameter_size, item.quantization_level].filter(Boolean).join(" · ") || "Details not provided"}<br />
              {item.capabilities?.join(" · ") ?? "Capabilities not provided"}<br />
              {item.loaded === null ? "Load state not provided" : item.loaded ? "Loaded" : "Not loaded"}
              {item.selectable ? item.capabilities === null ? " · Selectable; verify server support" : " · Answer model" : " · Not available for answers"}
            </small>
          </div>)}
        </div>
      </>}
    </section>
  );
}
