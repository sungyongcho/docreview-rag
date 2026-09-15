import { useEffect, useState } from "react";

/**
 * Build facts inlined by next.config through env constants at bundle time.
 * Empty strings are the valid fallback when the constants are unset.
 */
export function buildFingerprint(): string {
  return fullBuildFingerprint().slice(0, 6);
}

/** Unabbreviated source fingerprint retained for the build information panel. */
export function fullBuildFingerprint(): string {
  return process.env.NEXT_PUBLIC_DOCREVIEW_BUILD_FINGERPRINT ?? "";
}

/** ISO instant captured when next.config loaded — the build/dev-server start, never visit time. */
export function builtAtIso(): string {
  return process.env.NEXT_PUBLIC_DOCREVIEW_BUILT_AT ?? "";
}

export function builtAt(): Date | null {
  const ms = Date.parse(builtAtIso());
  return Number.isNaN(ms) ? null : new Date(ms);
}

/** Deterministic UTC label shared by prerendered HTML and the first client render. */
export function formatBuiltAtUtc(date: Date): string {
  return `${date.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

/** Browser-local label with an explicit timezone name; no IP or geolocation lookups. */
export function formatBuiltAtLocal(date: Date): string {
  const parts = localBuildTime(date);
  return `${parts.date} ${parts.time} ${parts.zone}`;
}

/** Keep regional identity separate from date/time so the lockup can wrap intentionally. */
export function localBuildTime(date: Date, zone = new Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC") {
  return {
    date: new Intl.DateTimeFormat(undefined, { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(date),
    time: new Intl.DateTimeFormat(undefined, { timeZone: zone, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(date),
    shortTime: new Intl.DateTimeFormat("en-US", { timeZone: zone, hour: "2-digit", minute: "2-digit", hour12: true }).format(date),
    zone,
  };
}

/** The initial UTC parts match server HTML; local parts are applied after hydration. */
export function useBuildTimeParts() {
  const [parts, setParts] = useState(() => {
    const date = builtAt();
    return date ? { date: date.toISOString().slice(0, 10), time: date.toISOString().slice(11, 19), shortTime: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", hour12: true }).format(date), zone: "UTC" } : null;
  });
  useEffect(() => {
    const date = builtAt();
    setParts(date ? localBuildTime(date) : null);
  }, []);
  return parts;
}

/** Hydration-safe timestamp: starts on the deterministic UTC label, then re-labels in the browser timezone. */
export function useBuildTimestamp(): string | null {
  const [label, setLabel] = useState(() => {
    const date = builtAt();
    return date ? formatBuiltAtUtc(date) : null;
  });
  useEffect(() => {
    const date = builtAt();
    setLabel(date ? formatBuiltAtLocal(date) : null);
  }, []);
  return label;
}
