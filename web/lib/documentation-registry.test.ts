import { readFileSync } from "node:fs";
import { renderTutorial } from "./tutorial-markdown.mjs";
import { describe, expect, it } from "vitest";
import { DEVELOPMENT_STORY_SOURCES, DOCUMENTATION_REGISTRY, DOCUMENTS, developmentStoryDocument, documentationLink, localizedDocumentationRoute, validateDocumentationRegistry } from "./documentation-registry.mjs";

describe("documentation registry", () => {
  it("provides seventeen paired documents and twelve unique tutorial steps", () => {
    expect(validateDocumentationRegistry()).toBe(DOCUMENTATION_REGISTRY);
    expect(DOCUMENTS).toHaveLength(34);
    for (const locale of ["ko", "en"]) {
      const documents = DOCUMENTS.filter((document) => document.locale === locale);
      expect(documents).toHaveLength(17);
      expect(documents.flatMap((document) => document.steps.map((step) => step.number)).sort((a, b) => a - b)).toEqual(Array.from({ length: 12 }, (_, index) => index + 1));
      expect(documents.map((document) => document.id)).toEqual(["overview", "environment", "quickstart", "quickstart-dev", "answers", "retrieval", "documents", "acquisition", "indexing", "evaluation", "snapshots", "settings", "runtime", "troubleshooting", "architecture", "cli", "ollama"]);
    }
  });

  it.each(["ID", "slug", "step", "related"])("rejects conflicting %s entries", (kind) => {
    const registry = structuredClone(DOCUMENTATION_REGISTRY);
    if (kind === "ID") registry.documents[1].id = registry.documents[0].id;
    if (kind === "slug") registry.documents[1].slug = registry.documents[0].slug;
    if (kind === "step") registry.documents.find((document) => document.id === "quickstart")!.steps = structuredClone(registry.documents.find((document) => document.id === "environment")!.steps);
    if (kind === "related") registry.documents[0].related.push("missing");
    expect(() => validateDocumentationRegistry(registry)).toThrow();
  });

  it("resolves only registered Markdown files", () => {
    expect(documentationLink("indexing.md", "step-6", "en")).toMatchObject({ document: { id: "indexing", locale: "en" }, hash: "step-6" });
    expect(documentationLink("../../README.md", "", "en")).toBeNull();
  });

  it("preserves focused document identity and stable anchors across locales", () => {
    expect(localizedDocumentationRoute("/docreview-rag/docs/en/indexing/", "ko", "#step-7")).toBe("/docreview-rag/docs/ko/indexing/#step-7");
    expect(localizedDocumentationRoute("/docs/ko/cli/", "en", "#초기-schema-준비")).toBe("/docs/en/cli/#initial-schema-setup");
    expect(localizedDocumentationRoute("/docs/cli/", "en", "#초기-schema-준비")).toBe("/docs/en/cli/#initial-schema-setup");
    expect(localizedDocumentationRoute("/docs/en/ollama/", "ko", "#diagnostics")).toBe("/docs/ko/ollama/#diagnostics");
    expect(localizedDocumentationRoute("/docs/en/unknown/", "ko")).toBeNull();
  });

  it.each(["en", "ko"] as const)("keeps Quick Start anchors on their own documents (%s)", (locale) => {
    expect(documentationLink("quickstart.md", "qs-app-1", locale)).toMatchObject({ document: { id: "quickstart" }, hash: "qs-app-1" });
    expect(localizedDocumentationRoute("/docs/en/quickstart-dev/", locale, "#qs-web-4")).toBe(`/docs/${locale}/quickstart-dev/#qs-web-4`);
  });

  it("keeps the Korean development draft separate and preserves its route during language changes", () => {
    expect(developmentStoryDocument("ko")).toMatchObject({ title: "개발 기록", file: DEVELOPMENT_STORY_SOURCES.ko });
    expect(developmentStoryDocument("en")).toMatchObject({ title: "Development log", file: DEVELOPMENT_STORY_SOURCES.en });
    expect(DOCUMENTS.some((document) => document.id === developmentStoryDocument("ko").id)).toBe(false);
    expect(localizedDocumentationRoute("/docreview-rag/docs/ko/development/", "en", "#References")).toBe("/docreview-rag/docs/en/development/#References");
    expect(localizedDocumentationRoute("/docs/en/development/", "ko", "#시작과-학습")).toBe(`/docs/ko/development/#${encodeURIComponent("시작과-학습")}`);
  });
});

it.each(["en", "ko"] as const)("preserves the progress/queue section when changing language from %s", (locale) => {
  const other = locale === "en" ? "ko" : "en";
  const headings = renderTutorial(readFileSync(`../docs/TUTORIAL/${locale}/indexing.md`, "utf8"), { locale }).headings;
  expect(headings.some((heading) => heading.id === "job-progress")).toBe(true);
  const destination = localizedDocumentationRoute(`/docreview-rag/docs/${locale}/indexing/`, other, "#job-progress")!;
  const target = renderTutorial(readFileSync(`../docs/TUTORIAL/${other}/indexing.md`, "utf8"), { locale: other }).headings;
  const fragment = decodeURIComponent(destination.split("#")[1]);
  expect(target.some((heading) => heading.id === fragment)).toBe(true);
});
