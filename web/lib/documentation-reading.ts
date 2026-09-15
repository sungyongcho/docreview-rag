import { DOCUMENTATION_BASE, DOCUMENTS } from "./documentation-registry.mjs";

export type QuickStartMode = "cli" | "web";

/** What a language switch captures on the source document and replays on the target. */
export interface CapturedPosition {
  /** Canonical section ids from the containing H2 down to the section at the reading line. */
  path: string[];
  /** Fraction of the current section span that sits above the reading line. */
  progress: number;
  /** Open `data-doc-detail` disclosure ids. */
  details: string[];
  /** Selected Quick Start interface when the document has CLI/Web panels. */
  quickstart?: QuickStartMode;
}

export interface ReadingState extends CapturedPosition {
  /** Canonical destination document id; identical across locales. */
  documentId: string;
  /** Only the requested locale may consume a pending language switch. */
  targetLocale?: "ko" | "en";
}

export interface DocumentSection {
  element: HTMLElement;
  id: string;
  depth: number;
  top: number;
}

/** Distance below the sticky header bottom where the reader's focus line sits. */
export const READING_LINE_INSET = 24;
const HEADER_SELECTOR = "header.docs-header";
const ROOT_SELECTOR = "[data-document-id], #docs-content";
const DETAIL_SELECTOR = "details[data-doc-detail]";
const STORAGE_PREFIX = "docreview:reading:";

/** The rendered document body; absent attributes fall back to the tutorial main element. */
export function documentRoot(root: ParentNode = document): HTMLElement | null {
  return root.querySelector<HTMLElement>(ROOT_SELECTOR);
}

/** Vertical viewport position that anchors section tracking and restoration. */
export function readingLine(root: ParentNode = document): number {
  return (root.querySelector(HEADER_SELECTOR)?.getBoundingClientRect().bottom ?? 0) + READING_LINE_INSET;
}

/** Content inside a collapsed disclosure or a hidden panel is not readable right now. */
function sectionVisible(element: HTMLElement): boolean {
  if (element.closest("[hidden]")) return false;
  const collapsed = element.closest("details:not([open])");
  if (!collapsed) return true;
  const summary = element.closest("summary");
  return summary !== null && summary.parentElement === collapsed;
}

/** Visible H2-H4 headings in document order, keyed by their canonical cross-locale id. */
export function documentSections(root: ParentNode = document): DocumentSection[] {
  const scope = documentRoot(root) ?? root;
  const sections: DocumentSection[] = [];
  for (const element of scope.querySelectorAll<HTMLElement>("h2, h3, h4")) {
    const id = element.dataset.docSection ?? element.id;
    if (!id || !sectionVisible(element)) continue;
    sections.push({ element, id, depth: Number(element.tagName.slice(1)), top: element.getBoundingClientRect().top });
  }
  return sections;
}

/** The Quick Start tab selection, when this document has the CLI/Web panel. */
export function quickStartMode(root: ParentNode = document): QuickStartMode | undefined {
  const scope = documentRoot(root) ?? root;
  if (!scope.querySelector("#quickstart-cli-tab, #quickstart-web-tab")) return undefined;
  return scope.querySelector("#quickstart-cli-tab")?.getAttribute("aria-selected") === "true" ? "cli" : "web";
}

/** Snapshot the reading position so a locale navigation can replay it on the same document. */
export function captureReadingState(root: ParentNode = document, line = readingLine(root)): CapturedPosition {
  const scope = documentRoot(root) ?? root;
  const sections = documentSections(root);
  let index = -1;
  for (let i = 0; i < sections.length; i += 1) if (sections[i].top <= line) index = i;
  const current = index >= 0 ? sections[index] : undefined;
  const next = sections[index + 1];
  const path: string[] = [];
  if (current) {
    const lastAt = new Map<number, number>();
    for (let i = 0; i < index; i += 1) {
      lastAt.set(sections[i].depth, i);
      for (let depth = sections[i].depth + 1; depth <= 4; depth += 1) lastAt.delete(depth);
    }
    for (let depth = 2; depth < current.depth; depth += 1) {
      const parent = lastAt.get(depth);
      if (parent !== undefined) path.push(sections[parent].id);
    }
    path.push(current.id);
  }
  const container = documentRoot(root);
  const start = current?.top ?? container?.getBoundingClientRect().top ?? 0;
  const end = next?.top ?? container?.getBoundingClientRect().bottom ?? start;
  const progress = end > start ? Math.min(1, Math.max(0, (line - start) / (end - start))) : 0;
  const details: string[] = [];
  for (const detail of scope.querySelectorAll<HTMLDetailsElement>(DETAIL_SELECTOR)) {
    if (detail.open && detail.dataset.docDetail) details.push(detail.dataset.docDetail);
  }
  return { path, progress, details, quickstart: quickStartMode(root) };
}

