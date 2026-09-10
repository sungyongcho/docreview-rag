import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DocumentationPage } from "./documentation-page";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/.tutorial/revision", () => ({ tutorialRevision: "test", tutorialError: null }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["ko", "en"] as const)("renders the development outline with honest language and safe references in %s", async (locale) => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const { container } = render(await DocumentationPage({ documentId: "development", locale }));
  const status = screen.getByRole("complementary", { name: locale === "ko" ? "개발 기록 상태" : "Development log status" });
  expect(status).toHaveTextContent(locale === "ko" ? "초안 · 개요" : "Draft / Outline");
  if (locale === "en") expect(status).toHaveTextContent("The article below is the Korean source; an English translation is not available yet.");
  const article = screen.getByRole("article");
  expect(article.parentElement).toHaveAttribute("lang", "ko");
  expect(within(article).getByRole("heading", { level: 1 })).toHaveTextContent("개발 기록 초안");
  const references = article.querySelectorAll('a[href^="https://"]');
  expect(references.length).toBeGreaterThan(0);
  for (const link of references) {
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
  for (const link of container.querySelectorAll('a[href^="/docs/"]')) expect(link).not.toHaveAttribute("target");
  expect(screen.getByRole("link", { name: locale === "ko" ? "개발 기록" : "Development log" })).toHaveAttribute("aria-current", "page");
});


it.each(["en", "ko"] as const)("renders separate visitor and DEV quick starts with purposeful next links (%s)", async (locale) => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  const availability = locale === "ko" ? "이 안내의 사용 범위" : "Guide availability";
  const visitor = render(await DocumentationPage({ documentId: "quickstart", locale }));
  expect(within(screen.getByRole("main")).getByRole("heading", { level: 1 })).toHaveTextContent("Quick Start");
  expect(screen.getByRole("complementary", { name: availability }).querySelector(".development-badge")).toBeNull();
  expect(screen.queryByRole("tablist")).toBeNull();
  expect(visitor.container.querySelector('a[rel="next"]')).toHaveAttribute("href", expect.stringMatching(new RegExp(`^/docs/${locale}/answers/?$`)));
  cleanup();
  const developer = render(await DocumentationPage({ documentId: "quickstart-dev", locale }));
  expect(within(screen.getByRole("main")).getByRole("heading", { level: 1 })).toHaveTextContent("Quick Start for DEV MODE");
  expect(screen.getByRole("complementary", { name: availability }).querySelector(".development-badge")).not.toBeNull();
  expect(screen.getByRole("tab", { name: "Web" })).toHaveAttribute("aria-selected", "true");
  expect(developer.container.querySelectorAll('[id^="qs-web-"]')).toHaveLength(7);
  expect(developer.container.querySelectorAll('[id^="qs-cli-"]')).toHaveLength(7);
  expect(developer.container.querySelector("#qs-setup")).toBeNull();
  expect(developer.container.querySelector('a[rel="next"]')).toHaveAttribute("href", expect.stringMatching(new RegExp(`^/docs/${locale}/retrieval/?$`)));
});
