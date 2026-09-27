const PUBLIC_PREFIX = "/docreview-rag";
const API_PREFIX = `${PUBLIC_PREFIX}/api`;

/** Match a complete path segment so neighboring applications never enter this router. */
function matchesPrefix(pathname, prefix) {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export default {
  /** Forward one request as streams, retaining upstream status, headers and redirects. */
  fetch(request, env) {
    const incoming = new URL(request.url);
    if (incoming.hostname !== "sungyongcho.com" || !matchesPrefix(incoming.pathname, PUBLIC_PREFIX)) {
      return new Response("Not found", { status: 404 });
    }
    const api = matchesPrefix(incoming.pathname, API_PREFIX);
    const upstream = new URL(api ? env.DOCREVIEW_ORIGIN : env.DOCREVIEW_SITE_ORIGIN);
    upstream.pathname = api ? incoming.pathname.slice(API_PREFIX.length) || "/" : incoming.pathname;
    upstream.search = incoming.search;
    const headers = new Headers(request.headers);
    headers.set("Host", upstream.host);
    return fetch(upstream, {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual",
    });
  },
};
