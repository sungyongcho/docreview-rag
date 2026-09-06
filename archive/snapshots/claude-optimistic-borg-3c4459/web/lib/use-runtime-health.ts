"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getHealth, getReadiness } from "./api";
import type { Readiness } from "./types";

export type RuntimeHealthKind = "checking" | "healthy" | "api_down" | "db_degraded";

export interface RuntimeHealthState {
  kind: RuntimeHealthKind;
  readiness: Readiness | null;
  checkedAt: string | null;
}

const HEALTH_INTERVAL_MS = 30_000;
const HEALTH_TIMEOUT_MS = 5_000;

function issueKey(state: RuntimeHealthState): string | null {
  if (state.kind === "api_down") return "api_down";
  if (state.kind !== "db_degraded") return null;
  const corpus = state.readiness?.corpus;
  return `db:${corpus?.schema_status ?? "unknown"}:${corpus?.schema_message ?? ""}`;
}

export function useRuntimeHealth() {
  const [state, setState] = useState<RuntimeHealthState>({
    kind: "checking",
    readiness: null,
    checkedAt: null,
  });
  const [checking, setChecking] = useState(true);
  const [dismissedIssue, setDismissedIssue] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  const check = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setChecking(true);
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const timeout = window.setTimeout(() => request.abort(), HEALTH_TIMEOUT_MS);
    try {
      const health = await getHealth(request.signal);
      if (health.status !== "ok") throw new Error("API health response was not ok.");
      const readiness = await getReadiness(request.signal);
      const healthy = readiness.status === "ready" || readiness.corpus.availability === "not_applicable";
      if (!mounted.current) return;
      setState({
        kind: healthy ? "healthy" : "db_degraded",
        readiness,
        checkedAt: new Date().toISOString(),
      });
      if (healthy) setDismissedIssue(null);
    } catch {
      if (!mounted.current) return;
      setState((current) => ({
        kind: "api_down",
        readiness: current.readiness,
        checkedAt: new Date().toISOString(),
      }));
    } finally {
      window.clearTimeout(timeout);
      if (mounted.current) setChecking(false);
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void check();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void check();
    }, HEALTH_INTERVAL_MS);
    const onVisibility = () => {
      if (document.visibilityState === "visible") void check();
    };
    const onOnline = () => void check();
    const onOffline = () => {
      setState((current) => ({ ...current, kind: "api_down", checkedAt: new Date().toISOString() }));
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      mounted.current = false;
      controller.current?.abort();
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [check]);

  const currentIssue = useMemo(() => issueKey(state), [state]);
  const modalVisible = state.kind === "api_down"
    || (state.kind === "db_degraded" && dismissedIssue !== currentIssue);

  return {
    ...state,
    checking,
    check,
    modalVisible,
    dismissWarning: () => {
      if (state.kind === "db_degraded") setDismissedIssue(currentIssue);
    },
  };
}
