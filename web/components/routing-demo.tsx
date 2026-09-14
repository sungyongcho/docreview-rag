"use client";

import { useState } from "react";
import { ListChecks, MessagesSquare, ScanSearch, Sparkles } from "lucide-react";
import casesData from "@/lib/routing-demo-cases.json";
import "./demos.css";

/** Illustrative stage-0/stage-1 routing walkthrough for the development log — fixed cases, no calls. */

type Scope = "available" | "empty" | "not_applicable" | "pending";

interface RoutingCase {
  id: string;
  title: { ko: string; en: string };
  brief: { ko: string; en: string };
  query: string;
  prior?: string;
  expected_intent: "document_review" | "out_of_scope" | null;
  expected_rule: string | null;
  expected_scope: Scope;
}

const CASES = casesData.cases as RoutingCase[];

export function RoutingDemo({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  const [id, setId] = useState("known");
  const [history, setHistory] = useState(true);
  const item = CASES.find((c) => c.id === id) ?? CASES[0];

  const dropped = Boolean(item.prior) && !history;
  const intent = dropped ? null : item.expected_intent;
  const rule = dropped ? null : item.expected_rule;
  const scope: Scope = dropped ? "pending" : item.expected_scope;
  const pendingClassifier = intent === null;

  const intentLabel = intent === "document_review" ? (ko ? "분석 경로" : "document analysis")
    : intent === "out_of_scope" ? (ko ? "서비스 범위 밖" : "unsupported request") : null;

  const scopeState = pendingClassifier ? "pending" : scope === "not_applicable" ? "skipped" : "active";
  const scopeChip = pendingClassifier ? (ko ? "대기" : "pending")
    : scope === "not_applicable" ? (ko ? "건너뜀" : "skipped")
    : scope === "available" ? (ko ? "사용 가능" : "available") : (ko ? "없음" : "empty");
  const scopeBody = pendingClassifier
    ? (ko ? "분류의 실제 판단을 기다립니다 — 추출 대상을 추정하지 않습니다." : "Waits for the recorded classifier decision — extracted targets are never guessed.")
    : scope === "not_applicable" ? (ko ? "실행하지 않습니다 — 요청이 0단계에서 끝났습니다." : "Never runs — the request ended at stage 0.")
    : scope === "available" ? (ko ? "요청한 기업·연도가 예시 코퍼스에 있습니다." : "The requested issuer and year exist in the illustrative corpus.")
    : (ko ? "요청 연도의 제공 공시가 없어 범위 안내로 끝납니다." : "No provided filing matches the requested year — scope guidance ends the run.");

  const outcomeLabel = pendingClassifier ? (ko ? "분류 판단 대기" : "awaits classifier")
    : scope === "available" ? (ko ? "검색으로 진행" : "continues to retrieval")
    : scope === "empty" ? (ko ? "1단계 — 범위 안내" : "stage 1 — scope guidance")
    : (ko ? "0단계 — 범위 안내" : "stage 0 — scope notice");

  return <figure className="docs-demo">
    <figcaption className="docs-demo-head">
      <strong>{ko ? "라우팅 미니 실험" : "Routing mini-lab"}</strong>
      <span className="docs-demo-note">{ko ? "설명용 예시 — 실제 검색·모델 호출 없음" : "Illustrative examples — no search or model calls"}</span>
    </figcaption>
    <div className="docs-demo-tabs">
      {CASES.map((c) => <button key={c.id} type="button" aria-pressed={id === c.id} onClick={() => setId(c.id)}>{c.title[locale]}</button>)}
    </div>
    <p className="docs-demo-caption routing-brief">{item.brief[locale]}</p>
    {item.prior ? <label className="routing-history">
      <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
      <span>{ko ? "이전 대화 사용" : "Use prior conversation"}</span>
    </label> : null}
    <ol className="routing-flow">
      <li data-state="active" data-step="question">
        <MessagesSquare size={14} className="routing-icon" aria-hidden="true" />
        <div className="routing-step">
          <div className="routing-step-head"><strong>{ko ? "질문" : "Question"}</strong><span className="routing-chip">{ko ? "요청" : "request"}</span></div>
          <p className="routing-query">{item.query}</p>
          {item.prior ? <p className="routing-prior">{ko ? "이전 대화" : "prior"}: {item.prior}{dropped ? <em>{ko ? " · 사용 안 함" : " · not used"}</em> : null}</p> : null}
        </div>
      </li>
      <li data-state="active" data-step="rules">
        <ListChecks size={14} className="routing-icon" aria-hidden="true" />
        <div className="routing-step">
          <div className="routing-step-head"><strong>{ko ? "0단계 · 결정적 규칙" : "Stage 0 · deterministic rules"}</strong><span className="routing-chip">{rule ? (ko ? "매칭" : "matched") : (ko ? "미확정" : "unresolved")}</span></div>
          {rule ? <p><code>{rule}</code> → {intentLabel}</p> : <p>{ko ? "요청 전체를 커버하는 규칙이 없습니다" : "no rule covers the whole request"}</p>}
        </div>
      </li>
      <li data-state={pendingClassifier ? "pending" : "skipped"} data-step="classifier">
        <Sparkles size={14} className="routing-icon" aria-hidden="true" />
        <div className="routing-step">
          <div className="routing-step-head"><strong>{ko ? "분류 판단" : "Classifier decision"}</strong><span className="routing-chip">{pendingClassifier ? (ko ? "필요" : "needed") : (ko ? "건너뜀" : "skipped")}</span></div>
          <p>{pendingClassifier
            ? (ko ? "보조 분류 필요 — 실제 판단을 기다리며 결과를 추정하지 않습니다. 논리적 판단은 한 차례이지만 provider 재시도가 측정되는 호출을 더할 수 있습니다." : "Classifier assistance needed — the demo waits for the actual decision instead of guessing. One logical decision; provider retries can still add measured call attempts.")
            : (ko ? "불필요 — 규칙이 경로를 확정했습니다." : "Not needed — a rule settled the route.")}</p>
        </div>
      </li>
      <li data-state={scopeState} data-step="scope">
        <ScanSearch size={14} className="routing-icon" aria-hidden="true" />
        <div className="routing-step">
          <div className="routing-step-head"><strong>{ko ? "1단계 · 범위 확인" : "Stage 1 · scope check"}</strong><span className="routing-chip">{scopeChip}</span></div>
          <p>{scopeBody}</p>
        </div>
      </li>
    </ol>
    <dl className="docs-demo-metrics routing-summary">
      <div><dt>{ko ? "분류 판단" : "classifier decisions"}</dt><dd data-field="classifier">{pendingClassifier ? (ko ? "대기" : "pending") : "0"}</dd></div>
      <div><dt>{ko ? "요청의 끝" : "request ends"}</dt><dd data-field="outcome">{outcomeLabel}</dd></div>
    </dl>
    <p className="docs-demo-caption">{ko
      ? `예시 코퍼스: ${casesData.inventory.ko} — 데모용 고정 목록이며 실제 제공 현황이 아닙니다. 진행되는 경로의 답변은 검색 이후에 생성되며 이 패널에서는 만들지 않습니다.`
      : `Illustrative corpus: ${casesData.inventory.en} — a fixed list, not live availability. A continuing route generates its answer after retrieval, never inside this panel.`}</p>
  </figure>;
}
