import registry from "./documentation-registry.json" with { type: "json" };

export const DOCUMENTATION_REGISTRY = registry;
export const DOCUMENTATION_BASE = "/docreview-rag";
/** Per-locale sources for the author-written development log. */
export const DEVELOPMENT_STORY_SOURCES = { ko: "../DEVELOPMENT_STORY.ko.md", en: "../DEVELOPMENT_STORY.en.md" };

/** Expose the author-written development log separately from the bilingual user-guide inventory. */
export function developmentStoryDocument(locale = "ko") {
  const title = locale === "ko" ? "개발 기록" : "Development log";
  const file = DEVELOPMENT_STORY_SOURCES[locale];
  return { id: "development", slug: "development", group: "development", groupTitle: title, order: 0, source: file, file, locale, title, label: title, summary: locale === "ko" ? "RAG 파이프라인 구현과 AI 협업 개발 기록" : "Field notes from building a citation-grounded RAG workflow", href: `${DOCUMENTATION_BASE}/docs/${locale}/development/`, related: ["overview", "architecture"], steps: [] };
}

/** Keep manually entered fragments usable even when their percent escaping is incomplete. */
function fragment(hash) {
  const value = hash.replace(/^#/, "");
  try { return decodeURIComponent(value); }
  catch { return value; }
}

/** Reject ambiguous identities and incomplete translations before publishing documents. */
export function validateDocumentationRegistry(value = registry) {
  if (!Array.isArray(value.locales) || value.locales.join(",") !== "ko,en") throw new Error("Documentation requires Korean and English locales");
  const localized = (entry, name) => {
    if (!value.locales.every((locale) => typeof entry?.[locale] === "string" && entry[locale].trim())) throw new Error(`Missing documentation translation: ${name}`);
  };
  const unique = (items, name) => {
    if (new Set(items).size !== items.length) throw new Error(`Duplicate documentation ${name}`);
  };
  unique(value.groups.map((group) => group.id), "group");
  for (const group of value.groups) localized(group.title, group.id);
  const ids = value.documents.map((document) => document.id);
  unique(ids, "ID");
  unique(value.documents.map((document) => document.slug), "slug");
  unique(value.documents.map((document) => document.source), "source");
  unique(value.documents.map((document) => document.order), "order");
  const steps = [];
  for (const document of value.documents) {
    if (!/^[a-z][a-z0-9-]*$/.test(document.id) || !/^(?:[a-z][a-z0-9-]*)?$/.test(document.slug) || !/^[a-z][a-z0-9-]*\.md$/.test(document.source)) throw new Error(`Invalid documentation identity: ${document.id}`);
    if (!value.groups.some((group) => group.id === document.group)) throw new Error(`Unknown documentation group: ${document.group}`);
    if (!Number.isInteger(document.order) || document.order < 1) throw new Error(`Invalid documentation order: ${document.id}`);
    localized(document.title, document.id);
    localized(document.summary, document.id);
    for (const section of document.localizedSections ?? []) localized(section, `${document.id} section`);
    for (const locale of value.locales) unique((document.localizedSections ?? []).map((section) => section[locale]), `${document.id} section (${locale})`);
    for (const id of document.related) if (!ids.includes(id) || id === document.id) throw new Error(`Unknown or self-related document: ${id}`);
    for (const step of document.steps) {
      if (!Number.isInteger(step.number) || step.number < 1 || step.anchor !== `step-${step.number}`) throw new Error(`Invalid tutorial step: ${document.id}`);
      localized(step.title, `${document.id} step ${step.number}`);
      steps.push(step.number);
    }
  }
  unique(steps, "step");
  if (steps.sort((a, b) => a - b).some((number, index) => number !== index + 1)) throw new Error("Tutorial steps must be continuous");
  for (const locale of value.locales) unique(value.documents.flatMap((document) => Object.keys(document.legacyAnchors?.[locale] ?? {})), `legacy anchor (${locale})`);
  unique(value.documents.flatMap((document) => document.legacyFiles ?? []), "legacy file");
  return value;
}

/** Expand one canonical inventory into localized source files and navigation records. */
export function documentationDocuments(value = registry) {
  return value.locales.flatMap((locale) => [...value.documents].sort((a, b) => a.order - b.order).map((document) => ({
    ...document,
    locale,
    file: `${locale}/${document.source}`,
    title: document.title[locale],
    label: document.title[locale],
    summary: document.summary[locale],
    groupTitle: value.groups.find((group) => group.id === document.group).title[locale],
    href: `${DOCUMENTATION_BASE}/docs/${locale}/${document.slug ? document.slug + "/" : ""}`,
    steps: document.steps.map((step) => ({ ...step, title: step.title[locale] })),
  })));
}

export const DOCUMENTS = documentationDocuments();

/** Resolve a stable document ID in the requested language. */
export function documentationDocument(id, locale = "ko", value = registry) {
  return documentationDocuments(value).find((document) => document.id === id && document.locale === locale);
}

/** Map an old walkthrough section to its focused document and stable bilingual anchor. */
export function legacyDocumentationTarget(locale, hash, value = registry) {
  const anchor = fragment(hash);
  for (const language of [locale, ...value.locales.filter((item) => item !== locale)]) {
    const target = value.documents.find((document) => Object.hasOwn(document.legacyAnchors?.[language] ?? {}, anchor));
    if (target) return { document: documentationDocument(target.id, locale, value), hash: target.legacyAnchors[language][anchor] };
  }
  return null;
}

/** Resolve only registered Markdown filenames, including maintained legacy links. */
export function documentationLink(file, hash, locale = "ko", value = registry) {
  const source = value.documents.find((document) => document.source === file || document.legacyFiles?.includes(file));
  if (!source) return null;
  const legacy = source.legacyFiles?.includes(file) || (source.id === "quickstart" && fragment(hash).startsWith("qs-"))
    ? legacyDocumentationTarget(locale, hash, value) : null;
  return legacy ?? { document: documentationDocument(source.id, locale, value), hash };
}

/** Preserve the document, deployment prefix, and useful section when switching languages. */
export function localizedDocumentationRoute(pathname, locale, hash = "", value = registry) {
  const match = pathname.match(/^(.*)\/docs(?:\/(ko|en))?(?:\/([a-z][a-z0-9-]*))?\/?$/);
  if (!match) return null;
  if (match[3] === "development") return `${match[1]}/docs/${locale}/development/${hash ? `#${encodeURIComponent(fragment(hash))}` : ""}`;
  const source = value.documents.find((document) => document.slug === (match[3] ?? ""));
  if (!source) return null;
  let target = documentationDocument(source.id, locale, value);
  let anchor = fragment(hash);
  const section = source.localizedSections?.find((entry) => match[2] ? entry[match[2]] === anchor : value.locales.some((language) => entry[language] === anchor));
  if (section) anchor = section[locale];
  if ((!source.slug || source.id === "quickstart") && anchor) {
    const legacy = legacyDocumentationTarget(match[2] ?? locale, anchor, value);
    if (legacy) {
      target = documentationDocument(legacy.document.id, locale, value);
      anchor = legacy.hash;
    }
  }
  return `${match[1]}/docs/${locale}/${target.slug ? target.slug + "/" : ""}${anchor ? `#${encodeURIComponent(anchor)}` : ""}`;
}
