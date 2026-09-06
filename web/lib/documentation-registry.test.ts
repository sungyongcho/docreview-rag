import { describe, expect, it } from "vitest";
import { DEVELOPMENT_STORY_SOURCE, DOCUMENTATION_REGISTRY, DOCUMENTS, developmentStoryDocument, documentationLink, legacyDocumentationTarget, localizedDocumentationRoute, validateDocumentationRegistry } from "./documentation-registry.mjs";

describe("documentation registry", () => {
  it("provides sixteen paired documents and twelve unique tutorial steps", () => {
    expect(validateDocumentationRegistry()).toBe(DOCUMENTATION_REGISTRY);
    expect(DOCUMENTS).toHaveLength(32);
    for (const locale of ["ko", "en"]) {
      const documents = DOCUMENTS.filter((document) => document.locale === locale);
      expect(documents).toHaveLength(16);
      expect(documents.flatMap((document) => document.steps.map((step) => step.number)).sort((a, b) => a - b)).toEqual(Array.from({ length: 12 }, (_, index) => index + 1));
      expect(documents.flatMap((document) => document.steps.map((step) => step.number))).toEqual(Array.from({ length: 12 }, (_, index) => index + 1));
    }
  });

  it.each(["ID", "slug", "step", "related"])("rejects conflicting %s entries", (kind) => {
    const registry = structuredClone(DOCUMENTATION_REGISTRY);
    if (kind === "ID") registry.documents[1].id = registry.documents[0].id;
    if (kind === "slug") registry.documents[1].slug = registry.documents[0].slug;
    if (kind === "step") registry.documents[2].steps = structuredClone(registry.documents[1].steps);
    if (kind === "related") registry.documents[0].related.push("missing");
    expect(() => validateDocumentationRegistry(registry)).toThrow();
  });

  it("maps old walkthrough links to focused bilingual sections", () => {
    expect(documentationLink("walkthrough.md", "5-prepare-embeddings-and-bm25", "en")).toMatchObject({ document: { id: "indexing" }, hash: "step-6" });
    expect(legacyDocumentationTarget("ko", "#빠른-평가-실행하기")).toMatchObject({ document: { id: "evaluation" }, hash: "step-11" });
    expect(legacyDocumentationTarget("ko", "#run-a-quick-evaluation")).toMatchObject({ document: { id: "evaluation", locale: "ko" }, hash: "step-11" });
    expect(documentationLink("../../README.md", "", "en")).toBeNull();
  });

  it("preserves focused document identity and stable anchors across locales", () => {
    expect(localizedDocumentationRoute("/docreview-rag-agent/docs/en/indexing/", "ko", "#step-7")).toBe("/docreview-rag-agent/docs/ko/indexing/#step-7");
    expect(localizedDocumentationRoute("/docs/en/", "ko", "#1-open-the-development-environment")).toBe("/docs/ko/environment/#step-1");
    expect(localizedDocumentationRoute("/docs/ko/cli/", "en", "#초기-schema-준비")).toBe("/docs/en/cli/#initial-schema-setup");
    expect(localizedDocumentationRoute("/docs/cli/", "en", "#초기-schema-준비")).toBe("/docs/en/cli/#initial-schema-setup");
    expect(localizedDocumentationRoute("/docs/en/ollama/", "ko", "#diagnostics")).toBe("/docs/ko/ollama/#diagnostics");
    expect(localizedDocumentationRoute("/docs/en/unknown/", "ko")).toBeNull();
  });

  it("keeps the Korean development draft separate and preserves its route during language changes", () => {
    expect(developmentStoryDocument("ko")).toMatchObject({ title: "개발 기록", file: DEVELOPMENT_STORY_SOURCE });
    expect(developmentStoryDocument("en")).toMatchObject({ title: "Development log", file: DEVELOPMENT_STORY_SOURCE });
    expect(DOCUMENTS).toHaveLength(32);
    expect(localizedDocumentationRoute("/docreview-rag-agent/docs/ko/development/", "en", "#References")).toBe("/docreview-rag-agent/docs/en/development/#References");
    expect(localizedDocumentationRoute("/docs/en/development/", "ko", "#시작과-학습")).toBe(`/docs/ko/development/#${encodeURIComponent("시작과-학습")}`);
  });
});
