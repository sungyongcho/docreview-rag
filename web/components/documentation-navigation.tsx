"use client";

import { preferredLocale, savedLocale, type Locale } from "@/lib/i18n";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, BookOpen, Terminal } from "lucide-react";
import type { TutorialHeading, TutorialDocument } from "@/lib/tutorial-markdown.mjs";

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
export function DocumentationRedirect({ documentId }: { documentId: "walkthrough" | "cli" }) {
  const router = useRouter();
  const suffix = documentId === "cli" ? "cli/" : "";
  useEffect(() => {
    const locale = preferredLocale(window.location.pathname, savedLocale());
    router.replace(`/docs/${locale}/${suffix}${window.location.hash}`);
  }, [router, suffix]);
  return <main className="docs-shell"><h1>DocReview RAG</h1><p>사용 안내 · Documentation</p><nav aria-label="Language / 언어"><Link href={`/docs/ko/${suffix}`} lang="ko">한국어</Link>{" · "}<Link href={`/docs/en/${suffix}`} lang="en">English</Link></nav></main>;
}

export function DocumentationMenu({ current, documents, locale }: { current: string; documents: TutorialDocument[]; locale: Locale }) {
  const disclosure = useResponsiveDisclosure("(min-width: 701px)");
  return <details ref={disclosure} className="docs-menu" open>
    <summary>{locale === "ko" ? "문서 둘러보기" : "Documentation"}</summary>
    <nav aria-label={locale === "ko" ? "문서 선택" : "Choose a document"}>
      {documents.map((document) => <Link key={document.id} href={document.href.replace("/docreview-rag-agent", "")} aria-current={current === document.id ? "page" : undefined}>
        {document.id === "walkthrough" ? <BookOpen size={18} /> : <Terminal size={18} />}
        <span>{document.label}<small>{document.id === "walkthrough" ? (locale === "ko" ? "직접 해 보며 시작하기" : "Learn by doing") : (locale === "ko" ? "실행 · 상태 · 진단" : "Run · Inspect · Diagnose")}</small></span>
      </Link>)}
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
