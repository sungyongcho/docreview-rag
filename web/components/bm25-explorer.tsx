"use client";

import { useMemo, useState } from "react";
import "./bm25-explorer.css";

/** Illustrative BM25 walkthrough for the development log — fixed example data, real formula. */

const N = 1000;
const MAX_K1 = 3;

interface DemoTerm { term: { ko: string; en: string }; df: number; tf: number }
const TERMS: DemoTerm[] = [
  { term: { ko: "부채", en: "debt" }, df: 60, tf: 5 },
  { term: { ko: "비율", en: "ratio" }, df: 240, tf: 3 },
  { term: { ko: "상승", en: "rise" }, df: 170, tf: 2 },
  { term: { ko: "원인", en: "driver" }, df: 520, tf: 1 },
];
const QUESTION = { ko: "부채 비율 상승 원인", en: "debt ratio rise driver" };

const idf = (df: number) => Math.log(1 + (N - df + 0.5) / (df + 0.5));
const saturation = (tf: number, k1: number, norm: number) => (tf * (k1 + 1)) / (tf + k1 * norm);

const W = 300, H = 150, PAD = { l: 34, r: 10, t: 12, b: 24 };

function curvePath(fn: (x: number) => number, xMax: number, yMax: number, samples = 60) {
  const pts: string[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const x = (i / samples) * xMax;
    const y = Math.max(0, Math.min(yMax, fn(x)));
    pts.push(`${i === 0 ? "M" : "L"}${(PAD.l + (x / xMax) * (W - PAD.l - PAD.r)).toFixed(1)},${(PAD.t + (1 - y / yMax) * (H - PAD.t - PAD.b)).toFixed(1)}`);
  }
  return pts.join(" ");
}

function dot(cxVal: number, cyVal: number, xMax: number, yMax: number) {
  return {
    cx: PAD.l + (cxVal / xMax) * (W - PAD.l - PAD.r),
    cy: PAD.t + (1 - Math.max(0, Math.min(yMax, cyVal)) / yMax) * (H - PAD.t - PAD.b),
  };
}

