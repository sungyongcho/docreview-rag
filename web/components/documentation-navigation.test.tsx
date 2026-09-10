import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DOCUMENTS } from "@/lib/documentation-registry.mjs";
import { DocumentationLegacyAnchor, DocumentationMenu, DocumentationOutline, DocumentationRedirect } from "./documentation-navigation";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("documentation navigation", () => {
  it("groups all registered documents and keeps the collections always expanded", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const { container } = render(<DocumentationMenu current="indexing" locale="en" documents={DOCUMENTS.filter((document) => document.locale === "en")} />);
    expect(container.querySelector("details")).toBeNull();
    expect(within(container.querySelector(".docs-menu") as HTMLElement).getByText("Guides & development")).toBeInTheDocument();
    const links = screen.getByRole("navigation", { name: "Choose a document" }).querySelectorAll("a");
    expect(links).toHaveLength(16);
    expect(container.querySelectorAll(".docs-nav-group h2")).toHaveLength(5);
    expect(container.querySelector('a[aria-current="page"]')).toHaveTextContent("Indexing");
    expect(container.querySelector('a[aria-current="page"]')?.getAttribute("href")).toMatch(/^\/docs\/en\/indexing\/?$/);
    expect(container.querySelector('a[aria-current="page"] .development-badge')).toHaveAttribute("aria-label", "DEV only");
    expect(screen.getByRole("link", { name: "Documents" }).querySelector(".development-badge")).toBeNull();
    const collections = within(screen.getByRole("navigation", { name: "Guides & development" }));
    expect(collections.getByRole("link", { name: "User guide" })).toHaveAttribute("href", "/docs/en");
    expect(collections.getByRole("link", { name: "Development log" })).toHaveAttribute("href", "/docs/en/development");
    for (const link of collections.getAllByRole("link")) expect(link).not.toHaveAttribute("target");
  });

  it.each(["en", "ko"] as const)("orders the three starting guides and marks the developer quick start (%s)", (locale) => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const { container } = render(<DocumentationMenu current="quickstart" locale={locale} documents={DOCUMENTS.filter((document) => document.locale === locale)} />);
    const links = container.querySelector('[aria-labelledby="docs-group-start"]')!.querySelectorAll("a");
    expect(Array.from(links, (link) => link.getAttribute("href")?.replace(/\/$/, ""))).toEqual([`/docs/${locale}/environment`, `/docs/${locale}/quickstart`, `/docs/${locale}/quickstart-dev`]);
    expect(Array.from(links, (link) => Boolean(link.querySelector(".development-badge")))).toEqual([false, false, true]);
    expect(links[2]).toHaveTextContent("Quick Start for");
  });

  it.each(["qs-setup", "qs-web-4"])("redirects an old Quick Start bookmark %s without changing its checkpoint", (anchor) => {
    window.history.replaceState({}, "", `/docreview-rag-agent/docs/en/quickstart/#${anchor}`);
    render(<DocumentationLegacyAnchor locale="en" />);
    expect(navigation.replace).toHaveBeenCalledWith(`/docs/en/${anchor === "qs-setup" ? "environment" : "quickstart-dev"}/#${anchor}`);
  });

  it("marks the Korean development log without hiding the user guide", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    render(<DocumentationMenu current="development" locale="ko" documents={DOCUMENTS.filter((document) => document.locale === "ko")} />);
    expect(screen.getByRole("link", { name: "개발 기록" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("navigation", { name: "문서 선택" }).querySelectorAll("a")).toHaveLength(16);
  });

  it("lists only second-level sections without a disclosure toggle", () => {
    const { container } = render(<DocumentationOutline locale="en" headings={[{ id: "title", text: "Title", depth: 1 }, { id: "step-5", text: "Parse", depth: 2 }, { id: "detail", text: "Detail", depth: 3 }]} />);
    expect(container.querySelector("details")).toBeNull();
    expect(container.querySelector(".docs-outline-title")).toHaveTextContent("On this page");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Parse" })).toHaveAttribute("href", "#step-5");
  });

  it("redirects an old localized walkthrough anchor to its new section", () => {
    window.history.replaceState({}, "", "/docreview-rag-agent/docs/en/#run-a-quick-evaluation");
    render(<DocumentationLegacyAnchor locale="en" />);
    expect(navigation.replace).toHaveBeenCalledWith("/docs/en/evaluation/#step-11");
  });

  it("preserves an old root fragment when resolving the saved language", () => {
    localStorage.setItem("docreview.locale", "ko");
    window.history.replaceState({}, "", "/docreview-rag-agent/docs/#전체-초기화가-필요할-때");
    render(<DocumentationRedirect documentId="overview" />);
    expect(navigation.replace).toHaveBeenCalledWith("/docs/ko/troubleshooting/#reset");
  });

  it("translates a legacy CLI fragment when the saved language differs", () => {
    localStorage.setItem("docreview.locale", "en");
    window.history.replaceState({}, "", "/docreview-rag-agent/docs/cli/#초기-schema-준비");
    render(<DocumentationRedirect documentId="cli" />);
    expect(navigation.replace).toHaveBeenCalledWith("/docs/en/cli/#initial-schema-setup");
  });
});
