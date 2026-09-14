import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import bookmarks from "./documentation-bookmarks.json";
import { renderTutorial } from "./tutorial-markdown.mjs";

const root = resolve(process.cwd(), "../docs/TUTORIAL");

it.each(Object.entries(bookmarks))("preserves existing bookmarks in %s", (file, previous) => {
  const parsed = renderTutorial(readFileSync(resolve(root, file), "utf8"), { locale: file.startsWith("en/") || file.endsWith(".en.md") ? "en" : "ko" });
  const ids = new Set(parsed.headings.map((heading) => heading.id));
  expect(previous.filter((id) => !ids.has(id))).toEqual([]);
  expect(parsed.headings.filter((heading) => heading.depth === 1)).toHaveLength(1);
});

it.each(Object.keys(bookmarks).filter((file) => file.startsWith("en/")))("pairs canonical reading sections for %s", (file) => {
  const sections = (source: string, locale: "ko" | "en") => renderTutorial(readFileSync(resolve(root, source), "utf8"), { locale }).headings
    .filter((heading) => heading.depth >= 2 && heading.depth <= 4 && heading.text !== "SCREENSHOT NEEDED")
    .map((heading) => heading.id);
  expect(sections(file, "en")).toEqual(sections(file.replace(/^en\//, "ko/"), "ko"));
  const details = (source: string) => [...readFileSync(resolve(root, source), "utf8").matchAll(/<!-- details: ([a-z][a-z0-9-]*) \|/g)].map((match) => match[1]).sort();
  expect(details(file)).toEqual(details(file.replace(/^en\//, "ko/")));
});
