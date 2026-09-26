"use client";
import { ProductBrand } from "@/components/product-brand";
import { useI18n } from "@/lib/i18n";
import type { Readiness } from "@/lib/types";

/** Starter questions cover both registries and both answer languages; only the titles are translated, the question is sent as written. */
const EXAMPLE_QUESTIONS = [
  { source: "SEC", language: "en", title: "NVIDIA growth drivers", question: "What drove NVIDIA data center revenue growth?" },
  { source: "DART", language: "ko", title: "Samsung memory risks", question: "삼성전자 메모리 사업의 주요 위험은 무엇인가요?" },
  { source: "SEC", language: "en", title: "AMD supply-chain risks", question: "What manufacturing and supply-chain risks did AMD identify in its FY2024 10-K?" },
  { source: "DART", language: "en", title: "SK hynix HBM outlook", question: "What did SK hynix report about HBM demand and its business outlook in 2024? Cite the filing evidence." },
  { source: "SEC", language: "ko", title: "NVIDIA revenue comparison", question: "NVIDIA의 FY2024 총매출은 얼마이며, FY2023과 비교해 어떻게 달라졌나요?" },
  { source: "DART", language: "ko", title: "Samsung semiconductor investment", question: "삼성전자의 2024년 반도체 시설투자 목적과 주요 투자 내용을 설명해 주세요." },
];

interface ReviewWelcomeProps {
  developer: boolean;
  readiness: Readiness | null;
  onNewChat: () => void;
  onOpenBuild: () => void;
  /** Examples fill the composer for editing; they are never sent directly. */
  onChooseExample: (question: string) => void;
}

/** First screen of an empty conversation: what the service promises and where to start. */
export function ReviewWelcome({ developer, readiness, onNewChat, onOpenBuild, onChooseExample }: ReviewWelcomeProps) {
  const { t, locale } = useI18n();
  return (
    <div className="welcome">
      <ProductBrand hero onActivate={onNewChat} actionLabel={`DocReview RAG · ${t("New chat")}`} />
      <p className="eyebrow">{t("Grounded by design")}</p>
      <h1>{t("Review filings with verifiable evidence.")}</h1>
      <p className="welcome-description">{t("Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.").split("NOT_IN_DOCS")[0]}<span className="verdict not-in-docs welcome-verdict">{t("Not in documents")}</span>{t("Ask across SEC 10-K and DART reports. Unsupported answers terminate as NOT_IN_DOCS.").split("NOT_IN_DOCS")[1]}</p>
      <ol className="first-review-path"><li><strong>01</strong><span>{t("Ask about a filing")}</span></li><li><strong>02</strong><span>{t("Open its original evidence")}</span></li><li><strong>03</strong><span>{t("Inspect execution and compare retrieval")}</span></li></ol>
      <div className="welcome-links"><button className="button ghost" type="button" onClick={onOpenBuild}>{t("Explore the implementation")}</button><a href={`/docreview-rag/docs/${locale}/`}>{t("Read the guide")}</a></div>
      {readiness?.mode === "canned" && <p className="notice">{t("Demonstration data — no live provider calls.")}</p>}
      {developer && readiness?.corpus?.documents === 0 ? (
        <div className="next-step" data-tour="evidence-fallback">
          <h2>{t("Corpus is empty")}</h2>
          <p>{t("Download and ingest filings first.")}</p>
          <div className="action-row"><button className="button primary" type="button" onClick={onOpenBuild}>{t("Open Build")}</button></div>
        </div>
      ) : (
        <section className="welcome-examples" data-tour="evidence-fallback" aria-label={t("Example questions")}>
          <p className="welcome-examples-hint">{t("Choose an example to edit before sending.")}</p>
          <div className="suggestions">
            {EXAMPLE_QUESTIONS.map((example) => <button key={example.title} type="button" aria-label={t(example.title)} onClick={() => onChooseExample(example.question)}><span className="suggestion-meta"><span className="suggestion-source">{example.source}</span><span>{example.source === "SEC" ? "10-K" : t("Annual report")} · {example.language === "en" ? "English" : "한국어"}</span></span><strong>{t(example.title)}</strong><span className="suggestion-question" lang={example.language}>{example.question}</span></button>)}
          </div>
        </section>
      )}
    </div>
  );
}
