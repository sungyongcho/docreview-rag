import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

/** Web package root resolved from this file, so callers stay cwd-independent. */
export const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const HASHED_DIRECTORIES = ["app", "branding", "components", "lib", "public", "scripts"];
const HASHED_FILES = ["next.config.ts", "package.json", "package-lock.json", "tsconfig.json", "vitest.config.ts", "vitest.setup.ts"];
const SKIPPED_ENTRIES = new Set([".git", ".next", ".turbo", ".tutorial", "coverage", "dist", "node_modules", "out"]);
const SKIPPED_FILES = new Set(["api-generated.ts", "next-env.d.ts", "operator-api-generated.ts", "tsconfig.tsbuildinfo"]);

function* walk(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
    if (SKIPPED_ENTRIES.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else if (entry.isFile() && !SKIPPED_FILES.has(entry.name)) yield path;
  }
}

/** Sorted hash inputs as "/" separated names relative to rootDir — never absolute paths. */
export function fingerprintInputs(rootDir = WEB_ROOT) {
  const names = [];
  for (const directory of HASHED_DIRECTORIES) {
    const absolute = join(rootDir, directory);
    if (existsSync(absolute)) for (const file of walk(absolute)) names.push(relative(rootDir, file).split(sep).join("/"));
  }
  for (const file of HASHED_FILES) if (existsSync(join(rootDir, file))) names.push(file);
  return names.sort();
}

/** Deterministic content fingerprint of the web sources that shape the bundle; no git or network. */
export function buildFingerprint(rootDir = WEB_ROOT) {
  const hash = createHash("sha256");
  for (const name of fingerprintInputs(rootDir)) {
    hash.update(name);
    hash.update("\0");
    hash.update(readFileSync(join(rootDir, name)));
    hash.update("\0");
  }
  return hash.digest("hex").slice(0, 12);
}

/** Fingerprint plus capture time; the timestamp is independent of the hashed inputs. */
export function buildMetadata({ rootDir = WEB_ROOT, now = new Date() } = {}) {
  return { fingerprint: buildFingerprint(rootDir), builtAt: now.toISOString() };
}
