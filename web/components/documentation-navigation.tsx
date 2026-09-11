"use client";

import { preferredLocale, savedLocale, useI18n, type Locale } from "@/lib/i18n";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, BookOpen, Camera, ChartColumn, Compass, Cpu, Database, Download, Files, LifeBuoy, MessageSquareText, MonitorCog, Network, Search, SlidersHorizontal, Terminal, type LucideIcon } from "lucide-react";
import type { TutorialHeading, TutorialDocument } from "@/lib/tutorial-markdown.mjs";
import { DOCUMENTATION_BASE, documentationDocument, legacyDocumentationTarget, localizedDocumentationRoute } from "@/lib/documentation-registry.mjs";
import { DEV_ONLY_NOTE } from "@/lib/dev-mode";
import { CreatorSignature } from "@/components/creator-signature";
import { DevelopmentBadge } from "@/components/development-badge";
import { HoverBubble } from "@/components/hover-bubble";

const DOCUMENT_ICONS: Record<string, LucideIcon> = { Activity, Camera, ChartColumn, Compass, Cpu, Database, Download, Files, LifeBuoy, MessageSquareText, MonitorCog, Network, Search, SlidersHorizontal, Terminal };

const MENU_COPY = {
  ko: { title: "가이드와 개발 기록", userGuide: "사용 가이드", developmentLog: "개발 기록", chooseDocument: "문서 선택" },
  en: { title: "Guides & development", userGuide: "User guide", developmentLog: "Development log", chooseDocument: "Choose a document" },
} as const;

interface DocumentationGroup {
  id: string;
  title: string;
  developmentOnly: boolean;
  documents: TutorialDocument[];
}

/** Group the localized inventory once so the menu never rescans it per row. */
function documentationGroups(documents: TutorialDocument[]): DocumentationGroup[] {
  return [...new Set(documents.map((document) => document.group))].map((id) => ({
    id,
    title: documents.find((document) => document.group === id)!.groupTitle,
    developmentOnly: documents.filter((document) => document.group === id).every((document) => document.developmentOnly),
    documents: documents.filter((document) => document.group === id && document.id !== "overview"),
  }));
}

/** One document row with its icon, localized title, DEV badge and hover summary. */
function DocumentationMenuLink({ document, current, locale }: { document: TutorialDocument; current: string; locale: Locale }) {
  const { t } = useI18n();
  const Icon = DOCUMENT_ICONS[document.icon ?? ""] ?? BookOpen;
  const showBadge = document.developmentOnly && !/DEV/i.test(document.title);
  const label = <>{document.title}{showBadge && <> <DevelopmentBadge locale={locale} compact tooltip={false} text={document.id === "quickstart-dev" ? "DEV MODE" : undefined} /></>}</>;
  return <HoverBubble bubble={<div className="docs-menu-bubble-body">
    <span className="docs-menu-bubble-group">{document.groupTitle}</span>
    <strong>{label}</strong>
    <p>{document.summary}</p>
    {document.developmentOnly && <p className="docs-menu-bubble-dev">{t(DEV_ONLY_NOTE)}</p>}
  </div>} label={document.summary} width={236} className="docs-menu-bubble">
    <Link href={document.href.replace(DOCUMENTATION_BASE, "")} aria-current={current === document.id ? "page" : undefined}>
      <Icon size={16} aria-hidden="true" />
      <span>{label}</span>
    </Link>
  </HoverBubble>;
}

/** The user guide and development log entries above the grouped inventory. */
function DocumentationCollectionLink({ href, icon: Icon, label, current }: { href: string; icon: LucideIcon; label: string; current: boolean }) {
  return <Link href={href} aria-current={current ? "page" : undefined}><Icon size={16} aria-hidden="true" /><span>{label}</span></Link>;
}

