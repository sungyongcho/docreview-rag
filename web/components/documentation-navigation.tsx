"use client";

import { preferredLocale, savedLocale, type Locale } from "@/lib/i18n";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, ArrowUpRight, BookOpen, Camera, ChartColumn, Compass, Cpu, Database, Download, Files, LifeBuoy, MessageSquareText, MonitorCog, Network, Search, SlidersHorizontal, Terminal, type LucideIcon } from "lucide-react";
import type { TutorialHeading, TutorialDocument } from "@/lib/tutorial-markdown.mjs";
import { DOCUMENTATION_BASE, documentationDocument, legacyDocumentationTarget, localizedDocumentationRoute } from "@/lib/documentation-registry.mjs";
import { DevelopmentBadge } from "@/components/development-badge";

const DOCUMENT_ICONS: Record<string, LucideIcon> = { Activity, Camera, ChartColumn, Compass, Cpu, Database, Download, Files, LifeBuoy, MessageSquareText, MonitorCog, Network, Search, SlidersHorizontal, Terminal };

function useResponsiveDisclosure(query: string) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const media = window.matchMedia(query);
    function update() { if (ref.current) ref.current.open = media.matches; }
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return ref;
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

/** Retain old root-document bookmarks after their sections move to focused pages. */
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
  const disclosure = useResponsiveDisclosure("(min-width: 701px)");
  const groups = [...new Set(documents.map((document) => document.group))];
  return <details ref={disclosure} className="docs-menu" open>
    <summary>{locale === "ko" ? "가이드와 개발 기록" : "Guides & development"}</summary>
    <nav className="docs-nav-group" aria-label={locale === "ko" ? "가이드와 개발 기록" : "Guides & development"}>
      <Link href={`/docs/${locale}/`} aria-current={current === "overview" ? "page" : undefined}><BookOpen size={16} aria-hidden="true" /><span>{locale === "ko" ? "사용 가이드" : "User guide"}</span></Link>
      <Link href={`/docs/${locale}/development/`} aria-current={current === "development" ? "page" : undefined}><Terminal size={16} aria-hidden="true" /><span>{locale === "ko" ? "개발 기록" : "Development log"}</span></Link>
    </nav>
    <nav aria-label={locale === "ko" ? "문서 선택" : "Choose a document"}>
      {groups.map((group) => <section className="docs-nav-group" key={group} aria-labelledby={`docs-group-${group}`}>
        <h2 id={`docs-group-${group}`}>{documents.find((document) => document.group === group)!.groupTitle}</h2>
        {documents.filter((document) => document.group === group).map((document) => {
          const Icon = DOCUMENT_ICONS[document.icon ?? ""] ?? BookOpen;
          return <Link key={document.id} href={document.href.replace(DOCUMENTATION_BASE, "")} aria-current={current === document.id ? "page" : undefined}>
          <Icon size={16} aria-hidden="true" />
          <span>{document.title}{document.developmentOnly && <> <DevelopmentBadge locale={locale} compact /></>}{current === document.id && <small>{document.summary}</small>}</span>
        </Link>; })}
      </section>)}
    </nav>
    <p className="docs-menu-note">{locale === "ko" ? "같은 환경, 같은 데이터. 작업 결과를 화면에서 이어서 확인하세요." : "One environment, shared data. Follow your results from commands to the dashboard."}</p>
    <Link className="docs-service-link" href="/">DocReview RAG <ArrowUpRight size={14} /></Link>
  </details>;
}

export function DocumentationOutline({ headings, locale }: { headings: TutorialHeading[]; locale: Locale }) {
  const disclosure = useResponsiveDisclosure("(min-width: 1151px)");
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
  return <details ref={disclosure} className="docs-outline" open>
    <summary>{locale === "ko" ? "이 페이지에서" : "On this page"}</summary>
    <nav aria-label={locale === "ko" ? "목차" : "Table of contents"}><ol>{sections.map((section) => <li key={section.id}>
      <a href={`#${section.id}`} aria-current={active === section.id ? "location" : undefined}>{section.text}</a>
    </li>)}</ol></nav>
  </details>;
}
