import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { parseEnv } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";

const directory = dirname(fileURLToPath(import.meta.url));

/** Accept only root HTTP(S) origins; credentials, paths and query strings are not deploy settings. */
function origin(value, name) {
  let parsed;
  try { parsed = new URL(value); }
  catch { throw new Error(`${name} must be an HTTP(S) origin.`); }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error(`${name} must be an HTTP(S) origin without credentials, path, query or fragment.`);
  }
  return parsed.origin;
}

/** Resolve only this router's settings; process values override the repository dotenv. */
export function deploymentOptions(flags, environment, dotenv, config) {
  if (flags.some(flag => !["--dry-run", "--bootstrap"].includes(flag))) {
    throw new Error("Usage: node deploy.mjs [--dry-run] [--bootstrap]");
  }
  const dryRun = flags.includes("--dry-run");
  const value = name => environment[name] ?? dotenv[name];
  const credentials = Object.fromEntries(["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"].map(name => [name, value(name)]));
  if (!dryRun) for (const [name, secret] of Object.entries(credentials)) {
    if (!secret) throw new Error(`${name} is required in the environment or repository .env.`);
  }
  const vars = {
    DOCREVIEW_ORIGIN: origin(value("DEPLOY_DOCREVIEW_ORIGIN") || config.vars.DOCREVIEW_ORIGIN, "DEPLOY_DOCREVIEW_ORIGIN"),
    DOCREVIEW_SITE_ORIGIN: origin(value("DEPLOY_DOCREVIEW_SITE_ORIGIN") || config.vars.DOCREVIEW_SITE_ORIGIN, "DEPLOY_DOCREVIEW_SITE_ORIGIN"),
  };
  return {
    config: { ...config, ...(flags.includes("--bootstrap") ? { routes: [] } : {}), vars },
    dryRun,
    credentials: Object.fromEntries(Object.entries(credentials).filter(([, secret]) => secret !== undefined)),
  };
}

/** Deploy this Worker only, optionally creating it before its two existing routes are reassigned. */
function main() {
  const dotenvPath = process.env.DOTENV_PATH ?? resolve(directory, "../..", ".env");
  const dotenv = existsSync(dotenvPath) ? parseEnv(readFileSync(dotenvPath, "utf8")) : {};
  const config = JSON.parse(readFileSync(join(directory, "wrangler.jsonc"), "utf8"));
  const options = deploymentOptions(process.argv.slice(2), process.env, dotenv, config);
  // Keep the generated config beside worker.js so Wrangler resolves unchanged relative paths.
  const generated = join(directory, `.wrangler-${randomUUID()}.json`);
  writeFileSync(generated, JSON.stringify(options.config, null, 2), { mode: 0o600, flag: "wx" });
  try {
    const args = [join(directory, "node_modules/wrangler/bin/wrangler.js"), "deploy", "--config", generated, "--no-autoconfig"];
    if (options.dryRun) args.push("--dry-run", "--outdir", join(directory, "dist"));
    const result = spawnSync(process.execPath, args, {
      cwd: directory,
      stdio: "inherit",
      env: { ...process.env, ...options.credentials, WRANGLER_SEND_METRICS: "false", WRANGLER_LOG_PATH: join(directory, ".wrangler", "logs") },
    });
    if (result.error) throw result.error;
    process.exitCode = result.status ?? 1;
  } finally { unlinkSync(generated); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { main(); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