/** A heading, or an alias/bookmark element carrying the same document-local id. */
export function findSection(id: string, root: ParentNode = document): HTMLElement | null {
  const scope = documentRoot(root) ?? root;
  for (const element of scope.querySelectorAll<HTMLElement>("[data-doc-section]")) {
    if (element.dataset.docSection === id) return element;
  }
  const byId = document.getElementById(id);
  if (!byId) return null;
  return scope === document || (scope instanceof Element && scope.contains(byId)) ? byId : null;
}

/** Deepest still-existing section id wins; missing headings fall back to their parent. */
export function resolveSection(path: readonly string[], root: ParentNode = document): HTMLElement | null {
  for (const id of [...path].reverse()) {
    const element = findSection(id, root);
    if (element && sectionVisible(element)) return element;
  }
  return null;
}

/** The element a fragment points at, accepting imperfect manual percent escaping. */
export function anchorTarget(hash: string, root: ParentNode = document): HTMLElement | null {
  const raw = hash.replace(/^#/, "");
  if (!raw) return null;
  let id = raw;
  try { id = decodeURIComponent(raw); } catch { /* Keep the raw fragment when it is not fully escaped. */ }
  return findSection(id, root);
}

/** Reopen captured disclosures before any measurement runs against the new layout. */
export function openDetails(ids: readonly string[], root: ParentNode = document): number {
  if (!ids.length) return 0;
  const wanted = new Set(ids);
  let opened = 0;
  for (const detail of (documentRoot(root) ?? root).querySelectorAll<HTMLDetailsElement>(DETAIL_SELECTOR)) {
    if (detail.dataset.docDetail && wanted.has(detail.dataset.docDetail) && !detail.open) {
      detail.open = true;
      opened += 1;
    }
  }
  return opened;
}

/** Open every disclosure containing a linked target so its anchor becomes reachable. */
export function openDetailAncestors(target: Element): number {
  let opened = 0;
  let ancestor = target.parentElement?.closest("details") ?? null;
  while (ancestor) {
    if (!ancestor.open) { ancestor.open = true; opened += 1; }
    ancestor = ancestor.parentElement?.closest("details") ?? null;
  }
  return opened;
}

/** Document-space scroll offset that puts the equivalent section progress back on the reading line. */
export function sectionScrollTop(state: CapturedPosition, root: ParentNode = document, line = readingLine(root)): number | null {
  const container = documentRoot(root);
  if (!container) return null;
  const sections = documentSections(root);
  const target = state.path.length ? resolveSection(state.path, root) : null;
  const scrolled = window.scrollY;
  if (!target) {
    const start = container.getBoundingClientRect().top + scrolled;
    const end = (sections[0]?.element.getBoundingClientRect().top ?? container.getBoundingClientRect().bottom) + scrolled;
    return Math.max(0, start + state.progress * Math.max(0, end - start) - line);
  }
  const index = sections.findIndex((section) => section.element === target);
  const next = index >= 0 ? sections[index + 1]?.element : undefined;
  const start = target.getBoundingClientRect().top + scrolled;
  const end = (next ? next.getBoundingClientRect().top : container.getBoundingClientRect().bottom) + scrolled;
  return Math.max(0, start + state.progress * Math.max(0, end - start) - line);
}

const pending = new Map<string, ReadingState>();

function isReadingState(value: unknown): value is ReadingState {
  if (typeof value !== "object" || value === null) return false;
  const state = value as Partial<ReadingState>;
  return typeof state.documentId === "string"
    && Array.isArray(state.path) && state.path.every((id) => typeof id === "string")
    && typeof state.progress === "number" && Number.isFinite(state.progress) && state.progress >= 0 && state.progress <= 1
    && Array.isArray(state.details) && state.details.every((id) => typeof id === "string")
    && (state.quickstart === undefined || state.quickstart === "cli" || state.quickstart === "web")
    && (state.targetLocale === undefined || state.targetLocale === "ko" || state.targetLocale === "en");
}

/** Session copies only rescue a reload mid-navigation; the in-memory record is authoritative. */
function storedReadingState(documentId: string): ReadingState | null {
  try {
    const raw = window.sessionStorage?.getItem(STORAGE_PREFIX + documentId);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return isReadingState(parsed) && parsed.documentId === documentId ? parsed : null;
  } catch { return null; }
}

function clearStoredReadingStates() {
  try {
    const storage = window.sessionStorage;
    if (!storage) return;
    const keys: string[] = [];
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      if (key?.startsWith(STORAGE_PREFIX)) keys.push(key);
    }
    for (const key of keys) storage.removeItem(key);
  } catch { /* Optional storage may be denied; memory still serves this tab. */ }
}