/** Legacy links resolve after hydration because the saved preference is browser-owned. */
export function DocumentationRedirect({ documentId }: { documentId: string }) {
  const router = useRouter();
  useEffect(() => {
    const locale = preferredLocale(window.location.pathname, savedLocale());
    const document = documentationDocument(documentId, locale)!;
    const destination = localizedDocumentationRoute(window.location.pathname, locale, window.location.hash) ?? document.href + window.location.hash;
    router.replace(destination.replace(DOCUMENTATION_BASE, ""));
  }, [router, documentId]);
  return <main className="docs-shell"><h1>DocReview RAG</h1><p>사용 안내 · Documentation</p><nav aria-label="Language / 언어"><Link href={documentationDocument(documentId, "ko")!.href.replace(DOCUMENTATION_BASE, "")} lang="ko">한국어</Link>{" · "}<Link href={documentationDocument(documentId, "en")!.href.replace(DOCUMENTATION_BASE, "")} lang="en">English</Link></nav></main>;
}

/** Retain old overview and Quick Start bookmarks after their sections move to focused pages. */
export function DocumentationLegacyAnchor({ locale }: { locale: Locale }) {
  const router = useRouter();
  useEffect(() => {
    function redirect() {
      const target = legacyDocumentationTarget(locale, window.location.hash);
      if (target) router.replace(target.document.href.replace(DOCUMENTATION_BASE, "") + (target.hash ? `#${encodeURIComponent(target.hash)}` : ""));
    }
    redirect();
    window.addEventListener("hashchange", redirect);
    return () => window.removeEventListener("hashchange", redirect);
  }, [locale, router]);
  return null;
}

export function DocumentationMenu({ current, documents, locale }: { current: string; documents: TutorialDocument[]; locale: Locale }) {
  const copy = MENU_COPY[locale];
  return <div className="docs-menu">
    <p className="docs-menu-title">{copy.title}</p>
    <nav className="docs-nav-group" aria-label={copy.title}>
      <DocumentationCollectionLink href={`/docs/${locale}/`} icon={BookOpen} label={copy.userGuide} current={current === "overview"} />
      <DocumentationCollectionLink href={`/docs/${locale}/development/`} icon={Terminal} label={copy.developmentLog} current={current === "development"} />
    </nav>
    <nav className="docs-menu-sections" aria-label={copy.chooseDocument}>
      {documentationGroups(documents).map((group) => <section className="docs-nav-group" key={group.id} aria-labelledby={`docs-group-${group.id}`}>
        <h2 id={`docs-group-${group.id}`}>{group.title}{group.developmentOnly && <> <DevelopmentBadge locale={locale} compact tooltip={false} text={document.id === "quickstart-dev" ? "DEV MODE" : undefined} /></>}</h2>
        {group.documents.map((document) => <DocumentationMenuLink key={document.id} document={document} current={current} locale={locale} />)}
      </section>)}
    </nav>
    <div className="docs-menu-creator"><CreatorSignature variant="footer" /></div>
  </div>;
}

export function DocumentationOutline({ headings, locale }: { headings: TutorialHeading[]; locale: Locale }) {
  const sections = headings.filter((heading) => heading.depth === 2);
  const [active, setActive] = useState("");
  useEffect(() => {
    function update() {
      let selected = sections[0]?.id ?? "";
      for (const section of sections) {
        if ((document.getElementById(section.id)?.getBoundingClientRect().top ?? Infinity) <= 150) selected = section.id;
      }
      setActive(selected);
    }
    let frame = 0;
    function onScroll() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    }
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [headings]);
  return <div className="docs-outline">
    <p className="docs-outline-title">{locale === "ko" ? "이 페이지에서" : "On this page"}</p>
    <nav aria-label={locale === "ko" ? "목차" : "Table of contents"}><ol>{sections.map((section) => <li key={section.id}>
      <a href={`#${section.id}`} aria-current={active === section.id ? "location" : undefined}>{section.text}</a>
    </li>)}</ol></nav>
  </div>;
}
