import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { DEVELOPMENT_STORY_SOURCE, documentationDocuments } from "../lib/documentation-registry.mjs";
import { DOCUMENTATION_REGISTRY_FILE, prepareTutorial, readDocumentationRegistry, writeTutorialRevision } from "./prepare-tutorial.mjs";

/** Content polling catches editor replacement saves and mounted image changes. */
async function fingerprint(root, registryFile) {
  const digest = createHash("sha256");
  const registry = await readDocumentationRegistry(registryFile);
  digest.update(JSON.stringify(registry));
  async function add(file) {
    digest.update(file + "\0");
    try { digest.update(await readFile(resolve(root, file))); }
    catch (reason) { digest.update(String(reason.code)); }
  }
  async function assets(directory) {
    let entries;
    try { entries = await readdir(resolve(root, directory), { withFileTypes: true }); }
    catch (reason) {
      if (reason.code !== "ENOENT") throw reason;
      return;
    }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const file = directory + "/" + entry.name;
      if (entry.isDirectory()) await assets(file);
      else if (entry.isFile()) await add(file);
    }
  }
  for (const document of documentationDocuments(registry)) await add(document.file);
  await add(DEVELOPMENT_STORY_SOURCE);
  await assets("assets");
  return digest.digest("hex");
}

/** Refresh a generated dependency; Next HMR owns delivery to open documents. */
export async function watchTutorial({ root = resolve(process.cwd(), "../docs/TUTORIAL"), output = resolve(process.cwd(), "public/tutorial-assets"), revisionFile = resolve(process.cwd(), ".tutorial/revision.ts"), registryFile = DOCUMENTATION_REGISTRY_FILE, intervalMs = 750, onError = console.error } = {}) {
  let previous;
  let lastError;
  let stopped = false;
  let timer;
  let pending = Promise.resolve();
  async function update() {
    try {
      const current = await fingerprint(root, registryFile);
      if (current === previous && !lastError) return;
      await prepareTutorial(root, output, revisionFile, { registryFile });
      previous = current;
      lastError = undefined;
    } catch (reason) {
      const message = "Tutorial validation failed: " + (reason instanceof Error ? reason.message : String(reason));
      await writeTutorialRevision(revisionFile, "invalid", message);
      if (message !== lastError) onError(message);
      lastError = message;
    }
  }
  function schedule() {
    if (stopped) return;
    timer = setTimeout(() => {
      pending = update().finally(schedule);
    }, intervalMs);
  }
  pending = update();
  await pending;
  schedule();
  return async () => { stopped = true; clearTimeout(timer); await pending; };
}
