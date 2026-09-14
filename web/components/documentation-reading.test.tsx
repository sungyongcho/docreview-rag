import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { consumeReadingState, latestReadingState, rememberReadingState } from "@/lib/documentation-reading";
import { I18nProvider, LOCALE_KEY, useI18n, type Locale } from "@/lib/i18n";
import { DocumentationLanguageSwitch, DocumentationReadingBoundary } from "./documentation-reading";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), prefetch: vi.fn() }));
const current = vi.hoisted(() => ({ pathname: "/docs/ko/cli/" }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation, usePathname: () => current.pathname }));

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  current.pathname = "/docs/ko/cli/";
  Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
  localStorage.clear();
  sessionStorage.clear();
  consumeReadingState("__none__");
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

function stubRects(rects: Record<string, { top?: number; bottom?: number }>) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const entry = rects[this.id] ?? {};
    const top = entry.top ?? 0;
    const bottom = entry.bottom ?? top;
    return { top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  });
}

function stubScrollY(value: number) {
  Object.defineProperty(window, "scrollY", { value, configurable: true });
}

function DocsPage({ locale = "ko", documentId = "cli" }: { locale?: Locale; documentId?: string }) {
  return <DocumentationReadingBoundary documentId={documentId} locale={locale}>
    <header className="docs-header" id="page-header" />
    <main id="docs-content" data-document-id={documentId} data-document-locale={locale}>
      <DocumentationLanguageSwitch locale={locale} />
      <h2 id="install" data-doc-section="install">Install</h2>
      <h3 id="install-cli" data-doc-section="install-cli">CLI install</h3>
      <details data-doc-detail="extra"><summary>Extra</summary><h3 id="detail-note" data-doc-section="detail-note">Note</h3></details>
      <h2 id="usage" data-doc-section="usage">Usage</h2>
      <LocaleProbe />
    </main>
  </DocumentationReadingBoundary>;
}

function LocaleProbe() {
  const { locale } = useI18n();
  return <output data-testid="locale">{locale}</output>;
}

describe("DocumentationLanguageSwitch", () => {
  it("replaces the localized route through the client router without a full reload", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/?view=grid#old");
    stubRects({ "page-header": { bottom: 60 }, install: { top: 30 }, "install-cli": { top: 400 }, "detail-note": { top: 700 }, usage: { top: 900 }, "docs-content": { top: 20, bottom: 2000 } });
    render(<I18nProvider><DocsPage /></I18nProvider>);
    expect(navigation.prefetch).toHaveBeenCalledWith("/docs/en/cli/");
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(navigation.replace).toHaveBeenCalledWith("/docs/en/cli/?view=grid#install", { scroll: false });
    expect(window.location.pathname).toBe("/docreview-rag/docs/ko/cli/");
    expect(latestReadingState()).toMatchObject({ documentId: "cli", path: ["install"] });
  });

  it("maps legacy localized heading ids through the registry fallback", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/");
    stubRects({ "page-header": { bottom: 60 }, "초기-schema-준비": { top: 30 }, "docs-content": { top: 20, bottom: 900 } });
    render(<I18nProvider><DocumentationReadingBoundary documentId="cli" locale="ko">
      <header className="docs-header" id="page-header" />
      <main id="docs-content" data-document-id="cli" data-document-locale="ko">
        <DocumentationLanguageSwitch locale="ko" />
        <h2 id="초기-schema-준비">초기 schema 준비</h2>
      </main>
    </DocumentationReadingBoundary></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(navigation.replace).toHaveBeenCalledWith("/docs/en/cli/#initial-schema-setup", { scroll: false });
  });

  it("is a no-op for the current language", () => {
    render(<I18nProvider><DocsPage /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "한국어" }));
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(latestReadingState()).toBeNull();
  });

  it("cancels an unfinished switch when the reader selects the current language again", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/");
    render(<I18nProvider><DocsPage /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(latestReadingState()).toMatchObject({ targetLocale: "en" });
    fireEvent.click(screen.getByRole("button", { name: "한국어" }));
    expect(navigation.replace).toHaveBeenLastCalledWith("/docs/ko/cli/", { scroll: false });
    expect(latestReadingState()).toBeNull();
  });

  it("does not consume a position when a superseded locale commits first", () => {
    rememberReadingState({ documentId: "cli", targetLocale: "ko", path: ["install"], progress: .4, details: [] });
    expect(consumeReadingState("cli", "en")).toBeNull();
    expect(latestReadingState()).toMatchObject({ targetLocale: "ko", progress: .4 });
    expect(consumeReadingState("cli", "ko")).toMatchObject({ targetLocale: "ko", progress: .4 });
    expect(latestReadingState()).toBeNull();
  });

  it("does not hijack non-document routes", () => {
    current.pathname = "/docreview-rag/";
    window.history.replaceState({}, "", "/docreview-rag/");
    render(<I18nProvider><DocumentationLanguageSwitch locale="ko" /><LocaleProbe /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
  });

  it("lets the last rapid toggle win", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/");
    stubRects({ "page-header": { bottom: 60 }, install: { top: 30 }, "install-cli": { top: 400 }, "detail-note": { top: 700 }, usage: { top: 900 }, "docs-content": { top: 20, bottom: 2000 } });
    render(<I18nProvider><DocsPage /></I18nProvider>);
    const english = screen.getByRole("button", { name: "EN" });
    fireEvent.click(english);
    fireEvent.click(english);
    expect(navigation.replace).toHaveBeenCalledTimes(2);
    expect(latestReadingState()).toMatchObject({ documentId: "cli", path: ["install"] });
  });
});

