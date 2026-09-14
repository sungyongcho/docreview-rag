import { afterEach, describe, expect, it, vi } from "vitest";
import {
  anchorTarget,
  captureReadingState,
  consumeReadingState,
  documentSections,
  findSection,
  initialQuickStartMode,
  latestReadingState,
  openDetailAncestors,
  openDetails,
  READING_LINE_INSET,
  readingLine,
  rememberReadingState,
  resolveSection,
  routeDocumentId,
  routerPath,
  sectionScrollTop,
  withQuery,
  type ReadingState,
} from "./documentation-reading";

afterEach(() => {
  document.body.innerHTML = "";
  window.history.replaceState({}, "", "/");
  sessionStorage.clear();
  consumeReadingState("__none__");
  vi.restoreAllMocks();
});

function docsPage(inner: string, documentId = "cli") {
  document.body.innerHTML = `<header class="docs-header" id="page-header"></header><main id="docs-content" data-document-id="${documentId}" data-document-locale="en">${inner}</main>`;
  return document.querySelector("main")!;
}

function stubRects(rects: Record<string, { top?: number; bottom?: number }>) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const entry = rects[this.id] ?? {};
    const top = entry.top ?? 0;
    const bottom = entry.bottom ?? top;
    return { top, bottom, left: 0, right: 0, width: 0, height: bottom - top, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  });
}

function state(partial: Partial<ReadingState> = {}): ReadingState {
  return { documentId: "cli", path: [], progress: 0, details: [], ...partial };
}

describe("reading line and sections", () => {
  it("measures the reading line just below the sticky header", () => {
    docsPage("");
    stubRects({ "page-header": { bottom: 64 } });
    expect(readingLine()).toBe(64 + READING_LINE_INSET);
  });

  it("lists visible sections by canonical id and skips hidden or id-less headings", () => {
    docsPage(`<h2 id="install" data-doc-section="install">Install</h2>
      <details data-doc-detail="closed"><summary>More</summary><h3 id="inner" data-doc-section="inner">Inner</h3></details>
      <details data-doc-detail="open" open><summary>Summary</summary><h3 id="shown" data-doc-section="shown">Shown</h3></details>
      <section hidden><h3 id="panel" data-doc-section="panel">Panel</h3></section>
      <h2>No id heading</h2>`);
    expect(documentSections().map((section) => section.id)).toEqual(["install", "shown"]);
  });

  it("captures the nearest section, its parent path, progress and open details", () => {
    docsPage(`<h2 id="install" data-doc-section="install">Install</h2>
      <h3 id="install-cli" data-doc-section="install-cli">CLI</h3>
      <h4 id="install-opts" data-doc-section="install-opts">Options</h4>
      <h2 id="usage" data-doc-section="usage">Usage</h2>
      <details data-doc-detail="kept" open><summary>s</summary></details>
      <details data-doc-detail="shut"><summary>s</summary></details>`);
    stubRects({ install: { top: 40 }, "install-cli": { top: 200 }, "install-opts": { top: 260 }, usage: { top: 900 }, "docs-content": { top: 20, bottom: 2000 } });
    const captured = captureReadingState(document, 230);
    expect(captured.path).toEqual(["install", "install-cli"]);
    expect(captured.progress).toBeCloseTo((230 - 200) / (260 - 200), 5);
    expect(captured.details).toEqual(["kept"]);
    expect(captured.quickstart).toBeUndefined();
  });

  it("keeps the top-level path for a deeply nested section", () => {
    docsPage(`<h2 id="a" data-doc-section="a">A</h2><h3 id="a-1" data-doc-section="a-1">A1</h3><h4 id="a-1-x" data-doc-section="a-1-x">A1x</h4><h2 id="b" data-doc-section="b">B</h2>`);
    stubRects({ a: { top: 10 }, "a-1": { top: 50 }, "a-1-x": { top: 100 }, b: { top: 500 }, "docs-content": { top: 0, bottom: 800 } });
    const captured = captureReadingState(document, 120);
    expect(captured.path).toEqual(["a", "a-1", "a-1-x"]);
  });

  it("records the Quick Start mode only when the document has the tabs", () => {
    docsPage(`<button id="quickstart-cli-tab" aria-selected="true"></button><button id="quickstart-web-tab" aria-selected="false"></button>`);
    expect(captureReadingState().quickstart).toBe("cli");
    docsPage(`<button id="quickstart-web-tab" aria-selected="true"></button>`);
    expect(captureReadingState().quickstart).toBe("web");
  });
});

