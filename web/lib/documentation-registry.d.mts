export type DocumentationLocale = "ko" | "en";
export interface TutorialStep { number: number; anchor: string; title: string }
export interface TutorialDocument {
  id: string; slug: string; group: string; groupTitle: string; order: number;
  source: string; locale: DocumentationLocale; file: string; title: string; label: string;
  summary: string; href: string; related: string[]; steps: TutorialStep[];
}
export interface DocumentationRegistry {
  locales: DocumentationLocale[];
  groups: Array<{ id: string; title: Record<DocumentationLocale, string> }>;
  documents: Array<{
    id: string; slug: string; group: string; order: number; source: string;
    title: Record<DocumentationLocale, string>; summary: Record<DocumentationLocale, string>;
    related: string[]; steps: Array<{ number: number; anchor: string; title: Record<DocumentationLocale, string> }>;
    legacyFiles?: string[]; legacyAnchors?: Partial<Record<DocumentationLocale, Record<string, string>>>;
    localizedSections?: Array<Record<DocumentationLocale, string>>;
  }>;
}
export const DOCUMENTATION_REGISTRY: DocumentationRegistry;
export const DOCUMENTATION_BASE: string;
export const DOCUMENTS: TutorialDocument[];
export function validateDocumentationRegistry(value?: DocumentationRegistry): DocumentationRegistry;
export function documentationDocuments(value?: DocumentationRegistry): TutorialDocument[];
export function documentationDocument(id: string, locale?: DocumentationLocale, value?: DocumentationRegistry): TutorialDocument | undefined;
export function legacyDocumentationTarget(locale: DocumentationLocale, hash: string, value?: DocumentationRegistry): { document: TutorialDocument; hash: string } | null;
export function documentationLink(file: string, hash: string, locale?: DocumentationLocale, value?: DocumentationRegistry): { document: TutorialDocument; hash: string } | null;
export function localizedDocumentationRoute(pathname: string, locale: DocumentationLocale, hash?: string, value?: DocumentationRegistry): string | null;
