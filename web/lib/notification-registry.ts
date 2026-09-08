import type { ReviewEngineState } from "./types";
import type { NavigationTarget } from "./navigation";

export type NotificationKind = "info" | "success" | "warning" | "error" | "job";
export type NotificationTarget = NavigationTarget | { view: "build"; tab: "jobs"; jobId: string } | { view: "settings"; category: "prompt" | "local" | "data" | "about" | "limits" | "runtime" };
export interface NotificationDetail { text?: string; cause?: string; path?: string; fix?: NotificationTarget; }
export interface NotificationSpec { classification: "persistent" | "transient" | "inline-replaced"; title: string; target: NotificationTarget | null; surface: string | null; }

/** Every production call declares a registered delivery class and its owning surface. */
export const NOTIFICATION_EVENTS = {
  "snapshot-comparison-result": { classification: "persistent", title: "Snapshot comparison", target: { view: "measure", tab: "snapshots", resultId: null }, surface: "measure-snapshots" },
  "notification-target-unavailable": { classification: "transient", title: "Item unavailable", target: null, surface: null },
  "build-refresh-error": {
    "classification": "inline-replaced",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "documents"
    },
    "surface": "build-documents"
  },
  "corpus-operation-notice": {
    "classification": "transient",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-jobs"
  },
  "corpus-operation-error": {
    "classification": "persistent",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-jobs"
  },
  "corpus-operation-warning": {
    "classification": "transient",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-pipeline"
  },
  "prod-eval-warning": {
    "classification": "transient",
    "title": "Controls unavailable",
    "target": null,
    "surface": null
  },
  "evaluation-warning": {
    "classification": "transient",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "runs"
    },
    "surface": "measure-runs"
  },
  "evaluation-duplicate-notice": {
    "classification": "inline-replaced",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "runs"
    },
    "surface": "measure-runs"
  },
  "evaluation-queued-notice": {
    "classification": "transient",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "runs"
    },
    "surface": "measure-runs"
  },
  "evaluation-error": {
    "classification": "persistent",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "runs"
    },
    "surface": "measure-runs"
  },
  "measure-refresh-error": {
    "classification": "persistent",
    "title": "Notification",
    "target": {
      "view": "system",
      "tab": "status"
    },
    "surface": null
  },
  "golden-revisions-error": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "comparison-error": {
    "classification": "persistent",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "compare"
    },
    "surface": "measure-runs"
  },
  "evaluation-detail-error": {
    "classification": "inline-replaced",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "compare"
    },
    "surface": "measure-runs"
  },
  "golden-draft-notice": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "golden-draft-error": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "golden-save-notice": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "golden-save-error": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "golden-action-notice": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "golden-action-error": {
    "classification": "persistent",
    "title": "Golden dataset",
    "target": {
      "view": "measure",
      "tab": "golden"
    },
    "surface": "measure-golden"
  },
  "snapshot-create-notice": {
    "classification": "persistent",
    "title": "Snapshots",
    "target": {
      "view": "measure",
      "tab": "snapshots"
    },
    "surface": "measure-snapshots"
  },
  "snapshot-create-error": {
    "classification": "persistent",
    "title": "Snapshots",
    "target": {
      "view": "measure",
      "tab": "snapshots"
    },
    "surface": "measure-snapshots"
  },
  "snapshot-compare-error": {
    "classification": "persistent",
    "title": "Snapshots",
    "target": {
      "view": "measure",
      "tab": "snapshots"
    },
    "surface": "measure-snapshots"
  },
  "snapshot-visibility-notice": {
    "classification": "persistent",
    "title": "Snapshots",
    "target": {
      "view": "measure",
      "tab": "snapshots"
    },
    "surface": "measure-snapshots"
  },
  "snapshot-visibility-error": {
    "classification": "persistent",
    "title": "Snapshots",
    "target": {
      "view": "measure",
      "tab": "snapshots"
    },
    "surface": "measure-snapshots"
  },
  "evaluation-cancel-error": {
    "classification": "persistent",
    "title": "Evaluation",
    "target": {
      "view": "measure",
      "tab": "runs"
    },
    "surface": "measure-runs"
  },
  "help-locked-warning": {
    "classification": "transient",
    "title": "Controls unavailable",
    "target": null,
    "surface": null
  },
  "snapshot-review-notice": {
    "classification": "persistent",
    "title": "Snapshots",
    "target": {
      "view": "measure",
      "tab": "snapshots"
    },
    "surface": "measure-snapshots"
  },
  "evidence-review-error": {
    "classification": "inline-replaced",
    "title": "Notification",
    "target": {
      "view": "system",
      "tab": "status"
    },
    "surface": null
  },
  "operations-run-notice": {
    "classification": "transient",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "operations-run-error": {
    "classification": "persistent",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "prod-locked-warning": {
    "classification": "transient",
    "title": "Controls unavailable",
    "target": null,
    "surface": null
  },
  "local-conversations-cleared-notice": {
    "classification": "transient",
    "title": "Browser data",
    "target": {
      "view": "settings",
      "category": "data"
    },
    "surface": "settings"
  },
  "operations-refresh-error": {
    "classification": "persistent",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "operations-poll-notice": {
    "classification": "transient",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "operations-cancel-notice": {
    "classification": "transient",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "operations-cancel-error": {
    "classification": "persistent",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "defaults-suites-error": {
    "classification": "persistent",
    "title": "Experiment defaults",
    "target": {
      "view": "measure",
      "tab": "runs",
      "resultId": null
    },
    "surface": "measure-runs"
  },
  "defaults-snapshots-error": {
    "classification": "persistent",
    "title": "Experiment defaults",
    "target": {
      "view": "measure",
      "tab": "runs",
      "resultId": null
    },
    "surface": "measure-runs"
  },
  "defaults-revisions-error": {
    "classification": "persistent",
    "title": "Experiment defaults",
    "target": {
      "view": "measure",
      "tab": "runs",
      "resultId": null
    },
    "surface": "measure-runs"
  },
  "experiment-defaults-notice": {
    "classification": "transient",
    "title": "Experiment defaults",
    "target": {
      "view": "measure",
      "tab": "runs",
      "resultId": null
    },
    "surface": "measure-runs"
  },
  "profile-defaults-notice": {
    "classification": "transient",
    "title": "Settings",
    "target": {
      "view": "settings",
      "category": "prompt"
    },
    "surface": "settings"
  },
  "limits-error": {
    "classification": "persistent",
    "title": "Runtime settings",
    "target": {
      "view": "system",
      "tab": "status"
    },
    "surface": "system-status"
  },
  "desktop-notifications-notice": {
    "classification": "transient",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "desktop-notifications-warning": {
    "classification": "transient",
    "title": "Local Operations",
    "target": {
      "view": "system",
      "tab": "operations"
    },
    "surface": "operations"
  },
  "browser-storage-warning-warning": {
    "classification": "transient",
    "title": "Browser data",
    "target": {
      "view": "settings",
      "category": "data"
    },
    "surface": "settings"
  },
  "browser-storage-import-notice": {
    "classification": "persistent",
    "title": "Browser data",
    "target": {
      "view": "settings",
      "category": "data"
    },
    "surface": "settings"
  },
  "browser-storage-import-error": {
    "classification": "persistent",
    "title": "Browser data",
    "target": {
      "view": "settings",
      "category": "data"
    },
    "surface": "settings"
  },
  "prompt-defaults-notice": {
    "classification": "transient",
    "title": "Settings",
    "target": {
      "view": "settings",
      "category": "prompt"
    },
    "surface": "settings"
  },
  "conversation-settings-reset-notice": {
    "classification": "transient",
    "title": "Settings",
    "target": {
      "view": "settings",
      "category": "prompt"
    },
    "surface": "settings"
  },
  "all-defaults-notice": {
    "classification": "transient",
    "title": "Settings",
    "target": {
      "view": "settings",
      "category": "prompt"
    },
    "surface": "settings"
  },
  "playground-retrieval-error": {
    "classification": "persistent",
    "title": "Search trial",
    "target": {
      "view": "measure",
      "tab": "playground"
    },
    "surface": "playground"
  },
  "playground-review-error": {
    "classification": "persistent",
    "title": "Search trial",
    "target": {
      "view": "measure",
      "tab": "playground"
    },
    "surface": "playground"
  },
  "raw-request-error": {
    "classification": "persistent",
    "title": "API request",
    "target": {
      "view": "system",
      "tab": "api"
    },
    "surface": "system-api"
  },
  "document-facets-error": {
    "classification": "inline-replaced",
    "title": "Documents",
    "target": {
      "view": "build",
      "tab": "documents"
    },
    "surface": "build-documents"
  },
  "job-status": {
    "classification": "persistent",
    "title": "Job activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-jobs"
  },
  "jobs-refresh-error": {
    "classification": "persistent",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-jobs"
  },
  "job-retry-id-error": {
    "classification": "persistent",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-jobs"
  },
  "job-cancel-id-error": {
    "classification": "persistent",
    "title": "Corpus activity",
    "target": {
      "view": "build",
      "tab": "jobs"
    },
    "surface": "build-jobs"
  },
  "health-transition": {
    "classification": "persistent",
    "title": "Connection status",
    "target": {
      "view": "system",
      "tab": "status"
    },
    "surface": "health"
  },
  "local-connection": {
    "classification": "persistent",
    "title": "Local model connection",
    "target": {
      "view": "settings",
      "category": "local"
    },
    "surface": "local-model"
  },
  "local-cpu": {
    "classification": "persistent",
    "title": "Local model speed",
    "target": {
      "view": "settings",
      "category": "local"
    },
    "surface": "slow-cpu"
  },
  "review-result": {
    "classification": "persistent",
    "title": "Review completed",
    "target": {
      "view": "review"
    },
    "surface": "review"
  },
  "reset-receipt": {
    "classification": "persistent",
    "title": "Runtime reset",
    "target": {
      "view": "build",
      "tab": "pipeline",
      "stage": 1
    },
    "surface": "reset"
  },
  "preset-sync": {
    "classification": "persistent",
    "title": "Retrieval presets",
    "target": {
      "view": "measure",
      "tab": "presets",
      "resultId": null
    },
    "surface": "presets"
  },
  "evaluation-comparison": {
    "classification": "persistent",
    "title": "Evaluation comparison",
    "target": {
      "view": "measure",
      "tab": "compare"
    },
    "surface": "measure-compare"
  },
  "browser-export": {
    "classification": "persistent",
    "title": "Browser data",
    "target": {
      "view": "settings",
      "category": "data"
    },
    "surface": "settings"
  }
} as const satisfies Record<string, NotificationSpec>;
export type NotificationEvent = keyof typeof NOTIFICATION_EVENTS;
export interface NotifyOptions {
  /** Optional recovery navigation shown directly inside the live banner. */
  actionLabel?: string;
  event: NotificationEvent;
  kind?: NotificationKind;
  key?: string;
  title?: string;
  persist?: boolean;
  target?: NotificationTarget;
  detail?: NotificationDetail;
  jobId?: string;
  desktop?: boolean;
  duration?: number;
  surface?: string;
  supersedes?: string[];
  revision?: string;
  update?: boolean;
}

/** Keep structured API text verbatim; UI chrome explains the stable cause separately. */
export function notificationErrorDetail(error: unknown): NotificationDetail | undefined {
  if (!error || typeof error !== "object") return undefined;
  const record = error as Record<string, unknown>;
  const payload = record.failure && typeof record.failure === "object" ? record.failure as Record<string, unknown> : record;
  const text = typeof payload.detail === "string" ? payload.detail : Array.isArray(payload.details) ? payload.details.map(value => typeof value === "string" ? value : JSON.stringify(value, null, 2)).filter(Boolean).join("\n") || undefined : undefined;
  const cause = typeof payload.cause === "string" ? payload.cause : undefined;
  const path = typeof payload.path === "string" ? payload.path : undefined;
  const job = payload.corpus_job && typeof payload.corpus_job === "object" ? payload.corpus_job as Record<string, unknown> : null;
  const fix: NotificationTarget | undefined = cause ? typeof job?.job_id === "string" ? { view: "build", tab: "jobs", jobId: job.job_id } : { view: "build", tab: "documents" } : undefined;
  return text || cause || path ? { text, cause, path, fix } : undefined;
}


/** Prefer the API's original message over client-added validation or Error prefixes. */
export function notificationErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "failure" in error && error.failure && typeof error.failure === "object" && "message" in error.failure && typeof error.failure.message === "string") return error.failure.message;
  if (error && typeof error === "object" && "message" in error && typeof error.message === "string") return error.message;
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") return error.detail;
  return error instanceof Error ? error.message : String(error);
}


/** Share one connection-event identity between explicit actions and refreshed server state. */
export function localConnectionNotice(local: ReviewEngineState) {
  const reachable = local.enabled === true || local.reason === "no_answer_models";
  const disconnected = ["disconnected", "not_configured", "disabled_in_prod"].includes(local.reason ?? "");
  const message = reachable ? "Local model server connected." : disconnected ? "Local model server disconnected." : "Local model server is unavailable.";
  const kind: NotificationKind = reachable || disconnected ? "success" : "error";
  const signature = JSON.stringify([reachable, local.reason, local.protocol, local.model]);
  return { message, kind, signature, revision: `${signature}:${local.checked_at ?? "unrecorded"}` };
}
