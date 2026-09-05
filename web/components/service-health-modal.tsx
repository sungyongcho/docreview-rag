"use client";
import { useI18n } from "@/lib/i18n";
import { DatabaseZap, RefreshCw, RotateCw, ServerCrash, X } from "lucide-react";

import type { RuntimeHealthKind } from "@/lib/use-runtime-health";

interface ServiceHealthModalProps {
  kind: RuntimeHealthKind;
  visible: boolean;
  checking: boolean;
  onRetry: () => void;
  onReload: () => void;
  onDismiss: () => void;
  onOpenStatus: () => void;
  onOpenBuild: () => void;
  degradedMessage?: string;
}

export function ServiceHealthModal({
  kind,
  visible,
  checking,
  onRetry,
  onReload,
  onDismiss,
  onOpenStatus,
  onOpenBuild,
  degradedMessage,
}: ServiceHealthModalProps) {
  const { t, locale } = useI18n();
  if (!visible || (kind !== "api_down" && kind !== "db_degraded")) return null;
  const apiDown = kind === "api_down";
  return (
    <div className="health-modal-scrim" role="presentation">
      <section className="health-modal" role="dialog" aria-modal="true" aria-labelledby="health-modal-title">
        {!apiDown && <button className="icon-button health-modal-x" type="button" aria-label={t("Close database warning")} onClick={onDismiss}><X size={17} /></button>}
        <div className="health-modal-icon" aria-hidden="true">{apiDown ? <ServerCrash /> : <DatabaseZap />}</div>
        <p className="eyebrow">{t("Runtime health")}</p>
        <h2 id="health-modal-title">{apiDown ? t("DocReview API is unavailable") : t("Database is not ready")}</h2>
        <p>{apiDown ? t("The API is not running normally. Check the service, then try again.") : degradedMessage ?? "The API is running, but the database or corpus is not ready for review operations."}</p>
        <div className="health-modal-actions">
          {!apiDown && <button className="button" type="button" onClick={onOpenStatus}>{t("Open System status")}</button>}
          {!apiDown && <button className="button" type="button" onClick={onDismiss}>{t("Continue")}</button>}
          {!apiDown && <button className="button primary" type="button" onClick={onOpenBuild}>{t("Open Build")}</button>}
          {apiDown && <button className="button" type="button" onClick={onReload}><RotateCw size={15} />{t("Reload page")}</button>}
          {apiDown && <button className="button primary" type="button" disabled={checking} onClick={onRetry}><RefreshCw size={15} /> {checking ? t("Checking…") : t("Try again")}</button>}
        </div>
      </section>
    </div>
  );
}