describe("restoration math", () => {
  it("restores section top plus relative progress on the reading line", () => {
    docsPage(`<h2 id="install" data-doc-section="install">Install</h2><h3 id="install-cli" data-doc-section="install-cli">CLI</h3><h2 id="usage" data-doc-section="usage">Usage</h2>`);
    stubRects({ install: { top: 40 }, "install-cli": { top: 300 }, usage: { top: 800 }, "docs-content": { top: 20, bottom: 1500 }, "page-header": { bottom: 60 } });
    expect(sectionScrollTop(state({ path: ["install", "install-cli"], progress: 0.5 }), document, 84)).toBeCloseTo(300 + 0.5 * (800 - 300) - 84, 5);
  });

  it("falls back to the nearest existing parent when a heading is absent", () => {
    docsPage(`<h2 id="install" data-doc-section="install">Install</h2><h2 id="usage" data-doc-section="usage">Usage</h2>`);
    stubRects({ install: { top: 100 }, usage: { top: 400 }, "docs-content": { top: 0, bottom: 900 } });
    expect(resolveSection(["install", "gone-h3"])).toBe(document.getElementById("install"));
    expect(sectionScrollTop(state({ path: ["install", "gone-h3"], progress: 0.5 }), document, 84)).toBeCloseTo(100 + 0.5 * (400 - 100) - 84, 5);
  });

  it("measures pre-first-section progress when no heading was captured", () => {
    docsPage(`<p>Intro</p><h2 id="install" data-doc-section="install">Install</h2>`);
    stubRects({ install: { top: 300 }, "docs-content": { top: 80, bottom: 1200 } });
    expect(sectionScrollTop(state({ path: [], progress: 0.4 }), document, 84)).toBeCloseTo(80 + 0.4 * (300 - 80) - 84, 5);
  });

  it("uses the content end when the captured section is the last one", () => {
    docsPage(`<h2 id="install" data-doc-section="install">Install</h2><h2 id="usage" data-doc-section="usage">Usage</h2>`);
    stubRects({ install: { top: 40 }, usage: { top: 600 }, "docs-content": { top: 20, bottom: 1400 } });
    expect(sectionScrollTop(state({ path: ["usage"], progress: 0.25 }), document, 84)).toBeCloseTo(600 + 0.25 * (1400 - 600) - 84, 5);
  });
});

