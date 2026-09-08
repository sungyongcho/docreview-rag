import { readStoredValue, writeStoredValue } from "./storage";
import type { NotificationDetail, NotificationKind, NotificationTarget } from "./notification-registry";

export const NOTIFICATION_STORAGE_KEY = "docreview:notifications:v1";
export const NOTIFICATION_LIMIT = 100;
export interface NotificationEntry {
  id: string;
  key: string;
  kind: NotificationKind;
  title: string;
  body: string;
  target?: NotificationTarget;
  detail?: NotificationDetail;
  createdAt: string;
  updatedAt: string;
  readAt?: string;
  jobId?: string;
  count: number;
  surface?: string;
  revision?: string;
}

/** Accept internal destinations only; saved notification data cannot navigate to arbitrary URLs. */
export function validNotificationTarget(value: unknown): value is NotificationTarget {
  if (!value || typeof value !== "object") return false;
  const route = value as Record<string, unknown>;
  if (route.view === "settings") return ["prompt", "local", "data", "about", "limits", "runtime"].includes(String(route.category));
  if (route.view === "review") return route.conversationId === undefined || typeof route.conversationId === "string";
  if (route.view === "build") return [undefined, "pipeline", "documents", "jobs"].includes(route.tab as string) && (route.jobId === undefined || typeof route.jobId === "string") && (route.stage === undefined || route.stage === "setup" || Number.isInteger(route.stage) && Number(route.stage) >= 1 && Number(route.stage) <= 7);
  if (route.view === "measure") return [undefined, "playground", "golden", "runs", "compare", "snapshots", "defaults", "presets"].includes(route.tab as string) && (route.resultId == null || Number.isSafeInteger(route.resultId) && Number(route.resultId) > 0);
  return route.view === "system" && [undefined, "status", "operations", "api", "usage"].includes(route.tab as string);
}

/** Reject malformed optional detail before it can reach a React text or navigation surface. */
function validDetail(value: unknown): boolean {
  if (value === undefined) return true;
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const detail = value as Record<string, unknown>;
  return ["text", "cause", "path"].every(key => detail[key] === undefined || typeof detail[key] === "string") && (detail.fix === undefined || validNotificationTarget(detail.fix));
}

/** Read bounded history through the app's existing versioned browser-storage boundary. */
export function loadNotifications(): NotificationEntry[] {
  try {
    const stored = JSON.parse(readStoredValue(NOTIFICATION_STORAGE_KEY) ?? "null");
    if (stored?.version !== 1 || !Array.isArray(stored.entries)) return [];
    return stored.entries.filter((entry: NotificationEntry) => entry && typeof entry.id === "string" && typeof entry.key === "string" && typeof entry.body === "string" && typeof entry.title === "string" && ["info", "success", "warning", "error", "job"].includes(entry.kind) && Number.isInteger(entry.count) && entry.count > 0 && Number.isFinite(Date.parse(entry.createdAt)) && Number.isFinite(Date.parse(entry.updatedAt)) && (entry.readAt === undefined || typeof entry.readAt === "string") && validDetail(entry.detail) && (entry.jobId === undefined || typeof entry.jobId === "string") && (entry.revision === undefined || typeof entry.revision === "string") && (!entry.target || validNotificationTarget(entry.target))).slice(-NOTIFICATION_LIMIT);
  } catch { return []; }
}

/** Store the bounded projection without changing unrelated browser data. */
export function saveNotifications(entries: NotificationEntry[]): void {
  writeStoredValue(NOTIFICATION_STORAGE_KEY, JSON.stringify({ version: 1, entries: entries.slice(-NOTIFICATION_LIMIT) }));
}

/** Append distinct actions; update only an explicit event identity or an identical repeated error. */
export function appendNotification(entries: NotificationEntry[], incoming: NotificationEntry, update = false): NotificationEntry[] {
  const prior = entries.findLast(entry => entry.key === incoming.key && (update || entry.kind === "error" && incoming.kind === "error" && entry.body === incoming.body && JSON.stringify(entry.detail) === JSON.stringify(incoming.detail)));
  const repeatedError = prior?.kind === "error" && incoming.kind === "error" && prior.body === incoming.body && JSON.stringify(prior.detail) === JSON.stringify(incoming.detail);
  const next = { ...incoming, id: prior?.id ?? incoming.id, createdAt: prior?.createdAt ?? incoming.createdAt, count: repeatedError ? prior.count + 1 : 1 };
  return [...entries.filter(entry => entry.id !== prior?.id), next].slice(-NOTIFICATION_LIMIT);
}

/** Reading never deletes a history entry; preserve the first time it was read. */
export function readNotification(entries: NotificationEntry[], id: string | null, now: string): NotificationEntry[] {
  return entries.map(entry => id === null || entry.id === id ? { ...entry, readAt: entry.readAt ?? now } : entry);
}
