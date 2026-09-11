import "./demos.css";

/** Static development-order roadmap for the development log — steps grouped by phase. */

const PHASES: { name: { ko: string; en: string }; steps: { ko: string; en: string }[] }[] = [
  { name: { ko: "수집·구조화", en: "Ingestion" }, steps: [
    { ko: "파싱 (10-K Item·표)", en: "parsing (10-K items, tables)" },
    { ko: "표 정규화", en: "table normalization" },
    { ko: "청킹", en: "chunking" },
    { ko: "DB 적재", en: "DB load" },
  ] },
  { name: { ko: "검색", en: "Retrieval" }, steps: [
    { ko: "임베딩", en: "embeddings" },
    { ko: "RRF · retrieval service", en: "RRF · retrieval service" },
    { ko: "BM25 · 로컬 모델", en: "BM25 · local models" },
  ] },
  { name: { ko: "평가", en: "Evaluation" }, steps: [
    { ko: "평가 프레임워크 · golden", en: "eval framework · golden" },
    { ko: "DART · 한국어 표", en: "DART · Korean tables" },
    { ko: "한국어 lexical · KR golden · parity", en: "Korean lexical · KR golden · parity" },
  ] },
  { name: { ko: "제품화", en: "Productization" }, steps: [
    { ko: "API · CLI/compose", en: "API · CLI/compose" },
    { ko: "UI · Help", en: "UI · Help" },
    { ko: "로컬 엔진 (Ollama)", en: "local engine (Ollama)" },
  ] },
];

export function PipelineMap({ locale }: { locale: "ko" | "en" }) {
  let step = 0;
  return <figure className="docs-demo docs-demo-static">
    <figcaption className="docs-demo-head">
      <strong>{locale === "ko" ? "단계별 개발 순서" : "Build order by phase"}</strong>
    </figcaption>
    <ol className="docs-pipeline">
      {PHASES.map((phase) => <li key={phase.name.en} className="docs-pipeline-phase">
        <span className="docs-pipeline-name">{phase.name[locale]}</span>
        <ol className="docs-pipeline-steps">
          {phase.steps.map((label) => { step += 1; return <li key={label.en}><code>{step}</code>{label[locale]}</li>; })}
        </ol>
      </li>)}
    </ol>
  </figure>;
}
