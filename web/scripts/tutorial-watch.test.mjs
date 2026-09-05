// @vitest-environment node
import { mkdtemp, mkdir, readFile, writeFile, rename, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { watchTutorial } from "./tutorial-watch.mjs";

const cleanups = [];
afterEach(async () => { for (const cleanup of cleanups.splice(0).reverse()) await cleanup(); });

/** Watch only temporary canonical fixtures; never modify the actual documentation. */
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "docreview-tutorial-watch-"));
  cleanups.push(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, "assets"));
  for (const locale of ["ko", "en"]) {
    await mkdir(join(root, locale));
    await writeFile(join(root, locale, "walkthrough.md"), "# Guide\n\nOriginal paragraph.");
    await writeFile(join(root, locale, "cli.md"), "# CLI");
  }
  const output = join(root, "output");
  const revisionFile = join(root, ".tutorial/revision.ts");
  const onError = vi.fn();
  const stop = await watchTutorial({ root, output, revisionFile, intervalMs: 20, onError });
  cleanups.push(stop);
  return { root, output, revisionFile, onError };
}

it("refreshes the imported revision after editor replacement saves and image additions or replacements", async () => {
  const { root, output, revisionFile } = await fixture();
  const original = await readFile(revisionFile, "utf8");
  await writeFile(join(root, "ko/new.md"), "# Guide\n\nSaved paragraph.");
  await rename(join(root, "ko/new.md"), join(root, "ko/walkthrough.md"));
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).not.toBe(original));
  const edited = await readFile(revisionFile, "utf8");
  await writeFile(join(root, "assets/screenshot.png"), Buffer.from([137, 80, 78, 71, 1]));
  await writeFile(join(root, "ko/walkthrough.md"), "# Guide\n\n![Screenshot](../assets/screenshot.png)");
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
  const source = join(root, "ko/walkthrough.md");
  const markdown = await readFile(source);
  await rename(source, source + ".saving");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("Tutorial validation failed:"));
  expect(onError).toHaveBeenCalled();
  await writeFile(source, markdown);
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toBe(original));
});

it("reports an incomplete image save and recovers when the referenced file arrives", async () => {
  const { root, revisionFile } = await fixture();
  await writeFile(join(root, "en/walkthrough.md"), "# Guide\n\n![Screenshot](../assets/later.png)");
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("Tutorial validation failed:"));
  await writeFile(join(root, "assets/later.png"), Buffer.from([137, 80, 78, 71]));
  await vi.waitFor(async () => expect(await readFile(revisionFile, "utf8")).toContain("tutorialError: string | null = null"));
});
