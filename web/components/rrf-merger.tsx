"use client";

import { useMemo, useState } from "react";
import "./demos.css";

/** Illustrative RRF merge for the development log — two ranked lanes, k slider. */

const LANES = [
  { name: { ko: "벡터 레인", en: "vector lane" }, ranks: ["A", "B", "C", "D", "E"] },
  { name: { ko: "어휘 레인", en: "lexical lane" }, ranks: ["B", "D", "A", "F", "C"] },
];

export function RrfMerger({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  const [k, setK] = useState(60);

  const merged = useMemo(() => {
    const scores = new Map<string, { score: number; denominators: number[] }>();
    for (const lane of LANES) {
      for (const [i, doc] of lane.ranks.entries()) {
        const denominator = k + i + 1;
        const entry = scores.get(doc) ?? { score: 0, denominators: [] };
        entry.score += 1 / denominator;
        entry.denominators.push(denominator);
        scores.set(doc, entry);
      }
    }
    return [...scores.entries()].sort((a, b) => b[1].score - a[1].score);
  }, [k]);
  const max = merged[0]?.[1].score ?? 1;

  return <figure className="docs-demo">
    <figcaption className="docs-demo-head">
      <strong>{ko ? "RRF 순위 결합 미니 실험" : "RRF merge mini-lab"}</strong>
      <span className="docs-demo-note">{ko ? "설명용 예시 — 점수가 아니라 순위만 합산합니다" : "Illustrative — only ranks are summed, never scores"}</span>
    </figcaption>
    <div className="docs-demo-grid">
      <div className="docs-demo-lanes">
        {LANES.map((lane) => <div key={lane.name.en} className="docs-demo-lane">
          <p>{lane.name[locale]}</p>
          <ol>{lane.ranks.map((doc) => <li key={doc}>{doc}</li>)}</ol>
        </div>)}
      </div>
      <div className="docs-demo-out">
        <p>{ko ? "합산 결과" : "merged result"}</p>
        <ol className="docs-demo-merged">
          {merged.map(([doc, { score, denominators }]) => <li key={doc}>
            <code>{doc}</code>
            <span className="docs-demo-bar"><i style={{ width: `${(score / max) * 100}%` }} /><b>{score.toFixed(4)}</b></span>
            <span className="docs-demo-parts">{denominators.map((den) => `1/${den}`).join(" + ")}</span>
          </li>)}
        </ol>
      </div>
    </div>
    <label className="docs-demo-slider">
      <span>k <code>{k}</code></span>
      <input type="range" min={10} max={100} step={10} value={k} onChange={(e) => setK(Number(e.target.value))} />
      <small>{ko ? "k가 작을수록 상위 순위가, 클수록 균일하게 반영됩니다" : "smaller k favors top ranks; larger k flattens them"}</small>
    </label>
  </figure>;
}
