import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { DEVELOPMENT_STORY_SOURCES, DOCUMENTATION_REGISTRY, documentationDocuments } from "../lib/documentation-registry.mjs";

/** Build valid isolated source fixtures with every registered compatibility target. */
export async function writeTutorialFixtures(root, registry = DOCUMENTATION_REGISTRY) {
  for (const storyFile of Object.values(DEVELOPMENT_STORY_SOURCES)) {
    await writeFile(join(root, storyFile), "# Development log draft\n\n## References\n\n[Reference](https://example.com/reference)");
  }
  for (const document of documentationDocuments(registry)) {
    const anchors = new Set([...document.steps.map((step) => step.anchor), ...Object.values(document.legacyAnchors?.[document.locale] ?? {})].filter(Boolean));
    const source = [`# ${document.title}`, "Original paragraph.", ...[...anchors].map((anchor) => `## Section {#${anchor}}`)];
    for (const section of document.localizedSections ?? []) source.push(`## ${section[document.locale]}`);
    if (document.id === "cli") source.push("## Setup {#setup}");
    const file = join(root, document.file);
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, source.join("\n\n"));
  }
}
