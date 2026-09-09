"use client";
import { notificationErrorDetail, notificationErrorMessage } from "@/lib/notification-registry";
import { useI18n } from "@/lib/i18n";
import { UsageAvailabilityDashboard } from "./usage-availability-dashboard";
import { DevelopmentBadge } from "@/components/development-badge";


import { useEffect, useState } from "react";
import { apiBase, getReleaseLimits } from "@/lib/api";
import { operatorBase } from "@/lib/operator-api";
import { desktopJobNotificationsEnabled, setDesktopJobNotifications } from "@/lib/storage";
import { useNotifications } from "@/components/notifications";
import type { Readiness, ReleaseLimits } from "@/lib/types";

/** Show environment details for development and read-only allowances for deployment. */
export function RuntimeSettings({ readiness, live }: { readiness: Readiness | null; live: boolean }) {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [limits, setLimits] = useState<ReleaseLimits | null>(null);
  useEffect(() => {
    if (live) return;
    let active = true;
    const refresh = () => void getReleaseLimits().then(value => { if (active) setLimits(value); }).catch(reason => {
      if (!active) return;
      setLimits(null);
      notify(reason instanceof Error ? notificationErrorMessage(reason) : String(reason), "error", "limits", undefined, { event: "limits-error", detail: notificationErrorDetail(reason) });
    });
    refresh();
    const timer = window.setInterval(refresh, 60000);
    window.addEventListener("focus", refresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [live, notify]);
  const apiEndpoint = typeof window === "undefined" ? t("Loading…") : new URL(apiBase() || "/", window.location.origin).toString().replace(/\/$/, "");
  const databaseEndpoint = process.env.NEXT_PUBLIC_DB_ENDPOINT || t("Server-side connection · credentials hidden");
  const operationsEndpoint = operatorBase() || t("Not configured in this build");
  const embeddingModel = readiness?.models.embedding;
  return <section className="surface" data-help="system.runtime">{live ? <div className="surface-title"><h2>{t("Local runtime")}</h2><DevelopmentBadge locale={locale} compact /></div> : <h2>{t("Limits & availability")}</h2>}{live ? <div className="settings-metrics"><Metric label={t("Mode")} value={readiness?.environment?.toUpperCase() ?? t("Unknown")} /><Metric label={t("API URL")} value={apiEndpoint} /><Metric label={t("Database endpoint")} value={databaseEndpoint} />{readiness?.environment === "dev" && <Metric label={t("Operations URL")} value={operationsEndpoint} />}<Metric label={t("Database")} value={readiness?.corpus?.database_connected === true ? t("Connected") : readiness?.corpus?.database_connected === false ? t("Not connected") : t("Unknown")} /><Metric label={t("Schema")} value={t(readiness?.corpus?.schema_status ?? "Unknown")} /><Metric label={t("Index readiness")} value={t("{p0} / {p1} embedded · BM25 {p2}", { p0: (readiness?.corpus?.embedded_chunks ?? 0).toLocaleString(locale), p1: (readiness?.corpus?.chunks ?? 0).toLocaleString(locale), p2: t(readiness?.corpus?.bm25_ready ? "ready" : "not ready") })} /><Metric label={t("Review model")} value={readiness?.active_review_model ?? t("Not configured")} /><Metric label={t("Embedding model")} value={embeddingModel ? t("{p0} · {p1} dimensions", { p0: embeddingModel.default, p1: embeddingModel.dimensions ?? t("default") }) : t("Unknown")} /><p className="helper">{readiness?.environment === "dev" ? t("Manage the model-server connection in Settings › Local LLM. Database and API credentials stay server-side.") : t("Database and API credentials stay server-side.")}</p></div> : <UsageAvailabilityDashboard limits={limits} readiness={readiness} />}</section>;
}

/** Request browser permission only when the user enables completion notifications. */
export function DesktopJobNotifications() {
  const { t, locale } = useI18n();
  const { notify } = useNotifications();
  const [desktopNotifications, setDesktopNotifications] = useState(false);
  useEffect(() => setDesktopNotifications(desktopJobNotificationsEnabled()), []);
  async function toggleDesktopNotifications() {
    if (desktopNotifications) {
      setDesktopJobNotifications(false);
      setDesktopNotifications(false);
      notify(t("Desktop job notifications disabled."), "success", "desktop-notifications", undefined, { event: "desktop-notifications-notice" });
      return;
    }
    if (typeof Notification === "undefined") {
      notify(t("This browser does not support desktop notifications."), "warning", "desktop-notifications", undefined, { event: "desktop-notifications-warning" });
      return;
    }
    const permission = await Notification.requestPermission();
    const enabled = permission === "granted";
    setDesktopJobNotifications(enabled);
    setDesktopNotifications(enabled);
    notify(enabled ? t("Desktop job notifications enabled.") : t("Desktop notification permission was not granted."), enabled ? "success" : "warning", "desktop-notifications", undefined, { event: "desktop-notifications-notice" });
  }

  return <section className="surface job-notifications"><div className="surface-title"><h2>{t("Job notifications")}</h2></div><div className="job-notifications-row"><div className="job-notifications-state"><span className="helper">{t("Desktop job notifications")}</span><strong>{t(desktopNotifications ? "Enabled" : typeof Notification !== "undefined" && Notification.permission === "denied" ? "Blocked by browser" : "Disabled")}</strong></div><button className="button" type="button" onClick={() => void toggleDesktopNotifications()}>{desktopNotifications ? t("Disable desktop job notifications") : t("Enable desktop job notifications")}</button></div></section>;
}
function formatSeconds(value: number, locale: "ko" | "en"): string { if (value <= 0) return locale === "ko" ? "지금" : "now"; const hours = Math.floor(value / 3600); const minutes = Math.floor(value % 3600 / 60); const seconds = value % 60; if (locale === "ko") return hours ? `${hours}시간 ${minutes}분` : minutes ? `${minutes}분 ${seconds}초` : `${seconds}초`; return hours ? `${hours}h ${minutes}m` : minutes ? `${minutes}m ${seconds}s` : `${seconds}s`; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="setting-metric"><span>{label}</span><strong>{value}</strong></div>; }
