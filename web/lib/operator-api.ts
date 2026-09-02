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

async function operatorRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (!operatorAvailable()) throw new Error("Local Operations is not enabled for this build.");
  const response = await fetch(`${operatorBaseUrl()}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${operatorToken()}`,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail ?? `Operations request failed (${response.status}).`);
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