describe("DocumentationReadingBoundary", () => {
  it("restores the equivalent section progress, details and shared locale on commit", () => {
    rememberReadingState({ documentId: "cli", path: ["install", "install-cli"], progress: 0.5, details: ["extra"] });
    window.history.replaceState({}, "", "/docs/en/cli/#install-cli");
    current.pathname = "/docs/en/cli/";
    stubRects({ "page-header": { bottom: 60 }, install: { top: 40 }, "install-cli": { top: 300 }, "detail-note": { top: 500 }, usage: { top: 800 }, "docs-content": { top: 20, bottom: 1500 } });
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<I18nProvider><DocsPage locale="en" /></I18nProvider>);
    expect(document.querySelector('details[data-doc-detail="extra"]')).toHaveProperty("open", true);
    expect(scroll).toHaveBeenCalledWith(0, 300 + 0.5 * (500 - 300) - 84);
    expect(screen.getByRole("main").dataset.documentLocale).toBe("en");
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
    expect(localStorage.getItem(LOCALE_KEY)).toBe("en");
    expect(latestReadingState()).toBeNull();
  });

  it("restores the committed position when a preserved boundary gets the new locale", () => {
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/");
    stubRects({ "page-header": { bottom: 60 }, install: { top: 40 }, "install-cli": { top: 300 }, "detail-note": { top: 500 }, usage: { top: 800 }, "docs-content": { top: 20, bottom: 1500 } });
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    const view = render(<I18nProvider><DocsPage /></I18nProvider>);
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    window.history.replaceState({}, "", "/docs/en/cli/#install");
    view.rerender(<I18nProvider><DocsPage locale="en" /></I18nProvider>);
    expect(scroll).toHaveBeenCalledWith(0, 40 + ((84 - 40) / (300 - 40)) * (300 - 40) - 84);
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
  });

  it("opens a linked target inside a closed disclosure on direct navigation", () => {
    window.history.replaceState({}, "", "/docs/en/cli/#detail-note");
    current.pathname = "/docs/en/cli/";
    stubRects({ "page-header": { bottom: 60 }, "detail-note": { top: 500 }, "docs-content": { top: 20, bottom: 1500 } });
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<I18nProvider><DocsPage locale="en" /></I18nProvider>);
    expect(document.querySelector('details[data-doc-detail="extra"]')).toHaveProperty("open", true);
    expect(scroll).toHaveBeenCalledWith(0, 500 - 84);
  });

  it("scrolls a direct link into view when the browser could not anchor it", () => {
    window.history.replaceState({}, "", "/docs/en/cli/#usage");
    current.pathname = "/docs/en/cli/";
    stubRects({ "page-header": { bottom: 60 }, usage: { top: 800 }, "docs-content": { top: 20, bottom: 1500 } });
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<I18nProvider><DocsPage locale="en" /></I18nProvider>);
    expect(scroll).toHaveBeenCalledWith(0, 800 - 84);
  });

  it("leaves an already-anchored scroll position alone", () => {
    window.history.replaceState({}, "", "/docs/en/cli/#usage");
    current.pathname = "/docs/en/cli/";
    stubRects({ "page-header": { bottom: 60 }, usage: { top: 84 }, "docs-content": { top: 20, bottom: 1500 } });
    stubScrollY(716);
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<I18nProvider><DocsPage locale="en" /></I18nProvider>);
    expect(scroll).not.toHaveBeenCalled();
    stubScrollY(0);
  });

  it("discards a stale intent when another document commits first", () => {
    rememberReadingState({ documentId: "other", path: ["install"], progress: 0.5, details: ["extra"] });
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(<I18nProvider><DocsPage locale="en" /></I18nProvider>);
    expect(scroll).not.toHaveBeenCalled();
    expect(document.querySelector('details[data-doc-detail="extra"]')).toHaveProperty("open", false);
    expect(latestReadingState()).toBeNull();
  });

  it("survives denied session storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("denied"); });
    window.history.replaceState({}, "", "/docreview-rag/docs/ko/cli/");
    stubRects({ "page-header": { bottom: 60 }, install: { top: 30 }, "install-cli": { top: 400 }, usage: { top: 900 }, "docs-content": { top: 20, bottom: 2000 } });
    render(<I18nProvider><DocsPage /></I18nProvider>);
    expect(() => fireEvent.click(screen.getByRole("button", { name: "EN" }))).not.toThrow();
    expect(navigation.replace).toHaveBeenCalledWith("/docs/en/cli/#install", { scroll: false });
    expect(latestReadingState()).toMatchObject({ documentId: "cli" });
  });
});
