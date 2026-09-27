import assert from "node:assert/strict";
import { once } from "node:events";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { test } from "node:test";
import { Miniflare } from "miniflare";

const config = JSON.parse(readFileSync(new URL("./wrangler.jsonc", import.meta.url), "utf8"));
const publicOrigin = "https://sungyongcho.com";

/** Bind an isolated local upstream and close every connection when its test finishes. */
async function upstream(t, handle) {
  const server = createServer(handle);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  return `http://127.0.0.1:${server.address().port}`;
}

/** Execute the maintained Worker in workerd, replacing only its two origin bindings. */
async function router(t, api, site = api) {
  const worker = new Miniflare({
    cf: false,
    telemetry: { enabled: false },
    logRequests: false,
    workers: [{ config: {
      name: config.name,
      compatibilityDate: config.compatibility_date,
      manifest: { mainModule: config.main, modules: { [config.main]: { type: "esm", contents: readFileSync(new URL(config.main, import.meta.url), "utf8") } } },
      env: { DOCREVIEW_ORIGIN: { type: "json", value: api }, DOCREVIEW_SITE_ORIGIN: { type: "json", value: site } },
    } }],
  });
  t.after(() => worker.dispose());
  return worker;
}

/** Echo a bounded test request so route, query, headers and bytes are observable. */
function echo(label) {
  return (request, response) => {
    const chunks = [];
    request.on("data", chunk => chunks.push(chunk));
    request.on("end", () => {
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({ label, path: request.url, method: request.method, headers: request.headers, body: Buffer.concat(chunks).toString() }));
    });
  };
}

test("API strips only its prefix while the static site keeps the full public path", { timeout: 10_000 }, async t => {
  const api = await upstream(t, echo("api"));
  const site = await upstream(t, echo("site"));
  const worker = await router(t, api, site);
  for (const [path, label, expected] of [
    ["/docreview-rag/api", "api", "/"],
    ["/docreview-rag/api/", "api", "/"],
    ["/docreview-rag/api/limits/?view=public&x=a%2Fb", "api", "/limits/?view=public&x=a%2Fb"],
    ["/docreview-rag", "site", "/docreview-rag"],
    ["/docreview-rag/", "site", "/docreview-rag/"],
    ["/docreview-rag/_next/static/app.js?v=1", "site", "/docreview-rag/_next/static/app.js?v=1"],
    ["/docreview-rag/api-other", "site", "/docreview-rag/api-other"],
  ]) {
    const response = await worker.dispatchFetch(`${publicOrigin}${path}`);
    const actual = await response.json();
    assert.equal(response.status, 200);
    assert.equal(actual.label, label);
    assert.equal(actual.path, expected);
    assert.equal(actual.headers.host, new URL(label === "api" ? api : site).host);
  }
});

test("POST bodies reach the upstream before the client finishes uploading", { timeout: 10_000 }, async t => {
  const firstChunk = Promise.withResolvers();
  const api = await upstream(t, (request, response) => {
    const chunks = [];
    request.on("data", chunk => { chunks.push(chunk); firstChunk.resolve(); });
    request.on("end", () => { response.end(JSON.stringify({ method: request.method, body: Buffer.concat(chunks).toString(), telemetry: request.headers["x-docreview-telemetry"] })); });
  });
  const worker = await router(t, api);
  let upload;
  const body = new ReadableStream({ start(controller) { upload = controller; controller.enqueue(new TextEncoder().encode("first ")); } });
  const pending = worker.dispatchFetch(`${publicOrigin}/docreview-rag/api/review/stream/`, { method: "POST", body, duplex: "half", headers: { "X-DocReview-Telemetry": "stages" } });
  await firstChunk.promise;
  upload.enqueue(new TextEncoder().encode("second"));
  upload.close();
  assert.deepEqual(await (await pending).json(), { method: "POST", body: "first second", telemetry: "stages" });
});

test("SSE headers and the first event arrive before the upstream completes", { timeout: 10_000 }, async t => {
  let finish;
  const api = await upstream(t, (_request, response) => {
    response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", "x-upstream": "stream" });
    response.write('event: stage\ndata: {"node":"retrieve"}\n\n');
    finish = () => response.end('event: done\ndata: {}\n\n');
  });
  t.after(() => finish?.());
  const worker = await router(t, api);
  const response = await worker.dispatchFetch(`${publicOrigin}/docreview-rag/api/review/stream/`, { method: "POST", body: "{}" });
  assert.equal(response.headers.get("content-type"), "text/event-stream");
  assert.equal(response.headers.get("cache-control"), "no-cache");
  const reader = response.body.getReader();
  const first = await reader.read();
  assert.equal(new TextDecoder().decode(first.value), 'event: stage\ndata: {"node":"retrieve"}\n\n');
  assert.equal(first.done, false);
  finish();
  let rest = "";
  for (;;) {
    const part = await reader.read();
    if (part.done) break;
    rest += new TextDecoder().decode(part.value);
  }
  assert.equal(rest, 'event: done\ndata: {}\n\n');
});

test("upstream errors, Retry-After and redirects pass through exactly once", { timeout: 10_000 }, async t => {
  const calls = [];
  const api = await upstream(t, (request, response) => {
    calls.push(request.url);
    const status = Number(request.url.slice(1));
    response.writeHead(status, { "retry-after": "47", "content-type": "text/plain", ...(status === 308 ? { location: "https://other.test/do-not-follow" } : {}) });
    response.end(`upstream ${status}`);
  });
  const worker = await router(t, api);
  for (const status of [429, 413, 503, 308]) {
    const response = await worker.dispatchFetch(`${publicOrigin}/docreview-rag/api/${status}`, { method: "POST", body: "{}", redirect: "manual" });
    assert.equal(response.status, status);
    assert.equal(response.headers.get("retry-after"), "47");
    assert.equal(await response.text(), `upstream ${status}`);
    if (status === 308) assert.equal(response.headers.get("location"), "https://other.test/do-not-follow");
  }
  assert.deepEqual(calls, ["/429", "/413", "/503", "/308"]);
});

test("unrelated hosts and paths return 404 without forwarding to any origin", { timeout: 10_000 }, async t => {
  let calls = 0;
  const api = await upstream(t, (_request, response) => { calls++; response.end("unexpected"); });
  const worker = await router(t, api);
  for (const url of [`${publicOrigin}/`, `${publicOrigin}/gomoku/`, `${publicOrigin}/alphazero/`, `${publicOrigin}/minimax/`, `${publicOrigin}/docreview-rag-extra`, "https://other.test/docreview-rag/"]) {
    const response = await worker.dispatchFetch(url);
    assert.equal(response.status, 404);
    assert.equal(await response.text(), "Not found");
  }
  assert.equal(calls, 0);
});
