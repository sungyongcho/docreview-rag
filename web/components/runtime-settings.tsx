"use client";

import { useEffect, useState } from "react";
import { apiBase, getReleaseLimits } from "@/lib/api";
import { operatorBase } from "@/lib/operator-api";
import { desktopJobNotificationsEnabled, setDesktopJobNotifications } from "@/lib/storage";
import { useNotifications } from "@/components/notifications";
import type { Readiness, ReleaseLimits } from "@/lib/types";

/** Show environment details for development and read-only allowances for deployment. */
export function RuntimeSettings({ readiness, live }: { readiness: Readiness | null; live: boolean }) {
  const { notify } = useNotifications();
  const [limits, setLimits] = useState<ReleaseLimits | null>(null);
  useEffect(() => { if (!live) void getReleaseLimits().then(setLimits).catch((reason) => notify(String(reason), "error", "limits")); }, [live, notify]);
  const apiEndpoint = typeof window === "undefined" ? "Loading…" : new URL(apiBase() || "/", window.location.origin).toString().replace(/\/$/, "");
  const databaseEndpoint = process.env.NEXT_PUBLIC_DB_ENDPOINT || "Server-side connection · credentials hidden";
  const operationsEndpoint = operatorBase() || "Not configured in this build";
  const embeddingModel = readiness?.models.embedding;
  return <section className="surface" data-help="system.runtime"><h2>{live ? "Local runtime" : "Limits & availability"}</h2>{live ? <div className="settings-metrics"><Metric label="Mode" value={readiness?.environment?.toUpperCase() ?? "Unknown"} /><Metric label="API URL" value={apiEndpoint} /><Metric label="Database endpoint" value={databaseEndpoint} />{readiness?.environment === "dev" && <Metric label="Operations URL" value={operationsEndpoint} />}<Metric label="Database" value={String(readiness?.corpus?.database_connected ?? "Unknown")} /><Metric label="Schema" value={readiness?.corpus?.schema_status ?? "Unknown"} /><Metric label="Index readiness" value={`${(readiness?.corpus?.embedded_chunks ?? 0).toLocaleString()} / ${(readiness?.corpus?.chunks ?? 0).toLocaleString()} embedded · BM25 ${readiness?.corpus?.bm25_ready ? "ready" : "not ready"}`} /><Metric label="Review model" value={readiness?.active_review_model ?? "Not configured"} /><Metric label="Embedding model" value={embeddingModel ? `${embeddingModel.default} · ${embeddingModel.dimensions ?? "default"} dimensions` : "Unknown"} /><p className="helper">{readiness?.environment === "dev" ? "Manage the model-server connection in Settings › Local LLM. Database and API credentials stay server-side." : "Database and API credentials stay server-side."}</p></div> : <div className="settings-metrics"><Metric label="Mode" value={readiness?.environment?.toUpperCase() ?? "Unknown"} /><Metric label="Review" value={readiness?.review_enabled ? "Enabled" : "Disabled"} /><Metric label="Active model" value={readiness?.active_review_model ?? "Unavailable"} /><Metric label="Minute allowance" value={limits ? `${limits.remaining_minute} / ${limits.per_minute} · reset ${formatSeconds(limits.minute_reset_seconds)}` : "Loading…"} /><Metric label="Rolling day" value={limits ? `${limits.remaining_day} / ${limits.per_day} · reset ${formatSeconds(limits.day_reset_seconds)}` : "Loading…"} /><Metric label="Retry availability" value={limits?.retry_after_seconds ? formatSeconds(limits.retry_after_seconds) : "Available now"} /><Metric label="Input token ceiling" value={limits ? limits.max_input_tokens.toLocaleString() : "Loading…"} /><Metric label="Output token ceiling" value={limits ? limits.max_output_tokens.toLocaleString() : "Loading…"} /><Metric label="Per-request cost" value={limits ? `$${limits.max_cost_usd}` : "Loading…"} /><Metric label="Daily cost remaining" value={limits ? `$${limits.remaining_daily_cost_usd} / $${limits.daily_cost_usd}` : "Loading…"} /><Metric label="UTC cost reset" value={limits ? new Date(limits.daily_cost_reset_at_utc).toLocaleString() : "Loading…"} /><p className="helper">Limits apply to this single service process. Administrator operations are restricted in this deployment.</p></div>}</section>;
}

/** Request browser permission only when the user enables completion notifications. */
export function DesktopJobNotifications() {
  const { notify } = useNotifications();
  const [desktopNotifications, setDesktopNotifications] = useState(false);
  useEffect(() => setDesktopNotifications(desktopJobNotificationsEnabled()), []);
  async function toggleDesktopNotifications() {
    if (desktopNotifications) {
      setDesktopJobNotifications(false);
      setDesktopNotifications(false);
      notify("Desktop job notifications disabled.", "success", "desktop-notifications");
      return;
    }
    if (typeof Notification === "undefined") {
      notify("This browser does not support desktop notifications.", "warning", "desktop-notifications");
      return;
    }
    const permission = await Notification.requestPermission();
    const enabled = permission === "granted";
    setDesktopJobNotifications(enabled);
    setDesktopNotifications(enabled);
    notify(
      enabled ? "Desktop job notifications enabled." : "Desktop notification permission was not granted.",
      enabled ? "success" : "warning",
      "desktop-notifications",
    );
  }

  return <section className="surface"><h2>Job notifications</h2><Metric label="Desktop job notifications" value={desktopNotifications ? "Enabled" : typeof Notification !== "undefined" && Notification.permission === "denied" ? "Blocked by browser" : "Disabled"} /><button className="button" type="button" onClick={() => void toggleDesktopNotifications()}>{desktopNotifications ? "Disable desktop job notifications" : "Enable desktop job notifications"}</button></section>;
}
function formatSeconds(value: number): string { if (value <= 0) return "now"; const hours = Math.floor(value / 3600); const minutes = Math.floor(value % 3600 / 60); const seconds = value % 60; return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds}s` : `${seconds}s`; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="setting-metric"><span>{label}</span><strong>{value}</strong></div>; }
