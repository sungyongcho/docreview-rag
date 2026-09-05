"use client";
import { useI18n } from "@/lib/i18n";
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

function value(value: unknown, locale: string) {
  if (value === null || value === undefined || value === "") return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString(locale);
  return String(value);
}

export function SystemStatus({ readiness, localModel, localAllowed = false, loading, error, onRefresh, embedded = false, helpId }: SystemStatusProps) {
  const { t, locale } = useI18n();
  const corpus = readiness?.corpus;
  const models = readiness?.models ?? {};
  return (
    <section className={embedded ? "status-page embedded" : "status-page"} data-help={helpId}>
      {!embedded && <div className="page-heading">
        <div><p className="eyebrow">{t("System status")}</p><h1>{t("Runtime readiness")}</h1></div>
        <button className="button" type="button" disabled={loading} onClick={onRefresh}>
          <RefreshCw size={15} /> {loading ? t("Checking…") : t("Refresh")}
        </button>
      </div>}
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="metric-grid status-metrics">
        <div className="metric"><span>{t("Overall")}</span><strong>{t(readiness?.status ?? "Unknown")}</strong></div>
        <div className="metric"><span>{t("Mode")}</span><strong>{readiness?.environment?.toUpperCase() ?? t("Unknown")}</strong></div>
        <div className="metric"><span>{t("Database")}</span><strong>{t(corpus?.database_connected === true ? "Connected" : corpus?.database_connected === false ? "Not connected" : "Unknown")}</strong></div>
        <div className="metric"><span>{t("Schema")}</span><strong>{t(corpus?.schema_status ?? corpus?.availability ?? "Unknown")}</strong></div>
      </div>
      <div className="two-column status-columns">
        <section className="surface">
          <h2>{t("Corpus")}</h2>
          <dl className="status-list">
            <div><dt>{t("Availability")}</dt><dd>{t(corpus?.availability ?? "Unknown")}</dd></div>
            <div><dt>{t("Documents")}</dt><dd>{t(value(corpus?.documents, locale))}</dd></div>
            <div><dt>{t("Chunks")}</dt><dd>{t(value(corpus?.chunks, locale))}</dd></div>
            <div><dt>{t("Embedded")}</dt><dd>{t(value(corpus?.embedded_chunks, locale))}</dd></div>
            <div><dt>{t("Pending embeddings")}</dt><dd>{t(value(corpus?.pending_embeddings, locale))}</dd></div>
            <div><dt>{t("BM25")}</dt><dd>{t(corpus?.bm25_ready === true ? "ready" : corpus?.bm25_ready === false ? "not ready" : "Unknown")}</dd></div>
          </dl>
          {corpus?.schema_message && <p className="helper">{t("Schema details:")}{" "}{corpus.schema_message}</p>}
        </section>
        <section className="surface">
          <h2>{t("OpenAI model policy")}</h2>
          <p className="helper">{t("Revision")}{" "}{readiness?.policy_revision ?? t("Unknown")}</p>
          <div className="policy-list">
            {Object.entries(models).map(([role, policy]) => (
              <div key={role}>
                <strong>{t(role)}</strong>
                <span>{policy.default}</span>
                <small>{policy.reasoning_effort ? t("reasoning {p0}", { p0: t(policy.reasoning_effort) }) : t("{p0} dimensions", { p0: policy.dimensions?.toLocaleString(locale) ?? "?" })}</small>
              </div>
            ))}
          </div>
          <p className="helper">{t("Review capability:")}{" "}{readiness?.review_enabled ? readiness.active_review_model : t("disabled")}</p>
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
  const { t, locale } = useI18n();
  const local = readiness?.review_engines?.local;
  const unavailable = selected && (!local?.enabled || !local.models?.some((item) => item.name === selected && item.selectable));
  const model = unavailable ? `${selected} ${t("(Unavailable)")}` : selected ?? local?.model ?? t(local?.enabled ? "Select a model" : "Unavailable");
  const embedding = readiness?.models?.embedding?.default ?? "—";
  return (
    <section className="surface local-policy" data-help="system.local-policy">
      <h2>{t("Local model policy")}</h2>
      <p className="helper">{t("The selected local model serves these roles when the conversation uses Local LLM.")}</p>
      <p className="helper" role="status">{t(localEngineStatus(local))}</p>
      {local?.checked_at && <p className="helper">{t("Last checked:")}{" "}{new Date(local.checked_at).toLocaleTimeString(locale === "ko" ? "ko-KR" : "en-US")}</p>}
      <div className="local-policy-columns"><div><h3>{t("Model roles")}</h3><div className="policy-list local-policy-list">
        {LOCAL_ROLES.map(([role, detail]) => (
          <div key={role}>
            <strong>{t(role)}</strong>
            <span>{model}</span>
            <small>{t(detail)}</small>
          </div>
        ))}
        <div className="policy-locked">
          <strong>{t("embedding")}</strong>
          <span>{embedding}</span>
          <small>{t("never local; vectors carry their embedding identity")}</small>
        </div>
      </div>
      </div>{!!local?.models?.length && <div>
        <h3>{t("Installed models")}</h3>
        <div className="policy-list local-policy-list local-model-inventory">
          {local.models.map((item) => <div key={item.name}>
            <strong>{item.name}</strong>
            <span>{item.size_bytes === null ? t("Size not provided") : t("{p0} GB", { p0: (item.size_bytes / 1_000_000_000).toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) })}</span>
            <small>{[item.family, item.parameter_size, item.quantization_level].filter(Boolean).join(" · ") || t("Details not provided")}<br />
              {item.capabilities?.join(" · ") ?? t("Capabilities not provided")}<br />
              {item.loaded === null ? t("Load state not provided") : item.loaded ? t("Loaded") : t("Not loaded")}
              {item.selectable ? item.capabilities === null ? t(" · Selectable; verify server support") : t(" · Answer model") : t(" · Not available for answers")}
            </small>
          </div>)}
        </div>
      </div>}</div>
    </section>
  );
}