/** Queue the position a language switch should restore once the target document commits. */
export function rememberReadingState(state: ReadingState): void {
  cancelReadingState();
  pending.set(state.documentId, state);
  try { window.sessionStorage?.setItem(STORAGE_PREFIX + state.documentId, JSON.stringify(state)); }
  catch { /* Optional storage may be denied; memory still serves this tab. */ }
}

/**
 * Consume the pending position for the committing document. A commit for any other
 * document supersedes unfinished switch intents, so stale entries are dropped.
 */
export function consumeReadingState(documentId: string, locale?: "ko" | "en"): ReadingState | null {
  const state = pending.get(documentId) ?? storedReadingState(documentId);
  if (state?.targetLocale && locale && state.targetLocale !== locale) return null;
  cancelReadingState();
  return state;
}

/** Cancel a superseded switch without leaving a reload-restoration record behind. */
export function cancelReadingState(): void {
  pending.clear();
  clearStoredReadingStates();
}

/** The most recent switch intent, still visible while its destination renders. */
export function latestReadingState(): ReadingState | null {
  const latest = [...pending.values()].at(-1);
  if (latest) return latest;
  if (typeof window === "undefined") return null;
  const id = routeDocumentId(window.location.pathname);
  return id ? storedReadingState(id) : null;
}

/** The interface a qs-* fragment selects, when the current link carries one. */
export function linkedQuickStartMode(): QuickStartMode | undefined {
  if (typeof window === "undefined") return undefined;
  if (window.location.hash.startsWith("#qs-cli")) return "cli";
  if (window.location.hash.startsWith("#qs-web")) return "web";
  return undefined;
}

/** Quick Start's first mode: an explicit qs-* link beats a restored switch hint. */
export function initialQuickStartMode(): QuickStartMode {
  return linkedQuickStartMode() ?? latestReadingState()?.quickstart ?? "web";
}

/** Resolve a localized docs route back to the canonical document id. */
export function routeDocumentId(route: string): string | null {
  const match = route.split(/[?#]/)[0].match(/\/docs\/(ko|en)(?:\/([a-z][a-z0-9-]*))?\/?$/);
  if (!match) return null;
  const slug = match[2] ?? "";
  if (slug === "development") return "development";
  return DOCUMENTS.find((document) => document.slug === slug)?.id ?? null;
}

/** The router is already mounted under the deployment prefix and only wants its suffix. */
export function routerPath(route: string): string {
  return route.startsWith(DOCUMENTATION_BASE) ? route.slice(DOCUMENTATION_BASE.length) : route;
}

/** Preserve the current query string across a language switch without touching the fragment. */
export function withQuery(route: string, search: string): string {
  if (!search || search === "?") return route;
  const hash = route.indexOf("#");
  return hash < 0 ? route + search : `${route.slice(0, hash)}${search}${route.slice(hash)}`;
}
