import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { deploymentOptions } from "./deploy.mjs";

const config = JSON.parse(readFileSync(new URL("./wrangler.jsonc", import.meta.url), "utf8"));

test("bootstrap changes only routes and preserves both origins and runtime settings", () => {
  const normal = deploymentOptions(["--dry-run"], {}, {}, config);
  const bootstrap = deploymentOptions(["--dry-run", "--bootstrap"], {}, {}, config);
  assert.deepEqual(bootstrap.config, { ...normal.config, routes: [] });
  assert.equal(bootstrap.config.name, "docreview-router");
  assert.equal(bootstrap.config.compatibility_date, "2026-02-11");
  assert.equal(bootstrap.config.workers_dev, false);
  assert.equal(bootstrap.config.preview_urls, false);
  assert.deepEqual(normal.config.routes.map(route => route.pattern), ["sungyongcho.com/docreview-rag", "sungyongcho.com/docreview-rag/*"]);
});

test("credentials stay outside Worker bindings and process settings override dotenv values", () => {
  const result = deploymentOptions([], { CLOUDFLARE_ACCOUNT_ID: "test-account", CLOUDFLARE_API_TOKEN: "test-token", DEPLOY_DOCREVIEW_ORIGIN: "http://origin.test:8880" }, { CLOUDFLARE_API_TOKEN: "old-token", DEPLOY_DOCREVIEW_ORIGIN: "https://old.test", OPENAI_API_KEY_PROD: "never-copy-this", DEPLOY_DOCREVIEW_SITE_ORIGIN: "https://site.test" }, config);
  assert.deepEqual(result.credentials, { CLOUDFLARE_ACCOUNT_ID: "test-account", CLOUDFLARE_API_TOKEN: "test-token" });
  assert.deepEqual(result.config.vars, { DOCREVIEW_ORIGIN: "http://origin.test:8880", DOCREVIEW_SITE_ORIGIN: "https://site.test" });
  assert.equal(JSON.stringify(result.config).includes("test-token"), false);
  assert.equal(JSON.stringify(result).includes("never-copy-this"), false);
});

test("live deployment requires explicit account credentials and rejects origin or CLI scope expansion", () => {
  assert.throws(() => deploymentOptions([], {}, {}, config), /CLOUDFLARE_ACCOUNT_ID is required/);
  assert.throws(() => deploymentOptions([], { CLOUDFLARE_ACCOUNT_ID: "account" }, {}, config), /CLOUDFLARE_API_TOKEN is required/);
  assert.throws(() => deploymentOptions(["--name", "other-worker"], {}, {}, config), /Usage:/);
  for (const value of ["invalid", "ftp://origin.test", "https://user:secret@origin.test", "https://origin.test/path", "https://origin.test?query=secret", "https://origin.test#fragment"]) {
    assert.throws(() => deploymentOptions(["--dry-run"], { DEPLOY_DOCREVIEW_ORIGIN: value }, {}, config), /DEPLOY_DOCREVIEW_ORIGIN must be/);
  }
});
