"use client";

import { useState } from "react";
import "./demos.css";

/** Illustrative golden-eval metrics for the development log — two questions, shared top-k slider. */

interface EvalQuestion { id: string; label: { ko: string; en: string }; results: { doc: string; gold: boolean }[] }
const QUESTIONS: EvalQuestion[] = [
  { id: "q1", label: { ko: "문항 1 — 정답 3개", en: "question 1 — 3 gold" }, results: [
    { doc: "D1", gold: false }, { doc: "D2", gold: true }, { doc: "D3", gold: false },
    { doc: "D4", gold: false }, { doc: "D5", gold: true }, { doc: "D6", gold: false },
    { doc: "D7", gold: false }, { doc: "D8", gold: true },
  ] },
  { id: "q2", label: { ko: "문항 2 — 정답 2개", en: "question 2 — 2 gold" }, results: [
    { doc: "D1", gold: true }, { doc: "D2", gold: false }, { doc: "D3", gold: false },
    { doc: "D4", gold: true }, { doc: "D5", gold: false }, { doc: "D6", gold: false },
    { doc: "D7", gold: false }, { doc: "D8", gold: false },
  ] },
];

export function EvalMeter({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  const [k, setK] = useState(5);
  const [qid, setQid] = useState("q1");
  const question = QUESTIONS.find((q) => q.id === qid)!;

  const metrics = (q: EvalQuestion, kk: number) => {
    const seen = q.results.slice(0, kk);
    const hits = seen.filter((r) => r.gold).length;
    const first = seen.findIndex((r) => r.gold);
    return { hit: hits > 0 ? 1 : 0, recall: hits / q.results.filter((r) => r.gold).length, rr: first < 0 ? 0 : 1 / (first + 1) };
  };
  const m = metrics(question, k);
  const macro = QUESTIONS.map((q) => metrics(q, k));
  const macroHit = macro.reduce((s, x) => s + x.hit, 0) / QUESTIONS.length;
  const macroMrr = macro.reduce((s, x) => s + x.rr, 0) / QUESTIONS.length;

  return <figure className="docs-demo">
    <figcaption className="docs-demo-head">
      <strong>{ko ? "골든 평가 지표 미니 실험" : "Golden-eval metrics mini-lab"}</strong>
      <span className="docs-demo-note">{ko ? "설명용 예시 — 회색은 일반 결과, 초록은 정답 span" : "Illustrative — plain hits vs gold spans"}</span>
    </figcaption>
    <div className="docs-demo-tabs">
      {QUESTIONS.map((q) => <button key={q.id} type="button" aria-pressed={qid === q.id} onClick={() => setQid(q.id)}>{q.label[locale]}</button>)}
    </div>
    <div className="docs-demo-grid">
      <ol className="docs-demo-results">
        {question.results.map((r, i) => <li key={r.doc} className={`${r.gold ? "gold" : ""} ${i < k ? "in-k" : ""}`}>
          <code>#{i + 1}</code> {r.doc} {r.gold ? <span className="docs-demo-gold">gold</span> : null}
        </li>)}
      </ol>
      <div className="docs-demo-out">
        <p>{ko ? `top-${k} 기준` : `at top-${k}`}</p>
        <dl className="docs-demo-metrics">
          <div><dt>hit@{k}</dt><dd>{m.hit}</dd></div>
          <div><dt>recall@{k}</dt><dd>{m.recall.toFixed(2)}</dd></div>
          <div><dt>RR</dt><dd>{m.rr ? `1/${Math.round(1 / m.rr)}` : "0"}</dd></div>
        </dl>
        <p className="docs-demo-macro">{ko ? "두 문항 매크로 평균" : "macro mean over both questions"} — hit_rate {macroHit.toFixed(2)} · MRR {macroMrr.toFixed(2)}</p>
      </div>
    </div>
    <label className="docs-demo-slider">
      <span>top-k <code>{k}</code></span>
      <input type="range" min={1} max={8} step={1} value={k} onChange={(e) => setK(Number(e.target.value))} />
      <small>{ko ? "k를 늘리면 적중 가능성은 오르지만 노이즈도 늘어납니다" : "larger k catches more gold but admits more noise"}</small>
    </label>
  </figure>;
}
