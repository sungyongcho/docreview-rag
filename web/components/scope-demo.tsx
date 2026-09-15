"use client";

import { useId, useState } from "react";
import { FileCheck2, FileX2, MessagesSquare } from "lucide-react";
import "./demos.css";

/** Illustrative corpus-scope panel for the development log — fixed inventory, no calls. */

type Source = "auto" | "sec" | "dart";

const FILINGS = [
  { company: "NVIDIA", year: "FY2024", source: "sec", lang: "en", form: "10-K" },
  { company: "Samsung", year: "FY2024", source: "dart", lang: "ko", form: "사업보고서" },
] as const;

const QUESTION = {
  en: "Compare all available companies revenue",
  ko: "모든 기업의 매출을 비교해 주세요",
} as const;

export function ScopeDemo({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  const uid = useId();
  const [qlang, setQlang] = useState<"en" | "ko">("en");
  const [source, setSource] = useState<Source>("auto");
  const included = FILINGS.filter((f) => source === "auto" || f.source === source);

  return <figure className="docs-demo">
    <figcaption className="docs-demo-head">
      <strong>{ko ? "코퍼스 범위 미니 실험" : "Corpus scope mini-lab"}</strong>
      <span className="docs-demo-note">{ko ? "설명용 범위 — 검색·모델 호출 없음" : "Illustrative scope — no search or model calls"}</span>
    </figcaption>
    <div className="scope-controls">
      <div className="scope-field">
        <label htmlFor={`${uid}-qlang`}>{ko ? "질문 언어" : "Question language"}</label>
        <select id={`${uid}-qlang`} value={qlang} onChange={(e) => setQlang(e.target.value as "en" | "ko")}>
          <option value="en">{ko ? "영어" : "English"}</option>
          <option value="ko">{ko ? "한국어" : "Korean"}</option>
        </select>
      </div>
      <div className="scope-field">
        <label htmlFor={`${uid}-source`}>{ko ? "소스" : "Source"}</label>
        <select id={`${uid}-source`} value={source} onChange={(e) => setSource(e.target.value as Source)}>
          <option value="auto">{ko ? "자동 · SEC + DART" : "Auto · SEC + DART"}</option>
          <option value="sec">SEC</option>
          <option value="dart">DART</option>
        </select>
      </div>
    </div>
    <div className="scope-question">
      <MessagesSquare size={14} className="routing-icon" aria-hidden="true" />
      <div className="scope-question-body">
        <strong className="scope-query">{QUESTION[qlang]}</strong>
        <small>{ko ? "질문 언어는 검색 범위를 바꾸지 않습니다" : "Question language never changes which filings are in scope"}</small>
      </div>
    </div>
    <ul className="scope-cards">
      {FILINGS.map((f) => {
        const on = source === "auto" || f.source === source;
        const Icon = on ? FileCheck2 : FileX2;
        return <li className="scope-card" data-state={on ? "included" : "excluded"} key={f.company}>
          <div className="scope-card-head">
            <strong>{f.company} <span className="scope-year">{f.year}</span></strong>
            <span className="routing-chip"><Icon size={11} aria-hidden="true" />{on ? (ko ? "포함" : "included") : (ko ? "제외" : "excluded")}</span>
          </div>
          <div className="scope-card-tags"><span>{f.source.toUpperCase()}</span><span>{f.lang}</span><span>{f.form}</span></div>
        </li>;
      })}
    </ul>
    <dl className="docs-demo-metrics scope-summary">
      <div><dt>{ko ? "선택 소스" : "selected source"}</dt><dd data-field="source">{source === "auto" ? (ko ? "자동" : "Auto") : source.toUpperCase()}</dd></div>
      <div><dt>{ko ? "범위 내 공시" : "filings in scope"}</dt><dd data-field="included">{included.length} / {FILINGS.length}</dd></div>
    </dl>
    <p className="docs-demo-caption">{ko
      ? "고정된 예시 목록입니다 — 포함 표시는 검색 범위일 뿐, 문서를 찾을 수 있거나 답변이 근거로 지지된다는 증거가 아닙니다."
      : "A fixed illustrative inventory — inclusion marks the search scope only, not proof that a filing is retrievable or that an answer is supported."}</p>
  </figure>;
}