describe("anchors and disclosures", () => {
  it("resolves canonical sections, alias markers and percent-encoded fragments", () => {
    docsPage(`<span id="old-anchor" data-doc-alias="install"></span><h2 id="install" data-doc-section="install">Install</h2><h3 id="x" data-doc-section="초기-설정">설정</h3>`);
    expect(anchorTarget("#install")).toBe(document.getElementById("install"));
    expect(anchorTarget("#old-anchor")).toBe(document.getElementById("old-anchor"));
    expect(anchorTarget(`#${encodeURIComponent("초기-설정")}`)).toBe(document.querySelector('[data-doc-section="초기-설정"]'));
    expect(anchorTarget("#missing")).toBeNull();
    expect(anchorTarget("")).toBeNull();
  });

  it("opens only the captured details", () => {
    docsPage(`<details data-doc-detail="a"><summary>a</summary></details><details data-doc-detail="b"><summary>b</summary></details>`);
    expect(openDetails(["a"])).toBe(1);
    expect(document.querySelector('details[data-doc-detail="a"]')).toHaveProperty("open", true);
    expect(document.querySelector('details[data-doc-detail="b"]')).toHaveProperty("open", false);
    expect(openDetails(["a"])).toBe(0);
  });

  it("opens the disclosure chain around a linked target", () => {
    docsPage(`<details data-doc-detail="outer"><summary>o</summary><div><p id="deep">x</p></div></details>`);
    const target = anchorTarget("#deep")!;
    expect(openDetailAncestors(target)).toBe(1);
    expect(document.querySelector("details")!.open).toBe(true);
  });

  it("finds sections by data attribute before element id", () => {
    docsPage(`<h2 id="localized" data-doc-section="canonical">Heading</h2>`);
    expect(findSection("canonical")).toBe(document.getElementById("localized"));
    expect(findSection("localized")).toBe(document.getElementById("localized"));
    expect(findSection("nope")).toBeNull();
  });
});

describe("pending reading state", () => {
  it("returns a remembered state once and then clears it", () => {
    rememberReadingState(state({ path: ["install"], progress: 0.5 }));
    expect(consumeReadingState("cli")).toMatchObject({ path: ["install"], progress: 0.5 });
    expect(consumeReadingState("cli")).toBeNull();
    expect(latestReadingState()).toBeNull();
  });

  it("discards stale intents when another document commits first", () => {
    rememberReadingState(state({ documentId: "cli" }));
    expect(consumeReadingState("other")).toBeNull();
    expect(latestReadingState()).toBeNull();
  });

  it("tolerates denied session storage while memory still works", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("denied"); });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("denied"); });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("denied"); });
    expect(() => rememberReadingState(state({ path: ["install"] }))).not.toThrow();
    expect(consumeReadingState("cli")).toMatchObject({ path: ["install"] });
  });

  it("keeps the state available after a reload through session storage", async () => {
    rememberReadingState(state({ path: ["install"], progress: 0.25, details: ["extra"], quickstart: "cli" }));
    vi.resetModules();
    const fresh = await import("./documentation-reading");
    expect(fresh.consumeReadingState("cli")).toMatchObject({ path: ["install"], progress: 0.25, details: ["extra"], quickstart: "cli" });
  });

  it("follows the link hash before a pending Quick Start hint", () => {
    window.history.replaceState({}, "", "/docs/en/quickstart-dev/#qs-cli-3");
    expect(initialQuickStartMode()).toBe("cli");
    window.history.replaceState({}, "", "/docs/en/quickstart-dev/");
    rememberReadingState(state({ documentId: "quickstart-dev", quickstart: "cli" }));
    expect(initialQuickStartMode()).toBe("cli");
  });
});

describe("route helpers", () => {
  it("resolves localized routes back to canonical document ids", () => {
    expect(routeDocumentId("/docs/en/cli/")).toBe("cli");
    expect(routeDocumentId("/docreview-rag/docs/ko/")).toBe("overview");
    expect(routeDocumentId("/docs/ko/development/?view=x#h")).toBe("development");
    expect(routeDocumentId("/docs/en/quickstart-dev/#qs-web-2")).toBe("quickstart-dev");
    expect(routeDocumentId("/")).toBeNull();
  });

  it("strips only the configured deployment prefix for the router", () => {
    expect(routerPath("/docreview-rag/docs/en/cli/#a")).toBe("/docs/en/cli/#a");
    expect(routerPath("/docs/en/cli/")).toBe("/docs/en/cli/");
  });

  it("inserts the query string before the fragment", () => {
    expect(withQuery("/docs/en/cli/#a", "?view=x")).toBe("/docs/en/cli/?view=x#a");
    expect(withQuery("/docs/en/cli/", "")).toBe("/docs/en/cli/");
  });
});
