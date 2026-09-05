import { readFile, readdir, mkdir, writeFile, rename, copyFile, realpath, stat, chown, rm } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { resolve, dirname, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { DOCUMENTS, renderTutorial } from "../lib/tutorial-markdown.mjs";

/** Match new generated directories to their bind-mounted parent's owner. */
async function generatedDirectory(directory, owner) {
  const first = await mkdir(directory, { recursive: true });
  if (!first || process.getuid?.() !== 0) return;
  for (let current = directory; ; current = dirname(current)) {
    await chown(current, owner.uid, owner.gid);
    if (current === first) break;
  }
}

/** Find the existing parent when an empty public directory is absent from Git. */
async function generatedDirectoryOwner(directory) {
  for (let parent = dirname(directory); ; parent = dirname(parent)) {
    try { return await stat(parent); }
    catch (reason) { if (reason.code !== "ENOENT" || parent === dirname(parent)) throw reason; }
  }
}

/** Update Next's imported dependency only after the canonical sources validate. */
export async function writeTutorialRevision(file, revision, error = null) {
  const content = `// Generated from canonical tutorial sources. Do not edit.\nexport const tutorialRevision = ${JSON.stringify(revision)};\nexport const tutorialError: string | null = ${JSON.stringify(error)};\n`;
  let previous;
  try { previous = await readFile(file, "utf8"); }
  catch (reason) { if (reason.code !== "ENOENT") throw reason; }
  if (previous === content) return;
  await generatedDirectory(dirname(file), await stat(dirname(dirname(file))));
  const temporary = `${file}.${randomUUID()}.tmp`;
  await writeFile(temporary, content);
  await rename(temporary, file);
}

export async function prepareTutorial(root = resolve(process.cwd(), "../docs/TUTORIAL"), output = resolve(process.cwd(), "public/tutorial-assets"), revisionFile = null) {
  const documents = new Map();
  const digest = createHash("sha256");
  for (const item of DOCUMENTS) {
    const source = await readFile(resolve(root, item.file), "utf8");
    digest.update(item.file + "\0" + source + "\0");
    documents.set(item.file, renderTutorial(source, { locale: item.locale }));
  }
  const copies = new Map();
  for (const [file, document] of documents) {
    for (const link of document.links) {
      if (link.hash && !documents.get(link.file ?? file).headings.some((h) => h.id === link.hash)) throw new Error(`Missing tutorial heading: ${link.file ?? file}#${link.hash}`);
    }
    for (const path of document.images) {
      const assetsRoot = await realpath(resolve(root, "assets"));
      const source = await realpath(resolve(root, path));
      if (!source.startsWith(assetsRoot + sep)) throw new Error(`Image escapes tutorial assets: ${path}`);
      copies.set(source, resolve(output, path.slice(7)));
    }
  }
  for (const [source, target] of copies) digest.update(target.slice(output.length) + "\0").update(await readFile(source));
  // Keep the shared directory's ownership when host and container builders alternate.
  const owner = await generatedDirectoryOwner(output);
  await generatedDirectory(output, owner);
  for (const [source, target] of copies) {
    await generatedDirectory(dirname(target), owner);
    const temporary = `${target}.${randomUUID()}.tmp`;
    await copyFile(source, temporary);
    await rename(temporary, target);
  }
  const targets = new Set(copies.values());
  async function removeStale(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const target = resolve(directory, entry.name);
      if (entry.isDirectory()) await removeStale(target);
      else if (!entry.name.endsWith(".tmp") && !targets.has(target)) await rm(target, { force: true });
    }
  }
  await removeStale(output);
  if (revisionFile) await writeTutorialRevision(revisionFile, digest.digest("hex"));
  return { documents: documents.size, images: copies.size };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log("Tutorial sources ready:", await prepareTutorial(undefined, undefined, resolve(process.cwd(), ".tutorial/revision.ts")));
}
