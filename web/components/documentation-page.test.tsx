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
