import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DocumentationPage } from "./documentation-page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), prefetch: vi.fn() }), usePathname: () => "/docs/ko/answers/" }));
vi.mock("@/.tutorial/revision", () => ({ tutorialRevision: "test", tutorialError: null }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["ko", "en"] as const)("renders the development outline with honest language and safe references in %s", async (locale) => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const { container } = render(await DocumentationPage({ documentId: "development", locale }));
  const status = screen.getByRole("complementary", { name: locale === "ko" ? "개발 기록 상태" : "Development log status" });
  expect(status).toHaveTextContent(locale === "ko" ? "초안 · 개요" : "Draft / Outline");
  if (locale === "en") expect(status).toHaveTextContent("A working draft the author is still revising");
  const article = screen.getByRole("article");
  expect(article.parentElement).toHaveAttribute("lang", locale);
  expect(within(article).getByRole("heading", { level: 1 })).toHaveTextContent(locale === "ko" ? "개발 기록" : "Development Log");
  const references = article.querySelectorAll('a[href^="https://"]');
  expect(references.length).toBeGreaterThan(0);
  for (const link of references) {
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
  for (const link of container.querySelectorAll('a[href^="/docs/"]')) expect(link).not.toHaveAttribute("target");
  expect(screen.getByRole("link", { name: locale === "ko" ? "개발 기록" : "Development log" })).toHaveAttribute("aria-current", "page");
});


it.each(["ko", "en"] as const)("places the settings captures with a separate narrow-screen detail figure (%s)", async (locale) => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const { container } = render(await DocumentationPage({ documentId: "settings", locale }));
  const caps = container.querySelector(`[data-capture-id="openai-per-call-caps-editor"]`)!;
  expect(caps.querySelector("img")).toHaveAttribute("src", expect.stringContaining(`assets/captures/openai-per-call-caps-editor.${locale}.png`));
  expect(caps.querySelectorAll(".tutorial-image-callout")).toHaveLength(2);
  for (const id of ["conversation-evidence-policy", "conversation-run-limits"]) {
    const figure = container.querySelector(`[data-capture-id="${id}"]`)!;
    expect(figure.querySelector("img")).toHaveAttribute("src", expect.stringContaining(`assets/captures/${id}.${locale}.png`));
    expect(figure.querySelector("source")).toHaveAttribute("srcset", expect.stringContaining(`${id}.${locale}.mobile.png`));
    // The narrow main crop stops before the second target, which gets its own figure below it.
    expect(figure.querySelectorAll(".tutorial-image-callouts:not(.tutorial-image-callouts-mobile) .tutorial-image-callout")).toHaveLength(2);
    expect(figure.querySelectorAll(".tutorial-image-callouts-mobile .tutorial-image-callout")).toHaveLength(1);
    const detail = container.querySelector(`.tutorial-image-narrow-only [data-capture-id="${id}-mobile-detail"]`)!;
    expect(detail.querySelector("img")).toHaveAttribute("src", expect.stringContaining(`${id}.${locale}.mobile-detail.png`));
    expect(detail.querySelectorAll(".tutorial-image-callout")).toHaveLength(1);
    expect(detail.querySelector("source")).toBeNull();
  }
});

it.each(["en", "ko"] as const)("renders separate visitor and DEV quick starts with purposeful next links (%s)", async (locale) => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const availability = locale === "ko" ? "이 안내의 사용 범위" : "Guide availability";
  const visitor = render(await DocumentationPage({ documentId: "quickstart", locale }));
  expect(within(screen.getByRole("main")).getByRole("heading", { level: 1 })).toHaveTextContent("Quick Start");
  expect(screen.getByRole("complementary", { name: availability }).querySelector(".development-badge")).toBeNull();
  expect(screen.getByRole("navigation", { name: locale === "ko" ? "현재 위치" : "Breadcrumb" }).querySelector(".development-badge")).toBeNull();
  expect(screen.queryByRole("tablist")).toBeNull();
  expect(visitor.container.querySelector('a[rel="next"]')).toHaveAttribute("href", expect.stringMatching(new RegExp(`^/docs/${locale}/answers/?$`)));
  cleanup();
  const developer = render(await DocumentationPage({ documentId: "quickstart-dev", locale }));
  expect(within(screen.getByRole("main")).getByRole("heading", { level: 1 })).toHaveTextContent("Quick Start for DEV MODE");
  expect(screen.getByRole("complementary", { name: availability }).querySelector(".development-badge")).not.toBeNull();
  expect(screen.getByRole("navigation", { name: locale === "ko" ? "현재 위치" : "Breadcrumb" }).querySelector(".development-badge")).toHaveTextContent("DEV MODE");
  expect(screen.getByRole("tab", { name: "Web" })).toHaveAttribute("aria-selected", "true");
  expect(developer.container.querySelectorAll('[id^="qs-web-"]')).toHaveLength(7);
  expect(developer.container.querySelectorAll('[id^="qs-cli-"]')).toHaveLength(7);
  expect(developer.container.querySelector("#qs-setup")).toBeNull();
  expect(developer.container.querySelector('a[rel="next"]')).toHaveAttribute("href", expect.stringMatching(new RegExp(`^/docs/${locale}/retrieval/?$`)));
});
