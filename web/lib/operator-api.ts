import { presentationFetch } from "./production-preview";

// Read at call time: Next inlines NEXT_PUBLIC_* either way, and tests can stub the env per case.
function operatorBaseUrl() {
  return process.env.NEXT_PUBLIC_OPERATOR_BASE_URL ?? "";
}

function operatorToken() {
  return process.env.NEXT_PUBLIC_OPERATOR_TOKEN ?? "";
}

export type OperatorJobStatus = "running" | "succeeded" | "failed" | "cancelled" | "timed_out";

export interface OperatorCommand {
  command_id: string;
  label: string;
  description: string;
  category: "inspect" | "verify" | "service";
  confirmation: string | null;
  timeout_seconds: number;
}

export interface OperatorJob {
  job_id: string;
  command_id: string;
  label: string;
  status: OperatorJobStatus;
  output: string;
  exit_code: number | null;
  started_at: string;
  finished_at: string | null;
}

export function operatorAvailable() {
  return Boolean(operatorBaseUrl() && operatorToken());
}

export function operatorBase() {
  return operatorBaseUrl();
}

export class OperatorRequestError extends Error {
  constructor(message: string, readonly diagnosis?: WipeDiagnosis) {
    super(message);
    this.name = "OperatorRequestError";
  }
}

async function operatorRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (!operatorAvailable()) throw new Error("Local Operations is not enabled for this build.");
  const response = await presentationFetch(`${operatorBaseUrl()}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${operatorToken()}`,
      ...init?.headers,
    },
  }, true);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string; diagnosis?: WipeDiagnosis };
    throw new OperatorRequestError(payload.detail ?? `Operations request failed (${response.status}).`, payload.diagnosis);
  }
  return response.json() as Promise<T>;
}

export function getOperatorCommands() {
  return operatorRequest<OperatorCommand[]>("/commands");
}

export function getOperatorJobs() {
  return operatorRequest<OperatorJob[]>("/jobs");
}

export function startOperatorJob(commandId: string) {
  return operatorRequest<OperatorJob>("/jobs", {
    method: "POST",
    body: JSON.stringify({ command_id: commandId }),
  });
}

export function cancelOperatorJob(jobId: string) {
  return operatorRequest<OperatorJob>(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export interface WipePreview {
  token: string;
  expires: number;
  confirmation: string;
  backup: false;
  preserved: string[];
  target: { project: string; volume: string; tables: Record<string, number>; files: Array<{ path: string; bytes: number }> };
}
export interface WipeDiagnosis {
  code: string;
  details: Record<string, unknown>;
  remediation: string[];
}
export interface WipeCapability { available: boolean; reason: string | null; checked_at?: string; diagnosis?: WipeDiagnosis | null }
export interface WipeResult {
  extreme?: boolean;
  id?: string;
  status: string;
  stage?: string;
  message?: string;
  completed: string[];
  removed_files?: number;
  recovery?: string[];
  recovery_error?: string;
  retryable?: boolean;
  recovery_required?: boolean;
}
export function getWipeCapability() { return operatorRequest<WipeCapability>("/wipe/capability", { cache: "no-store" }); }
export function previewWipe() { return operatorRequest<WipePreview>("/wipe/preview", { method: "POST" }); }
export function startWipe(token: string, confirmation: string) { return operatorRequest<WipeResult>("/wipe", { method: "POST", body: JSON.stringify({ token, confirmation }) }); }
export function getWipeStatus() { return operatorRequest<WipeResult>("/wipe", { cache: "no-store" }); }
export function recoverWipe() { return operatorRequest<WipeResult>("/wipe/recover", { method: "POST" }); }

export function acknowledgeWipeBrowser(operationId: string) {
  return operatorRequest<{ acknowledged: boolean; id: string }>("/wipe/browser-cleared", {
    method: "POST", body: JSON.stringify({ operation_id: operationId }),
  });
}
