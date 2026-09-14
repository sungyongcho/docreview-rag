import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { splitQuickStart } from "./quickstart-markdown.mjs";
import { renderTutorial } from "./tutorial-markdown.mjs";

/** Read a canonical localized guide without using a generated copy. */
function source(locale: "en" | "ko", name: string): string {
  return readFileSync(resolve(process.cwd(), `../docs/TUTORIAL/${locale}/${name}.md`), "utf8");
}

/** Preserve the ordered inline technical terms separately from complete code blocks. */
function inlineCodes(markdown: string): string[] {
  return Array.from(markdown.replace(/```[\s\S]*?```/g, "").matchAll(/(?<!`)`([^`\n]+)`(?!`)/g), (match) => match[1]);
}

describe("split quick start guides", () => {
  it.each(["overview", "environment", "quickstart", "quickstart-dev"])("keeps localized structure, checkpoint IDs and technical instructions aligned for %s", (name) => {
    const en = source("en", name); const ko = source("ko", name);
    const english = renderTutorial(en, { locale: "en" }); const korean = renderTutorial(ko, { locale: "ko" });
    // Legacy bookmark aliases differ by locale and are not visible heading levels.
    expect(english.headings.filter((heading) => heading.depth > 0).map((heading) => heading.depth)).toEqual(korean.headings.filter((heading) => heading.depth > 0).map((heading) => heading.depth));
    expect(Array.from(en.matchAll(/\{#([a-z][a-z0-9-]*)\}/g), (match) => match[1])).toEqual(Array.from(ko.matchAll(/\{#([a-z][a-z0-9-]*)\}/g), (match) => match[1]));
    expect(english.codes).toEqual(korean.codes);
    expect(inlineCodes(en)).toEqual(inlineCodes(ko));
    const images = (text: string) => Array.from(text.matchAll(/!\[[^\]]*\]\(\.\.\/assets\/([a-z0-9.-]+)\)/g), (m) => m[1]);
    expect(images(en).map((name) => name.replace(/\.en\.png$/, ""))).toEqual(images(ko).map((name) => name.replace(/\.ko\.png$/, "")));
  });

  it.each(["en", "ko"] as const)("separates setup, the seven preparation steps, and visitor actions (%s)", (locale) => {
    const environment = source(locale, "environment"); const developer = source(locale, "quickstart-dev"); const visitor = source(locale, "quickstart");
    const sections = splitQuickStart(developer);
    expect(environment.indexOf("{#qs-setup}")).toBeLessThan(environment.indexOf("{#schema-recovery}"));
    expect(environment).toContain("git clone https://github.com/sungyongcho/docreview-rag.git");
    expect(environment).toContain("source ./rag-alias.sh\nrag-help\nrag-dev start");
    expect(environment).toContain("OPENAI_API_KEY_LOCAL=<your-own-openai-development-key>");
    expect(environment).toContain("{#open-build}");
    for (const mode of ["cli", "web"] as const) expect(Array.from(sections[mode].matchAll(/\{#qs-(?:cli|web)-(\d+)\}/g), (match) => Number(match[1]))).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(developer).not.toContain("git clone"); expect(developer).not.toContain("{#qs-setup}");
    expect(sections.common).toContain("environment.md#qs-setup");
    expect(visitor).not.toMatch(/git clone|rag-dev start|\[!DEV\]|```(?:bash|dotenv)|qs-cli|qs-web/);
    expect(Array.from(visitor.matchAll(/\{#qs-app-(\d+)\}/g), (match) => Number(match[1]))).toEqual([1, 2, 3, 4, 5]);
    expect(visitor).toContain("answers.md"); expect(visitor).toContain("documents.md#visibility"); expect(visitor).toContain("snapshots.md#comparison");
  });
});
