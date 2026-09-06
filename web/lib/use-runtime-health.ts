"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getHealth, getProductionPreviewReadiness, getReadiness } from "./api";
import type { Readiness, ReviewEngineState } from "./types";

export type RuntimeHealthKind = "checking" | "healthy" | "api_down" | "db_degraded" | "preparation_needed";

export interface RuntimeHealthState {
  kind: RuntimeHealthKind;
  readiness: Readiness | null;
  checkedAt: string | null;
}

const HEALTH_INTERVAL_MS = 30_000;
const HEALTH_TIMEOUT_MS = 5_000;

function issueKey(state: RuntimeHealthState): string | null {
  if (state.kind === "api_down") return "api_down";
  if (state.kind === "preparation_needed") return "preparation_needed";
  if (state.kind !== "db_degraded") return null;
  const corpus = state.readiness?.corpus;
  return `db:${corpus?.schema_status ?? "unknown"}:${corpus?.schema_message ?? ""}`;
}

/** Keep last-known metadata without presenting stale local connectivity as available. */
function unavailableReadiness(readiness: Readiness | null): Readiness | null {
  if (!readiness?.review_engines?.local) return readiness;
  return { ...readiness, review_engines: { ...readiness.review_engines, local: { ...readiness.review_engines.local, enabled: false, reason: "api_unavailable" } } };
}

export function useRuntimeHealth({ active = true, publicPreview = false }: { active?: boolean; publicPreview?: boolean } = {}) {
  const [state, setState] = useState<RuntimeHealthState>({
    kind: "checking",
    readiness: null,
    checkedAt: null,
  });
  const [checking, setChecking] = useState(active);
  const [dismissedIssue, setDismissedIssue] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const activity = useRef(active);
  activity.current = active;

  const check = useCallback(async (force = false) => {
    if (!activity.current || !mounted.current) return;
    if (controller.current && !force) return;
    setChecking(true);
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const timeout = window.setTimeout(() => request.abort(), HEALTH_TIMEOUT_MS);
    try {
      const health = await getHealth(request.signal);
      if (health.status !== "ok") throw new Error("API health response was not ok.");
      if (!mounted.current || !activity.current || controller.current !== request) return;
      if (request.signal.aborted) throw new Error("API health check timed out.");
      const readiness = await (publicPreview ? getProductionPreviewReadiness : getReadiness)(request.signal);
      const healthy = readiness.status === "ready" || readiness.corpus.availability === "not_applicable";
      if (!mounted.current || !activity.current || controller.current !== request) return;
      if (request.signal.aborted) throw new Error("Runtime readiness check timed out.");
      setState({
        kind: healthy ? "healthy" : readiness.corpus.database_connected === true && readiness.corpus.schema_status === "compatible" ? "preparation_needed" : "db_degraded",
        readiness,
        checkedAt: new Date().toISOString(),
      });
      if (healthy) setDismissedIssue(null);
    } catch {
      if (!mounted.current || !activity.current || controller.current !== request) return;
      setState((current) => ({
        kind: "api_down",
        readiness: unavailableReadiness(current.readiness),
        checkedAt: new Date().toISOString(),
      }));
    } finally {
      window.clearTimeout(timeout);
      if (controller.current === request) {
        controller.current = null;
        if (mounted.current) setChecking(false);
      }
    }
  }, [publicPreview]);

  /** Invalidate an older poll before exposing a successful connection change. */
  const refreshLocal = useCallback((local: ReviewEngineState) => {
    if (!activity.current || publicPreview) return;
    setState((current) => ({ ...current, readiness: current.readiness ? {
      ...current.readiness, review_engines: { ...current.readiness.review_engines, local },
    } : null }));
    void check(true);
  }, [check, publicPreview]);

  useEffect(() => {
    mounted.current = true;
    if (!active) {
      setChecking(false);
      return;
    }
    void check();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void check();
    }, HEALTH_INTERVAL_MS);
    const onVisibility = () => {
      if (document.visibilityState === "visible") void check();
    };
    const onOnline = () => void check();
    const onOffline = () => {
      controller.current?.abort();
      controller.current = null;
      setChecking(false);
      setState((current) => ({ ...current, readiness: unavailableReadiness(current.readiness), kind: "api_down", checkedAt: new Date().toISOString() }));
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      mounted.current = false;
      controller.current?.abort();
      controller.current = null;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [check, active]);

  const currentIssue = useMemo(() => issueKey(state), [state]);
  const modalVisible = active && (state.kind === "api_down"
    || ((state.kind === "db_degraded" || state.kind === "preparation_needed") && dismissedIssue !== currentIssue));

  return {
    ...state,
    checking,
    check,
    refreshLocal,
    modalVisible,
    dismissWarning: () => {
      if (state.kind === "db_degraded" || state.kind === "preparation_needed") setDismissedIssue(currentIssue);
    },
  };
}
