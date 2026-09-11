"use client";

import { useMemo, useState } from "react";
import "./demos.css";

/** Illustrative structure-aware chunking for the development log — budget slider packs blocks at boundaries. */

interface Block { type: "h" | "p" | "table"; label: string; tok: number; rows?: { label: string; tok: number }[]; headerTok?: number }
const BLOCKS: Block[] = [
  { type: "h", label: "8. Risk Factors", tok: 40 },
  { type: "p", label: "p", tok: 520 },
  { type: "p", label: "p", tok: 480 },
  { type: "table", label: "table", tok: 0, headerTok: 60, rows: [
    { label: "row 1", tok: 180 }, { label: "row 2", tok: 170 }, { label: "row 3", tok: 190 }, { label: "row 4", tok: 160 },
  ] },
  { type: "p", label: "p", tok: 640 },
  { type: "p", label: "p", tok: 300 },
  { type: "h", label: "9. Legal Proceedings", tok: 36 },
  { type: "p", label: "p", tok: 560 },
];

interface Unit { block: number; label: string; tok: number; header: boolean; chunk: number }

export function ChunkBoundary({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  const [budget, setBudget] = useState(1536);

  const { units, chunks } = useMemo(() => {
    const units: Unit[] = [];
    const chunks: { tok: number; labels: string[] }[] = [];
    let tok = 0, chunk = 0;
    for (const [i, block] of BLOCKS.entries()) {
      const parts = block.type === "table" && block.rows
        ? block.rows.map((row) => ({ label: `${block.label} ${row.label}`, tok: row.tok + (block.headerTok ?? 0), header: true }))
        : [{ label: block.label, tok: block.tok, header: false }];
      for (const part of parts) {
        if (tok + part.tok > budget && units.length) { tok = 0; chunk += 1; }
        units.push({ block: i, label: part.label, tok: part.tok, header: part.header, chunk });
        chunks[chunk] = chunks[chunk] ?? { tok: 0, labels: [] };
        chunks[chunk].labels.push(part.label);
        tok += part.tok;
        chunks[chunk].tok = tok;
      }
    }
    return { units, chunks };
  }, [budget]);

  return <figure className="docs-demo">
    <figcaption className="docs-demo-head">
      <strong>{ko ? "청킹 경계 미니 실험" : "Chunk-boundary mini-lab"}</strong>
      <span className="docs-demo-note">{ko ? "설명용 예시 — 구조 경계만 자르고 표 행에는 헤더를 반복합니다" : "Illustrative — cuts only at structure boundaries; split table rows repeat the header"}</span>
    </figcaption>
    <div className="docs-demo-grid">
      <ol className="docs-demo-blocks">
        {units.map((unit, i) => <li key={i} data-chunk={unit.chunk}>
          <code>c{unit.chunk + 1}</code> {unit.label} <small>{unit.tok}tok</small>
          {unit.header ? <span className="docs-demo-gold">{ko ? " +헤더" : " +hdr"}</span> : null}
        </li>)}
      </ol>
      <div className="docs-demo-out">
        <p>{ko ? "결과 청크" : "resulting chunks"}</p>
        <ol className="docs-demo-chunks">
          {chunks.map((chunk, ci) => <li key={ci} data-chunk={ci}>
            <strong>chunk {ci + 1}</strong> <small>{chunk.tok} tok</small>
            <span>{chunk.labels.join(" · ")}</span>
          </li>)}
        </ol>
      </div>
    </div>
    <label className="docs-demo-slider">
      <span>{ko ? "청크 예산" : "chunk budget"} <code>{budget} tok</code></span>
      <input type="range" min={512} max={3072} step={256} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
      <small>{ko ? "예산이 작을수록 표가 행 단위로 나뉘고 청크 수가 늘어납니다" : "smaller budgets split tables by row and raise the chunk count"}</small>
    </label>
  </figure>;
}
