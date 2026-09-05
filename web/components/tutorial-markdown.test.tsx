import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TutorialMarkdown } from "./tutorial-markdown";
import { renderTutorial } from "@/lib/tutorial-markdown.mjs";

describe("Tutorial Markdown", () => {
  it("expands the beginner path from the registry at the authored marker", () => {
    const parsed = renderTutorial("# Overview\n\n## Learning path {#learning-path}\n\n<!-- tutorial-steps -->", { locale: "en" });
    expect(parsed.links).toHaveLength(12);
    expect(parsed.links[0]).toEqual({ file: "en/environment.md", hash: "step-1" });
    expect(parsed.links[11]).toEqual({ file: "en/snapshots.md", hash: "step-12" });
    const { container } = render(<TutorialMarkdown content={parsed.content} />);
    expect(container.querySelectorAll("ol li")).toHaveLength(12);
    const example = renderTutorial("# Example\n\n```markdown\n<!-- tutorial-steps -->\n```", { locale: "en" });
    expect(example.codes[0].code).toBe("<!-- tutorial-steps -->");
    expect(example.links).toEqual([]);
  });
  it("uses explicit bilingual heading targets and maps legacy walkthrough links", () => {
    const parsed = renderTutorial("# Guide\n\n## 5. Parse {#step-5}\n\n[Legacy](walkthrough.md#4-ingest-the-source-into-documents-and-chunks)", { locale: "en" });
    expect(parsed.headings[1]).toEqual({ id: "step-5", text: "5. Parse", depth: 2 });
    render(<TutorialMarkdown content={parsed.content} />);
    expect(screen.getByRole("link", { name: "Legacy" })).toHaveAttribute("href", "/docreview-rag-agent/docs/en/indexing/#step-5");
    expect(() => renderTutorial("# Guide\n\n## One {#same}\n\n## Two {#same}")).toThrow("Duplicate explicit tutorial heading");
  });
  it("creates unique Korean heading links without treating fenced code as a heading", () => {
    const source = "# 안내\n\n## 첫 단계\n\n## 첫 단계\n\n```sh\n## not a heading\n```";
    expect(renderTutorial(source).headings.map((h) => h.id)).toEqual(["안내", "첫-단계", "첫-단계-2"]);
    const { container } = render(<TutorialMarkdown content={renderTutorial(source).content} />);
    for (const link of container.querySelectorAll<HTMLAnchorElement>("h2 a")) {
      expect(container.querySelector(`[id="${decodeURIComponent(link.hash.slice(1))}"]`)).not.toBeNull();
    }
    expect(container.querySelector("pre code")).toHaveTextContent("## not a heading");
  });

  it("renders tables and images, maps document links, and omits raw HTML", () => {
    const { container } = render(<TutorialMarkdown content={renderTutorial("# 안내\n\n| 키 | 값 |\n| --- | --- |\n| a | b |\n\n[명령](cli.md#설치)\n\n![상태](assets/status.png)\n\n<script>alert(1)</script>").content} />);
    expect(screen.getByRole("table").parentElement).toHaveClass("markdown-table-wrap");
    expect(screen.getByRole("link", { name: "명령" })).toHaveAttribute("href", "/docreview-rag-agent/docs/ko/cli/#%EC%84%A4%EC%B9%98");
    expect(screen.getByAltText("상태")).toHaveAttribute("src", "/docreview-rag-agent/tutorial-assets/status.png");
    expect(container.querySelector("script")).toBeNull();
  });

  it("resolves image references and rejects unsafe or inaccessible resources", () => {
    expect(renderTutorial("![상태][shot]\n\n[shot]: assets/status.png").images).toEqual(["assets/status.png"]);
    for (const source of ["[bad](javascript:alert)", "[repo](../../README.md)", "![bad](assets/../secret.png)", "![bad](assets//outside.png)", "![](assets/status.png)"]) {
      expect(() => renderTutorial(source)).toThrow();
    }
  });

  it.each([["ko", "전체 크기로 보기"], ["en", "Open full size"]] as const)("opens the original image in %s and invalidates replaced image caches", (locale, label) => {
    const { container, rerender } = render(<TutorialMarkdown content={renderTutorial("![Screenshot](assets/status.png)", { locale, assetVersion: "first" }).content} />);
    const image = container.querySelector("img")!;
    const link = image.closest("a")!;
    expect(link).toHaveAttribute("aria-label", `Screenshot · ${label}`);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link.getAttribute("href")).toBe(image.getAttribute("src"));
    expect(image).toHaveAttribute("src", "/docreview-rag-agent/tutorial-assets/status.png?v=first");
    rerender(<TutorialMarkdown content={renderTutorial("![Screenshot](assets/status.png)", { locale, assetVersion: "second" }).content} />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/docreview-rag-agent/tutorial-assets/status.png?v=second");
  });
});
