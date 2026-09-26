import { vi } from "vitest";

const unexpected: string[] = [];

/** Describe the exact HTTP route independently of its query parameters. */
export function requestRoute(input: RequestInfo | URL, init?: RequestInit): string {
  const request = input instanceof Request ? input : null;
  const url = new URL(request?.url ?? String(input), "http://localhost");
  const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
  return `${method} ${url.pathname.replace(/^\/docreview-rag\/api(?=\/)/, "").replace(/\/$/, "")}`;
}

/** Reject undeclared requests and remember them even when the UI handles the error. */
export function unexpectedRequest(input: RequestInfo | URL, init?: RequestInit): never {
  const route = requestRoute(input, init);
  unexpected.push(route);
  throw new Error(`Unexpected test request: ${route}`);
}

/** Assert the HTTP boundary after unmounting, so handled application errors cannot hide it. */
export function expectNoUnexpectedRequests(): void {
  const requests = unexpected.splice(0);
  if (requests.length) throw new Error(`Undeclared HTTP requests:\n${requests.join("\n")}`);
}

/** Encode exactly the supplied fixture without inventing missing server state. */
export function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

/** Install only the routes declared by this scenario; unexpected requests also fail teardown. */
export function stubHttp(routes: Record<string, (init?: RequestInit) => Response | Promise<Response>>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const handler = routes[requestRoute(input, init)];
    return handler ? handler(init) : unexpectedRequest(input, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
