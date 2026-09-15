import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { renderTutorial } from "@/lib/tutorial-markdown.mjs";

afterEach(cleanup);

it("keeps referenced headings and ordinary Markdown inside accessible details", () => {
  const parsed = renderTutorial("# Guide\n\n<!-- details: limits | Advanced limits -->\n\n## Budget {#budget}\n\n**Measured** attempts.\n\n<!-- /details -->", { locale: "en" });
  const { container } = render(parsed.content);
  const details = container.querySelector('details[data-doc-detail="limits"]');
  expect(details).not.toHaveAttribute("open");
  expect(details?.querySelector("summary")).toHaveTextContent("Advanced limits");
  expect(details?.querySelector("strong")).toHaveTextContent("Measured");
  expect(details?.querySelector("#budget")).toHaveAttribute("data-doc-section", "budget");
  expect(parsed.headings).toContainEqual({ id: "budget", text: "Budget", depth: 2 });
});

it("retains legacy fragments while displaying only the canonical heading", () => {
  const parsed = renderTutorial("# Guide\n\n<!-- heading-alias: 예전-제목 -->\n\n## New title {#stable-topic}");
  const { container } = render(parsed.content);
  expect(container.querySelector("#예전-제목")).toHaveAttribute("data-doc-alias", "stable-topic");
  expect(parsed.headings).toContainEqual({ id: "예전-제목", text: "New title", depth: 0, aliasFor: "stable-topic" });
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
});

it.each(["ko", "en"] as const)("separates the global learning step from the title in %s", (locale) => {
  const parsed = renderTutorial("# Guide\n\n## 9. Ask a question {#step-9}", { locale });
  render(parsed.content);
  expect(screen.getByText(locale === "ko" ? "전체 학습 경로 · 9/12" : "Learning path · 9/12")).toBeInTheDocument();
  expect(parsed.headings.find((heading) => heading.id === "step-9")?.text).toBe("Ask a question");
});

it.each([
  "<!-- details: options | Options -->\n\nNo end",
  "<!-- /details -->",
  "<!-- heading-alias: old -->\n\nNot a heading",
  "<!-- details: options | Options -->\n\n<!-- details: nested | Nested -->\n\n<!-- /details -->\n\n<!-- /details -->",
])("rejects malformed authoring markers", (body) => {
  expect(() => render(renderTutorial(`# Guide\n\n${body}`).content)).toThrow();
});

it("reserves known screenshot dimensions in the image renderer", () => {
  const { container } = render(renderTutorial('# Guide\n\n![Settings](../assets/settings.png)', {
    locale: "en", imageDimensions: { "assets/settings.png": { width: 2880, height: 2000 } },
    renderImage: ({ src, alt, width, height }) => <img src={src} alt={alt} width={width} height={height} />,
  }).content);
  expect(container.querySelector("img")).toHaveAttribute("width", "2880");
  expect(container.querySelector("img")).toHaveAttribute("height", "2000");
});
