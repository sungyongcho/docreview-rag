"use client";

import { useEffect, useRef } from "react";
import { useI18n } from "@/lib/i18n";
import { useSavedPresets } from "@/lib/use-saved-presets";
import { getLifecycleReceipts } from "@/lib/operator-api";
import { localConnectionNotice } from "@/lib/notification-registry";
import type { ReviewEngineState } from "@/lib/types";
import type { RuntimeHealthKind } from "@/lib/use-runtime-health";
import { useNotifications, useNotificationSurface } from "./notifications";

/** Observe existing signals once; repeated polls and explicit preset mutation events share one state. */
export function NotificationSignals({ enabled, healthKind, healthMessage, checkedAt, operations, local, model, cpuSpeed, conversationId, reviewVisible, jobsVisible, systemVisible }: {
  enabled: boolean; healthKind: RuntimeHealthKind; healthMessage?: string | null; checkedAt: string | null;
  operations: boolean; local?: ReviewEngineState; model: string | null; cpuSpeed: number | null; conversationId?: string;
  reviewVisible: boolean; jobsVisible: boolean; systemVisible: boolean;
}) {
  const { t } = useI18n();const { notify } = useNotifications();
  const health = useRef<RuntimeHealthKind | null>(null);
  const speed = useRef<string | null>(null);
  const connection = useRef<string | null>(null);
  const preset = useRef<{ kind: string; signature: string } | null>(null);
  const receiptErrors = useRef<string | null>(null);
  const presets = useSavedPresets();
  useNotificationSurface("slow-cpu", enabled && reviewVisible && cpuSpeed !== null);
  useNotificationSurface("review", enabled && reviewVisible);
  useNotificationSurface("build-jobs", enabled && jobsVisible);
  useNotificationSurface("health", enabled && systemVisible);
  useEffect(() => {
    if (!enabled || healthKind === "checking" || health.current === healthKind) return;
    const prior = health.current;health.current = healthKind;
    const message = healthKind === "healthy" ? t(prior ? "API connection recovered." : "Connected to the API.") : healthKind === "api_down" ? t("The API connection is unavailable.") : healthMessage || t(healthKind === "preparation_needed" ? "Corpus preparation is needed." : "Database readiness is degraded.");
    notify(message, healthKind === "healthy" ? "success" : healthKind === "api_down" ? "error" : "warning", "runtime-health", undefined, { event: "health-transition" });
  }, [enabled, healthKind, healthMessage, notify, t]);
  useEffect(() => {
    if (!enabled || !local) return;
    const event = localConnectionNotice(local);const previous = connection.current;connection.current = event.signature;
    if (previous === null || previous === event.signature) return;
    notify(t(event.message), event.kind, "local-connection", undefined, { event: "local-connection", revision: event.revision });
  }, [enabled, local, notify, t]);
  useEffect(() => {
    if (!enabled || !model || cpuSpeed === null) return;
    const measurement = `${model}:${cpuSpeed}`;if (speed.current === measurement) return;speed.current = measurement;
    notify(t("Local model {model}: {speed} tokens/s.", { model, speed: cpuSpeed.toFixed(1) }), "warning", `local-cpu:${model}`, undefined, { event: "local-cpu", target: { view: "review", conversationId }, revision: measurement, silent: true });
  }, [enabled, model, cpuSpeed, conversationId, notify, t]);
  useEffect(() => {
    if (!enabled || !presets.loaded || presets.storageKind === "pending") return;
    const signature = JSON.stringify({ presets: presets.presets, builtins: presets.builtins, errors: presets.fileErrors, error: presets.error });
    const prior = preset.current;preset.current = { kind: presets.storageKind, signature };
    if (!prior || prior.kind !== presets.storageKind || prior.signature === signature) return;
    const errors = [presets.error, ...presets.fileErrors.map(item => `${item.file}: ${item.error}`)].filter(Boolean).join("\n");
    notify(errors || t("Retrieval presets synchronized."), errors ? "error" : "success", "preset-sync", undefined, { event: "preset-sync", revision: signature, detail: errors ? { text: errors } : undefined });
  }, [enabled, presets, notify, t]);
  useEffect(() => {
    if (!enabled || !operations || !checkedAt) return;
    let active = true;
    const controller = new AbortController();
    void getLifecycleReceipts(controller.signal).then(receipts => {
      if (!active) return;receiptErrors.current = null;
      for (const receipt of receipts) {
        if (receipt.status === "running") continue;
        const message = receipt.status === "succeeded" ? t("Fresh-start cleanup completed.") : receipt.error || t("Fresh-start cleanup failed.");
        notify(message, receipt.status === "succeeded" ? "success" : "error", `fresh-start:${receipt.updated}`, undefined, { event: "reset-receipt", update: true, revision: String(receipt.updated), detail: { text: receipt.completed.join("\n") } });
      }
    }).catch(error => {
      if (!active) return;const message = error instanceof Error ? error.message : t("Fresh-start receipt could not be read.");
      if (receiptErrors.current === message) return;receiptErrors.current = message;
      notify(message, "error", "lifecycle-receipts", undefined, { event: "reset-receipt" });
    });
    return () => { active = false;controller.abort(); };
  }, [enabled, operations, checkedAt, notify, t]);
  return null;
}
