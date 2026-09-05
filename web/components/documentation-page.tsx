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
import { DOCUMENTATION_BASE, documentationDocument } from "@/lib/documentation-registry.mjs";
import { DocumentationLegacyAnchor, DocumentationMenu, DocumentationOutline } from "@/components/documentation-navigation";
import { tutorialRevision, tutorialError } from "@/.tutorial/revision";
import "./documentation.css";

export async function DocumentationPage({ documentId, locale = "ko" }: { documentId: string; locale?: "ko" | "en" }) {
  if (tutorialError) throw new Error(tutorialError);
  const documents = DOCUMENTS.filter((item) => item.locale === locale);
  const document = documentationDocument(documentId, locale)!;
  const source = readFileSync(resolve(process.cwd(), "../docs/TUTORIAL", document.file), "utf8");
  const parsed = renderTutorial(source, { locale });
  const highlighted = new Map<string, string>();
  for (const block of parsed.codes) highlighted.set(block.language + "\0" + block.code, await codeToHtml(block.code, { lang: block.language in bundledLanguages ? block.language as keyof typeof bundledLanguages : "text", themes: { light: "github-light", dark: "github-dark" } }));
  const tutorial = renderTutorial(source, { locale, assetVersion: tutorialRevision, renderCode: (block) => <CodeBlock code={block.code} language={block.language} html={highlighted.get(block.language + "\0" + block.code)!} /> });
  const index = documents.findIndex((item) => item.id === document.id);
  const previous = documents[index - 1];
  const next = documents[index + 1];
  const related = document.related.map((id) => documents.find((item) => item.id === id)!);
  return <div className="docs-site" lang={locale}>
    {document.id === "overview" && <DocumentationLegacyAnchor locale={locale} />}
    <a className="docs-skip" href="#docs-content">{locale === "ko" ? "본문으로 바로가기" : "Skip to content"}</a>
    <header className="docs-header">
      <div className="docs-header-inner">
      <Link className="docs-brand" href="/"><ProductBrand /></Link>
      <span className="docs-header-label">{locale === "ko" ? "사용 안내" : "Documentation"}</span><LanguageSwitch locale={locale} />
      <Link className="docs-back" href="/" aria-label={locale === "ko" ? "서비스로 돌아가기" : "Return to service"}><ArrowLeft size={15} /><span className="docs-back-long">{locale === "ko" ? "서비스로 돌아가기" : "Return to service"}</span><span className="docs-back-short">{locale === "ko" ? "서비스" : "Service"}</span></Link>
      </div>
    </header>
    <div className="docs-layout">
      <aside className="docs-sidebar"><DocumentationMenu current={document.id} documents={documents} locale={locale} /></aside>
      <main id="docs-content" className="docs-content" tabIndex={-1}>
        <nav className="docs-breadcrumb" aria-label={locale === "ko" ? "현재 위치" : "Breadcrumb"}><Link href={`/docs/${locale}/`}>{locale === "ko" ? "사용 안내" : "Documentation"}</Link><span aria-hidden="true">/</span><span>{document.label}</span></nav>
        <p className="docs-kicker">{document.groupTitle}</p>
        <TutorialMarkdown content={tutorial.content} />
        <section className="docs-related" aria-labelledby="docs-related-title"><h2 id="docs-related-title">{locale === "ko" ? "관련 문서" : "Related documents"}</h2><ul>{related.map((item) => <li key={item.id}><Link href={item.href.replace(DOCUMENTATION_BASE, "")}>{item.title}</Link></li>)}</ul></section>
        <nav className="docs-pagination" aria-label={locale === "ko" ? "이전·다음 문서" : "Previous and next documents"}>
          {previous && <Link className="docs-next docs-previous" rel="prev" href={previous.href.replace(DOCUMENTATION_BASE, "")}><ArrowLeft size={18} /><span><small>{locale === "ko" ? "이전 문서" : "Previous document"}</small>{previous.title}</span></Link>}
          {next && <Link className="docs-next" rel="next" href={next.href.replace(DOCUMENTATION_BASE, "")}><span><small>{locale === "ko" ? "다음 문서" : "Next document"}</small>{next.title}</span><ArrowRight size={18} /></Link>}
        </nav>
      </main>
      <aside className="docs-toc"><DocumentationOutline headings={tutorial.headings} locale={locale} /></aside>
    </div>
    <footer className="docs-footer"><div className="docs-footer-inner"><span>{locale === "ko" ? "DocReview RAG · 원문 근거와 함께 읽는 공시" : "DocReview RAG · Filings with verifiable evidence"}</span><CreatorSignature variant="footer" /></div></footer>
  </div>;
}
