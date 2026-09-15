import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { WEB_ROOT, buildFingerprint, buildMetadata, fingerprintInputs } from "./build-metadata.mjs";

const dirs: string[] = [];
afterEach(() => { while (dirs.length) rmSync(dirs.pop()!, { recursive: true, force: true }); });

/** Seed a minimal stand-in web tree including entries the fingerprint must ignore. */
function fixture(): string {
  const root = mkdtempSync(join(tmpdir(), "docreview-build-"));
  dirs.push(root);
  mkdirSync(join(root, "app"), { recursive: true });
  mkdirSync(join(root, "components"), { recursive: true });
  mkdirSync(join(root, "node_modules", "pkg"), { recursive: true });
  mkdirSync(join(root, ".next"), { recursive: true });
  writeFileSync(join(root, "app", "page.tsx"), "export default function Page() { return null; }\n");
  writeFileSync(join(root, "components", "brand.tsx"), "export const name = 'DocReview RAG';\n");
  writeFileSync(join(root, "node_modules", "pkg", "index.js"), "dependency\n");
  writeFileSync(join(root, ".next", "cache.bin"), "cache\n");
  writeFileSync(join(root, "next.config.ts"), "export default {};\n");
  writeFileSync(join(root, "package.json"), "{}\n");
  return root;
}

it("returns 12 lowercase hex characters that stay stable for identical sources", () => {
  const root = fixture();
  expect(buildFingerprint(root)).toMatch(/^[0-9a-f]{12}$/);
  expect(buildFingerprint(root)).toBe(buildFingerprint(root));
});

it("depends only on relative names and contents, not on the directory location", () => {
  const first = fixture();
  const second = fixture();
  expect(second).not.toBe(first);
  expect(buildFingerprint(second)).toBe(buildFingerprint(first));
  for (const name of fingerprintInputs(first)) {
    expect(name.startsWith("/")).toBe(false);
    expect(name).not.toContain(first);
  }
});

it("changes when a hashed source changes", () => {
  const root = fixture();
  const before = buildFingerprint(root);
  writeFileSync(join(root, "components", "brand.tsx"), "export const name = 'DocReview';\n");
  expect(buildFingerprint(root)).not.toBe(before);
});

it("ignores dependencies and generated output", () => {
  const root = fixture();
  const before = buildFingerprint(root);
  writeFileSync(join(root, "node_modules", "pkg", "index.js"), "changed\n");
  writeFileSync(join(root, ".next", "cache.bin"), "changed\n");
  mkdirSync(join(root, "out"), { recursive: true });
  writeFileSync(join(root, "out", "index.html"), "export\n");
  expect(buildFingerprint(root)).toBe(before);
});

it("keeps the timestamp independent of the fingerprint inputs", () => {
  const root = fixture();
  const now = new Date("2026-09-14T01:02:03.000Z");
  const metadata = buildMetadata({ rootDir: root, now });
  expect(metadata.builtAt).toBe("2026-09-14T01:02:03.000Z");
  expect(metadata.fingerprint).toBe(buildFingerprint(root));
  expect(buildMetadata({ rootDir: root, now: new Date("2020-01-01T00:00:00.000Z") }).fingerprint).toBe(metadata.fingerprint);
});

it("hashes this checkout's web sources from any cwd", () => {
  expect(fingerprintInputs(WEB_ROOT)).toContain("next.config.ts");
  expect(buildFingerprint(WEB_ROOT)).toMatch(/^[0-9a-f]{12}$/);
});
