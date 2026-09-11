"use client";

import { useState } from "react";
import "./demos.css";

/** Table normalization walkthrough for the development log — four stages, monospace-tinted tables. */

const STAGES = [
  { id: "html", label: { ko: "1 · HTML 원본", en: "1 · source HTML" }, caption: {
    ko: "rowspan·colspan이 섞인 원본 표입니다. 병합 셀의 소유 span은 따로 기록해 이후 추적에 씁니다.",
    en: "The source table mixes rowspan and colspan. Each merged cell's owner span is recorded for later tracking.",
  } },
  { id: "grid", label: { ko: "2 · 그리드 전개", en: "2 · dense grid" }, caption: {
    ko: "병합 셀을 전개해 모든 행이 같은 열 수를 갖는 밀집 그리드를 만듭니다. 빈 행·열은 여기서 제거됩니다.",
    en: "Merged cells are expanded into a dense grid where every row has the same width; empty rows and columns are dropped here.",
  } },
  { id: "fold", label: { ko: "3 · 단위 병합", en: "3 · unit fold" }, caption: {
    ko: "단위 열($, %, ₩)을 값 쪽으로 병합합니다. (1,234) 같은 음수 표기는 원문 그대로 둡니다.",
    en: "Unit columns ($, %, ₩) fold into the value cell. Negative notation like (1,234) is left untouched.",
  } },
  { id: "md", label: { ko: "4 · 마크다운", en: "4 · markdown" }, caption: {
    ko: "헤더를 모양으로 추론하고 마크다운으로 직렬화합니다. 헤더를 못 찾으면 빈 헤더로 둡니다.",
    en: "Headers are inferred by shape and the grid is serialized to markdown. If no header is found, it stays empty.",
  } },
];

function StageTable({ stage }: { stage: string }) {
  if (stage === "html") return <table className="docs-demo-table">
    <tbody>
      <tr><td rowSpan={2} className="demo-hl">Revenue</td><td>2024</td><td rowSpan={2} className="demo-hl">$</td><td>1,234</td></tr>
      <tr><td>2023</td><td>1,111</td></tr>
      <tr><td rowSpan={2} className="demo-hl">Cost</td><td>2024</td><td rowSpan={2} className="demo-hl">$</td><td>987</td></tr>
      <tr><td>2023</td><td>900</td></tr>
    </tbody>
  </table>;
  if (stage === "grid") return <table className="docs-demo-table">
    <tbody>
      <tr><td className="demo-hl">Revenue</td><td>2024</td><td className="demo-hl">$</td><td>1,234</td></tr>
      <tr><td className="demo-hl">Revenue</td><td>2023</td><td className="demo-hl">$</td><td>1,111</td></tr>
      <tr><td className="demo-hl">Cost</td><td>2024</td><td className="demo-hl">$</td><td>987</td></tr>
      <tr><td className="demo-hl">Cost</td><td>2023</td><td className="demo-hl">$</td><td>900</td></tr>
    </tbody>
  </table>;
  if (stage === "fold") return <table className="docs-demo-table">
    <tbody>
      <tr><td>Revenue</td><td>2024</td><td className="demo-hl">$1,234</td></tr>
      <tr><td>Revenue</td><td>2023</td><td className="demo-hl">$1,111</td></tr>
      <tr><td>Cost</td><td>2024</td><td className="demo-hl">$987</td></tr>
      <tr><td>Cost</td><td>2023</td><td className="demo-hl">$900</td></tr>
    </tbody>
  </table>;
  return <pre className="docs-demo-md">{[
    "| Label   | Year | Value  |",
    "|---------|------|--------|",
    "| Revenue | 2024 | $1,234 |",
    "| Revenue | 2023 | $1,111 |",
    "| Cost    | 2024 | $987   |",
    "| Cost    | 2023 | $900   |",
  ].join("\n")}</pre>;
}

export function TableNormalize({ locale }: { locale: "ko" | "en" }) {
  const [stage, setStage] = useState("html");
  const current = STAGES.find((s) => s.id === stage)!;
  return <figure className="docs-demo">
    <figcaption className="docs-demo-head">
      <strong>{locale === "ko" ? "표 정규화 단계 미리보기" : "Table normalization walkthrough"}</strong>
      <span className="docs-demo-note">{locale === "ko" ? "설명용 예시 — 실제 파서 출력이 아닙니다" : "Illustrative — not live parser output"}</span>
    </figcaption>
    <div className="docs-demo-tabs">
      {STAGES.map((s) => <button key={s.id} type="button" aria-pressed={stage === s.id} onClick={() => setStage(s.id)}>{s.label[locale]}</button>)}
    </div>
    <StageTable stage={stage} />
    <p className="docs-demo-caption">{current.caption[locale]}</p>
  </figure>;
}
