import { ProductBrand } from "@/components/product-brand";
import { DevelopmentBadge } from "@/components/development-badge";
import { LanguageSwitch } from "@/lib/i18n";
import { ThemeSwitch } from "@/components/theme-switch";
import { codeToHtml, bundledLanguages } from "shiki";
import { CodeBlock } from "@/components/code-block";
import { splitQuickStart } from "@/lib/quickstart-markdown.mjs";
import { QuickStartProvider, QuickStartPanels, QuickStartOutline } from "@/components/quickstart-guide";
import { TutorialMarkdown } from "@/components/tutorial-markdown";
import { TutorialImage } from "@/components/tutorial-image";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { DOCUMENTS, renderTutorial } from "@/lib/tutorial-markdown.mjs";
import { DOCUMENTATION_BASE, developmentStoryDocument, documentationDocument } from "@/lib/documentation-registry.mjs";
import { DocumentationLegacyAnchor, DocumentationMenu, DocumentationOutline } from "@/components/documentation-navigation";
import { tutorialRevision, tutorialError } from "@/.tutorial/revision";
import "./documentation.css";

export async function DocumentationPage({ documentId, locale = "ko" }: { documentId: string; locale?: "ko" | "en" }) {
  if (tutorialError) throw new Error(tutorialError);
  const documents = DOCUMENTS.filter((item) => item.locale === locale);
  const story = documentId === "development";
  const document = story ? developmentStoryDocument(locale) : documentationDocument(documentId, locale)!;
  const source = readFileSync(resolve(process.cwd(), "../docs/TUTORIAL", document.file), "utf8");
  const parsed = renderTutorial(source, { locale });
  const highlighted = new Map<string, string>();
  for (const block of parsed.codes) highlighted.set(block.language + "\0" + block.code, await codeToHtml(block.code, { lang: block.language in bundledLanguages ? block.language as keyof typeof bundledLanguages : "text", themes: { light: "github-light", dark: "github-dark" }, defaultColor: false }));
  const render = (markdown: string) => renderTutorial(markdown, { locale, assetVersion: tutorialRevision, renderImage: (image) => <TutorialImage {...image} />, renderDevelopmentNotice: (content) => <aside className="docs-development-notice"><DevelopmentBadge locale={locale} tooltip={false} /><div>{content}</div></aside>, renderCode: (block) => <CodeBlock code={block.code} language={block.language} html={highlighted.get(block.language + "\0" + block.code)!} /> });
  const tutorial = render(source);
  const sections = document.id === "quickstart-dev" ? splitQuickStart(source) : null;
  const body = sections ? <><TutorialMarkdown content={render(sections.common).content} /><QuickStartPanels locale={locale} cli={<TutorialMarkdown content={render(sections.cli).content} />} web={<TutorialMarkdown content={render(sections.web).content} />} /><TutorialMarkdown content={render(sections.after).content} /></> : <TutorialMarkdown content={tutorial.content} />;
  const index = documents.findIndex((item) => item.id === document.id);
  const previous = story ? undefined : documents[index - 1];
  const nextId = document.id === "environment" ? "quickstart-dev" : document.id === "quickstart" ? "answers" : document.id === "quickstart-dev" ? "retrieval" : null;
  const next = story ? undefined : nextId ? documents.find((item) => item.id === nextId) : documents[index + 1];
  const related = document.related.map((id) => documents.find((item) => item.id === id)!);
  const page = <div className="docs-site" lang={locale}>
    {(document.id === "overview" || document.id === "quickstart") && <DocumentationLegacyAnchor locale={locale} />}
    <a className="docs-skip" href="#docs-content">{locale === "ko" ? "본문으로 바로가기" : "Skip to content"}</a>
    <header className="docs-header">
      <div className="docs-header-inner">
      <Link className="docs-brand" href={`/docs/${locale}/`}><ProductBrand /></Link>
      <span className="docs-header-label">{locale === "ko" ? "가이드와 개발 기록" : "Guides & development"}</span><LanguageSwitch locale={locale} /><ThemeSwitch locale={locale} />
      <Link className="docs-back" href="/" aria-label={locale === "ko" ? "서비스로 돌아가기" : "Return to service"}><ArrowLeft size={15} /><span className="docs-back-long">{locale === "ko" ? "서비스로 돌아가기" : "Return to service"}</span><span className="docs-back-short">{locale === "ko" ? "서비스" : "Service"}</span></Link>
      </div>
    </header>
    <div className="docs-layout">
      <aside className="docs-sidebar"><DocumentationMenu current={document.id} documents={documents} locale={locale} /></aside>
      <main id="docs-content" className="docs-content" tabIndex={-1}>
        <nav className="docs-breadcrumb" aria-label={locale === "ko" ? "현재 위치" : "Breadcrumb"}><Link href={`/docs/${locale}/`}>{locale === "ko" ? "사용 가이드" : "User guide"}</Link><span aria-hidden="true">/</span><span>{document.label}</span></nav>
        <p className="docs-kicker">{document.groupTitle}</p>
        {story ? <aside className="docs-mode-guide" aria-label={locale === "ko" ? "개발 기록 상태" : "Development log status"}>
          <span className="docs-mode-shared">{locale === "ko" ? "초안 · 개요" : "Draft / Outline"}</span>
          <p>{locale === "ko" ? "사용자가 보충하는 개발 기록 초안입니다. 공개 데모와 DEV에서 읽을 수 있습니다." : "A working draft the author is still revising, readable in the public demo and DEV."}</p>
        </aside> : <aside className="docs-mode-guide" aria-label={locale === "ko" ? "이 안내의 사용 범위" : "Guide availability"}>
          {document.developmentOnly ? <DevelopmentBadge locale={locale} tooltip={false} /> : <span className="docs-mode-shared">{locale === "ko" ? "공통 안내" : "Shared guide"}</span>}
          <p>{document.developmentOnly
            ? (locale === "ko" ? "이 문서의 실습은 로컬 DEV 환경에서 실행합니다. 문서 전체는 공개 데모와 DEV 어디서든 읽을 수 있습니다." : "Run the exercises in this guide in a local DEV environment. The complete guide remains readable in both the public demo and DEV.")
            : (locale === "ko" ? "공개 데모와 DEV에서 함께 사용하는 안내입니다. 본문에서 스패너가 붙은 작업만 개발 모드 전용이며, 모든 문서는 두 환경에서 읽을 수 있습니다." : "This guide covers both the public demo and DEV. Only actions marked with a wrench require development mode; every document remains readable in both environments.")}</p>
        </aside>}
        <div lang={locale}>{body}</div>
        <section className="docs-related" aria-labelledby="docs-related-title"><h2 id="docs-related-title">{locale === "ko" ? "관련 문서" : "Related documents"}</h2><ul>{related.map((item) => <li key={item.id}><Link href={item.href.replace(DOCUMENTATION_BASE, "")}>{item.title}</Link></li>)}</ul></section>
        <nav className="docs-pagination" aria-label={locale === "ko" ? "이전·다음 문서" : "Previous and next documents"}>
          {previous && <Link className="docs-next docs-previous" rel="prev" href={previous.href.replace(DOCUMENTATION_BASE, "")}><ArrowLeft size={18} /><span><small>{locale === "ko" ? "이전 문서" : "Previous document"}</small>{previous.title}</span></Link>}
          {next && <Link className="docs-next" rel="next" href={next.href.replace(DOCUMENTATION_BASE, "")}><span><small>{locale === "ko" ? "다음 문서" : "Next document"}</small>{next.title}</span><ArrowRight size={18} /></Link>}
        </nav>
      </main>
      <aside className="docs-toc">{sections ? <QuickStartOutline headings={tutorial.headings} locale={locale} /> : <DocumentationOutline headings={tutorial.headings} locale={locale} />}</aside>
    </div>
  </div>;
  return sections ? <QuickStartProvider>{page}</QuickStartProvider> : page;
}
