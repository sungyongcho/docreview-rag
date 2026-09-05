// @vitest-environment node
import { mkdtemp, mkdir, readFile, writeFile, rename, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { watchTutorial } from "./tutorial-watch.mjs";
import { DOCUMENTATION_REGISTRY } from "../lib/documentation-registry.mjs";
import { writeTutorialFixtures } from "./tutorial-test-support.mjs";

const cleanups = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup(); });

/** Watch only temporary canonical fixtures; never modify the actual documentation. */
async function fixture() {
  const directory = await mkdtemp(join(tmpdir(), "docreview-tutorial-watch-"));
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const root = join(directory, "TUTORIAL");
  await mkdir(join(root, "assets"), { recursive: true });
  await writeTutorialFixtures(root);
  const output = join(root, "output");
  const revisionFile = join(root, ".tutorial/revision.ts");
  const registryFile = join(root, "registry.json");
  await writeFile(registryFile, JSON.stringify(DOCUMENTATION_REGISTRY));
  const onError = vi.fn();
  const stop = await watchTutorial({ root, output, revisionFile, registryFile, intervalMs: 20, onError });
  cleanups.push(stop);
  return { root, output, revisionFile, registryFile, onError };
}

it("refreshes the imported revision after editor replacement saves and image additions or replacements", async () => {
  const { root, output, revisionFile } = await fixture();
  const original = await readFile(revisionFile, "utf8");
  const source = await readFile(join(root, "ko/architecture.md"), "utf8");
  await writeFile(join(root, "ko/new.md"), source + "\n\nSaved paragraph.");
  await rename(join(root, "ko/new.md"), join(root, "ko/architecture.md"));
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).not.toBe(original));
  const edited = await readFile(revisionFile, "utf8");
  await writeFile(join(root, "assets/screenshot.png"), Buffer.from([137, 80, 78, 71, 1]));
  await writeFile(join(root, "ko/architecture.md"), source + "\n\n![Screenshot](../assets/screenshot.png)");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).not.toBe(edited));
  expect(await readFile(join(output, "screenshot.png"))).toEqual(Buffer.from([137, 80, 78, 71, 1]));
  const withImage = await readFile(revisionFile, "utf8");
  await writeFile(join(root, "assets/screenshot.png"), Buffer.from([137, 80, 78, 71, 2]));
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).not.toBe(withImage));
  expect(await readFile(join(output, "screenshot.png"))).toEqual(Buffer.from([137, 80, 78, 71, 2]));
});

it("surfaces missing canonical sources and automatically recovers even when the original valid bytes return", async () => {
  const { root, revisionFile, onError } = await fixture();
  const original = await readFile(revisionFile, "utf8");
  const source = join(root, "ko/overview.md");
  const markdown = await readFile(source);
  await rename(source, source + ".saving");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("Tutorial validation failed:"));
  expect(onError).toHaveBeenCalled();
  await writeFile(source, markdown);
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toBe(original));
});

it("reports an incomplete image save and recovers when the referenced file arrives", async () => {
  const { root, revisionFile } = await fixture();
  await writeFile(join(root, "en/architecture.md"), "# Guide\n\n![Screenshot](../assets/later.png)");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("Tutorial validation failed:"));
  await writeFile(join(root, "assets/later.png"), Buffer.from([137, 80, 78, 71]));
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("tutorialError: string | null = null"));
});

it("watches documents registered while the same development process is running", async () => {
  const { root, revisionFile, registryFile } = await fixture();
  const registry = structuredClone(DOCUMENTATION_REGISTRY);
  registry.documents.push({ id: "additional", slug: "additional", group: "reference", order: Math.max(...registry.documents.map((document) => document.order)) + 1, source: "additional.md", title: { ko: "추가 문서", en: "Additional document" }, summary: { ko: "새 등록 항목", en: "A newly registered entry" }, related: ["overview"], steps: [] });
  await writeFile(registryFile, JSON.stringify(registry));
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("Tutorial validation failed:"));
  for (const locale of registry.locales) await writeFile(join(root, locale, "additional.md"), "# Additional");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("tutorialError: string | null = null"));
  const registered = await readFile(revisionFile, "utf8");
  await writeFile(join(root, "en/additional.md"), "# Additional\n\nUpdated without a restart.");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).not.toBe(registered));
});

it("refreshes the development outline and recovers after an incomplete save", async () => {
  const { root, revisionFile } = await fixture();
  const original = await readFile(revisionFile, "utf8");
  const storyFile = join(root, "../DEVELOPMENT_STORY_OUTLINE.md");
  const source = await readFile(storyFile, "utf8");
  await writeFile(storyFile + ".saving", source + "\n\nDraft edit.");
  await rename(storyFile + ".saving", storyFile);
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).not.toBe(original));
  const edited = await readFile(revisionFile, "utf8");
  await writeFile(storyFile, "## Missing title");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("Development log requires one main heading"));
  await writeFile(storyFile, source + "\n\nDraft edit.");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toBe(edited));
});
