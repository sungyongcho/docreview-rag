import { ProductBrand } from "@/components/product-brand";
import { CreatorSignature } from "@/components/creator-signature";
import { LanguageSwitch } from "@/lib/i18n";
import { codeToHtml, bundledLanguages } from "shiki";
import { CodeBlock } from "@/components/code-block";
import { TutorialMarkdown } from "@/components/tutorial-markdown";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Link from "next/link";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { DOCUMENTS, renderTutorial } from "@/lib/tutorial-markdown.mjs";
import { DocumentationMenu, DocumentationOutline } from "@/components/documentation-navigation";
import { tutorialRevision, tutorialError } from "@/.tutorial/revision";

export async function DocumentationPage({ documentId, locale = "ko" }: { documentId: "walkthrough" | "cli"; locale?: "ko" | "en" }) {
  if (tutorialError) throw new Error(tutorialError);
  const documents = DOCUMENTS.filter((item) => item.locale === locale);
  const document = documents.find((item) => item.id === documentId)!;
  const source = readFileSync(resolve(process.cwd(), "../docs/TUTORIAL", document.file), "utf8");
  const parsed = renderTutorial(source, { locale });
  const highlighted = new Map<string, string>();
  for (const block of parsed.codes) highlighted.set(block.language + "\0" + block.code, await codeToHtml(block.code, { lang: block.language in bundledLanguages ? block.language as keyof typeof bundledLanguages : "text", themes: { light: "github-light", dark: "github-dark" } }));
  const tutorial = renderTutorial(source, { locale, assetVersion: tutorialRevision, renderCode: (block) => <CodeBlock code={block.code} language={block.language} html={highlighted.get(block.language + "\0" + block.code)!} /> });
  const other = documents.find((item) => item.id !== documentId)!;
  return <div className="docs-site" lang={locale}>
    <a className="docs-skip" href="#docs-content">{locale === "ko" ? "본문으로 바로가기" : "Skip to content"}</a>
    <header className="docs-header">
      <div className="docs-header-inner">
      <Link className="docs-brand" href="/"><ProductBrand /></Link>
      <span className="docs-header-label">{locale === "ko" ? "사용 안내" : "Documentation"}</span><LanguageSwitch locale={locale} />
      <Link className="docs-back" href="/" aria-label={locale === "ko" ? "서비스로 돌아가기" : "Return to service"}><ArrowLeft size={15} /><span className="docs-back-long">{locale === "ko" ? "서비스로 돌아가기" : "Return to service"}</span><span className="docs-back-short">{locale === "ko" ? "서비스" : "Service"}</span></Link>
      </div>
    </header>
    <div className="docs-layout">
      <aside className="docs-sidebar"><DocumentationMenu current={documentId} documents={documents} locale={locale} /></aside>
      <main id="docs-content" className="docs-content" tabIndex={-1}>
        <nav className="docs-breadcrumb" aria-label={locale === "ko" ? "현재 위치" : "Breadcrumb"}><Link href={`/docs/${locale}/`}>{locale === "ko" ? "사용 안내" : "Documentation"}</Link><span aria-hidden="true">/</span><span>{document.label}</span></nav>
        <p className="docs-kicker">{documentId === "walkthrough" ? (locale === "ko" ? "시작하기" : "GET STARTED") : (locale === "ko" ? "명령 안내" : "COMMAND REFERENCE")}</p>
        <TutorialMarkdown content={tutorial.content} />
        <Link className="docs-next" href={other.href.replace("/docreview-rag-agent", "")}><span><small>{locale === "ko" ? "함께 읽기" : "Read next"}</small>{other.title}</span><ArrowRight size={20} /></Link>
      </main>
      <aside className="docs-toc"><DocumentationOutline headings={tutorial.headings} locale={locale} /></aside>
    </div>
    <footer className="docs-footer"><div className="docs-footer-inner"><span>{locale === "ko" ? "DocReview RAG · 원문 근거와 함께 읽는 공시" : "DocReview RAG · Filings with verifiable evidence"}</span><CreatorSignature variant="footer" /></div></footer>
  </div>;
}
