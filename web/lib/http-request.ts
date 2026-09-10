/** `RequestInit` plus an optional per-attempt deadline in milliseconds; `0` or absent means no deadline. */
export type TimedRequestInit = RequestInit & { timeoutMs?: number };

/** Reject as soon as `signal` aborts, so a body read that ignores the abort cannot outlive its deadline. */
function rejectOnAbort(signal: AbortSignal): Promise<never> {
  return new Promise((_resolve, reject) => {
    if (signal.aborted) reject(signal.reason);
    else signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  });
}

/** Apply the same abort and response-body deadline to DEV, PROD and operator requests. */
export async function requestFetch(url: string, init: TimedRequestInit = {}): Promise<Response> {
  const { timeoutMs, ...requestInit } = init;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (requestInit.signal?.aborted) controller.abort();
  requestInit.signal?.addEventListener("abort", abort, { once: true });
  const deadline = timeoutMs
    ? setTimeout(() => controller.abort(new DOMException("Request timed out.", "TimeoutError")), timeoutMs)
    : null;
  try {
    const response = await fetch(url, { ...requestInit, signal: controller.signal });
    if (deadline === null) return response;
    // Include body delivery so stalled responses do not outlive the request deadline.
    const text = await Promise.race([response.text(), rejectOnAbort(controller.signal)]);
    const bodyless = response.status === 204 || response.status === 205 || response.status === 304;
    return new Response(bodyless ? null : text, { status: response.status, statusText: response.statusText, headers: response.headers });
  } finally {
    if (deadline !== null) clearTimeout(deadline);
    requestInit.signal?.removeEventListener("abort", abort);
  }
}