export function Bm25Explorer({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  const [k1, setK1] = useState(1.2);
  const [b, setB] = useState(0.75);
  const [docLen, setDocLen] = useState(1.0);

  const norm = 1 - b + b * docLen;
  const rows = useMemo(() => TERMS.map((item) => {
    const i = idf(item.df);
    const sat = saturation(item.tf, k1, norm);
    return { ...item, idf: i, sat, score: i * sat };
  }), [k1, norm]);
  const total = rows.reduce((sum, row) => sum + row.score, 0);
  // Fixed visual scales use the saturation ceiling, never an evidence cutoff.
  const termScale = Math.max(...rows.map((row) => row.idf)) * (MAX_K1 + 1);
  const totalScale = rows.reduce((sum, row) => sum + row.idf, 0) * (MAX_K1 + 1);

  const idfMax = Math.ceil(idf(0.5) * 10) / 10;
  const tfXMax = 15;
  const tfYMax = k1 + 1.4;

  const copy = {
    title: ko ? "BM25 점수 미니 실험" : "BM25 score mini-lab",
    note: ko ? "설명용 예시 계산 — 실제 서버 데이터가 아닙니다" : "An illustrative calculation — not live server data",
    idfTitle: ko ? "IDF — 단어가 흔할수록 로그 곡선을 따라 기여가 줄어듭니다" : "IDF — common terms contribute less, along a log curve",
    idfX: ko ? "문서 빈도 df (코퍼스 1,000건)" : "document frequency df (corpus of 1,000)",
    tfTitle: ko ? "TF 포화 — 반복 등장은 k1이 정한 천장까지 포화됩니다" : "TF saturation — repeats saturate at the ceiling k1 sets",
    tfX: ko ? "문서 내 등장 횟수 tf" : "term frequency inside the document",
    k1Label: "k1",
    bLabel: "b",
    lenLabel: ko ? "문서 길이 (dl/avgdl)" : "doc length (dl/avgdl)",
    queryLabel: ko ? "예시 질문" : "example question",
    docLabel: ko ? "예시 문서" : "example document",
    scoreLabel: ko ? "합계 점수" : "total score",
    explanation: ko ? "이 점수는 어휘 검색 순위에 사용됩니다. 근거 채택 여부는 점수만으로 정하지 않고 이후 검증에서 확인합니다." : "This score informs lexical retrieval ranking. Evidence support is established by later checks, not by this score alone.",
    termCol: ko ? "단어" : "term",
  };

  return <figure className="bm25-demo">
    <figcaption className="bm25-demo-head">
      <strong>{copy.title}</strong>
      <span className="bm25-demo-note">{copy.note}</span>
    </figcaption>

    <div className="bm25-demo-charts">
      <div className="bm25-demo-chart">
        <p>{copy.idfTitle}</p>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={copy.idfTitle}>
          {[0.25, 0.5, 0.75].map((g) => <line key={g} className="bm25-grid" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + g * (H - PAD.t - PAD.b)} y2={PAD.t + g * (H - PAD.t - PAD.b)} />)}
          <line className="bm25-grid bm25-axis" x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} />
          <path className="bm25-curve" d={curvePath((x) => idf(x), N, idfMax)} />
          {rows.map((row) => { const p = dot(row.df, row.idf, N, idfMax); return <g key={row.term.en}>
            <circle className="bm25-dot" cx={p.cx} cy={p.cy} r={3.5} />
            <text className="bm25-dot-label" x={p.cx} y={p.cy - 7} textAnchor="middle">{row.term[locale]}</text>
          </g>; })}
          <text className="bm25-axis-label" x={PAD.l} y={H - 6}>{copy.idfX}</text>
        </svg>
      </div>

      <div className="bm25-demo-chart">
        <p>{copy.tfTitle}</p>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={copy.tfTitle}>
          {[0.25, 0.5, 0.75].map((g) => <line key={g} className="bm25-grid" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + g * (H - PAD.t - PAD.b)} y2={PAD.t + g * (H - PAD.t - PAD.b)} />)}
          <line className="bm25-grid bm25-axis" x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} />
          <line className="bm25-ceil" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + (1 - (k1 + 1) / tfYMax) * (H - PAD.t - PAD.b)} y2={PAD.t + (1 - (k1 + 1) / tfYMax) * (H - PAD.t - PAD.b)} />
          <path className="bm25-curve" d={curvePath((x) => saturation(x, k1, norm), tfXMax, tfYMax)} />
          {rows.map((row) => { const p = dot(row.tf, row.sat, tfXMax, tfYMax); return <g key={row.term.en}>
            <circle className="bm25-dot" cx={p.cx} cy={p.cy} r={3.5} />
            <text className="bm25-dot-label" x={p.cx} y={p.cy - 7} textAnchor="middle">{row.term[locale]}</text>
          </g>; })}
          <text className="bm25-axis-label" x={PAD.l} y={H - 6}>{copy.tfX}</text>
        </svg>
      </div>
    </div>

    <div className="bm25-demo-sliders">
      <label><span>{copy.k1Label} <code>{k1.toFixed(1)}</code></span>
        <input type="range" min={0.2} max={MAX_K1} step={0.1} value={k1} onChange={(e) => setK1(Number(e.target.value))} />
        <small>{ko ? "TF 포화 속도" : "TF saturation speed"}</small>
      </label>
      <label><span>{copy.bLabel} <code>{b.toFixed(2)}</code></span>
        <input type="range" min={0} max={1} step={0.05} value={b} onChange={(e) => setB(Number(e.target.value))} />
        <small>{ko ? "길이 보정 강도" : "length normalization"}</small>
      </label>
      <label><span>{copy.lenLabel} <code>{docLen.toFixed(1)}×</code></span>
        <input type="range" min={0.4} max={2.5} step={0.1} value={docLen} onChange={(e) => setDocLen(Number(e.target.value))} />
        <small>{ko ? "평균 대비 문서 길이" : "length vs corpus average"}</small>
      </label>
    </div>

    <div className="bm25-demo-query">
      <p className="bm25-demo-q"><span>{copy.queryLabel}</span> “{QUESTION[locale]}” <em>×</em> <span>{copy.docLabel}</span></p>
      <ul>
        {rows.map((row) => <li key={row.term.en}>
          <code>{row.term[locale]}</code>
          <span className="bm25-term-meta">df {row.df} · idf {row.idf.toFixed(2)} · tf {row.tf} → sat {row.sat.toFixed(2)}</span>
          <span className="bm25-term-bar"><i style={{ width: `${Math.min(100, (row.score / termScale) * 100)}%` }} /><b>{row.score.toFixed(2)}</b></span>
        </li>)}
      </ul>
      <div className="bm25-demo-score">
        <span>{copy.scoreLabel}</span>
        <span className="bm25-score-track">
          <i style={{ width: `${Math.min(100, (total / totalScale) * 100)}%` }} />
        </span>
        <strong>{total.toFixed(2)}</strong>
      </div>
      <p className="bm25-demo-explanation">{copy.explanation}</p>
    </div>
  </figure>;
}
