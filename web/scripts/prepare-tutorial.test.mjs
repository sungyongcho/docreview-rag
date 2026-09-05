// @vitest-environment node
import { mkdtemp, mkdir, writeFile, readFile, readdir, stat, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { prepareTutorial } from "./prepare-tutorial.mjs";
import { writeTutorialFixtures } from "./tutorial-test-support.mjs";

const directories = [];
afterEach(async () => { for (const path of directories.splice(0)) await rm(path, { recursive: true, force: true }); });

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "docreview-tutorial-test-"));
  directories.push(root);
  await mkdir(join(root, "assets"));
  await writeTutorialFixtures(root);
  for (const locale of ["ko", "en"]) {
    const file = join(root, locale, "overview.md");
    await writeFile(file, await readFile(file, "utf8") + "\n\n[CLI](cli.md#setup)\n\n![Status](../assets/status.png)");
  }
  // A real 1x1 PNG exercises binary copying, without adding a fake tutorial screenshot.
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=", "base64");
  await writeFile(join(root, "assets/status.png"), png);
  await writeFile(join(root, "assets/unused.png"), png);
  return { root, output: join(root, "output"), png };
}

it("copies only referenced assets and clears stale generated copies", async () => {
  const { root, output, png } = await fixture();
  expect(await prepareTutorial(root, output)).toEqual({ documents: 30, images: 1 });
  expect(await readFile(join(output, "status.png"))).toEqual(png);
  expect(await readdir(output)).toEqual(["status.png"]);
  const originalDirectory = await stat(output);
  await writeTutorialFixtures(root);
  await prepareTutorial(root, output);
  expect(await readdir(output)).toEqual([]);
  expect((await stat(output)).ino).toBe(originalDirectory.ino);
});

it("prepares a fresh checkout without an untracked public directory", async () => {
  const { root, png } = await fixture();
  const web = join(root, "web");
  await mkdir(web);
  const output = join(web, "public/tutorial-assets");
  expect(await prepareTutorial(root, output)).toEqual({ documents: 30, images: 1 });
  expect(await readFile(join(output, "status.png"))).toEqual(png);
  expect((await stat(output)).uid).toBe((await stat(web)).uid);
});

it("rejects undeclared steps and missing registered step anchors before creating output", async () => {
  const { root, output } = await fixture();
  await writeFile(join(root, "en", "indexing.md"), "# Indexing\n\n## Unexpected {#step-42}");
  await expect(prepareTutorial(root, output)).rejects.toThrow("Undeclared tutorial step");
  await writeFile(join(root, "en", "indexing.md"), "# Indexing");
  await expect(prepareTutorial(root, output)).rejects.toThrow("Missing tutorial heading: en/indexing.md#step-5");
  await expect(stat(output)).rejects.toMatchObject({ code: "ENOENT" });
});

it("fails for missing documents, images, and cross-document headings", async () => {
  const { root, output } = await fixture();
  const cli = await readFile(join(root, "ko", "cli.md"), "utf8");
  await writeFile(join(root, "ko", "cli.md"), cli.replace("## Setup {#setup}", ""));
  await expect(prepareTutorial(root, output)).rejects.toThrow("Missing tutorial heading");
  await writeFile(join(root, "ko", "cli.md"), cli);
  await rm(join(root, "assets/status.png"));
  await expect(prepareTutorial(root, output)).rejects.toThrow();
  await rm(join(root, "ko", "cli.md"));
  await expect(prepareTutorial(root, output)).rejects.toThrow();
});
