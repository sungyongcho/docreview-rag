import "./demos.css";

/** Static end-to-end data flow for the architecture guide — stages with the retrieval fork. */

const STAGES: { label: { ko: string; en: string }; detail: { ko: string; en: string }; lanes?: { ko: string; en: string }[] }[] = [
  { label: { ko: "원문 수집", en: "Source acquisition" }, detail: { ko: "SEC EDGAR · DART — 원문 바이트와 식별 정보 보존", en: "SEC EDGAR · DART — source bytes and identity preserved" } },
  { label: { ko: "파싱 · 표 정규화", en: "Parse · normalize tables" }, detail: { ko: "HTML/XML 구조, 표 셀·단위, 원문 오프셋", en: "HTML/XML structure, table cells, units, source offsets" } },
  { label: { ko: "청크 · 문서 저장", en: "Chunks · documents" }, detail: { ko: "인용 가능한 청크와 안정적인 식별자를 DB에 저장", en: "Citable chunks with stable identifiers stored in the DB" } },
  {
    label: { ko: "검색 인덱스", en: "Search indexes" },
    detail: { ko: "같은 청크에서 두 경로를 준비", en: "Two paths prepared from the same chunks" },
    lanes: [
      { ko: "임베딩 — 의미 검색", en: "Embeddings — semantic" },
      { ko: "BM25 — 키워드 검색", en: "BM25 — lexical" },
    ],
  },
  { label: { ko: "하이브리드 검색", en: "Hybrid retrieval" }, detail: { ko: "경로별 순위를 RRF로 융합하고 선택적으로 재정렬", en: "Per-path ranks fused by RRF, optionally reranked" } },
  { label: { ko: "답변 · 인용 검증", en: "Answer · citation check" }, detail: { ko: "근거가 있는 답변 또는 NOT_IN_DOCS", en: "A supported answer or NOT_IN_DOCS" } },
  { label: { ko: "평가 · 스냅샷", en: "Evaluate · snapshot" }, detail: { ko: "골든셋 측정과 변경되지 않는 인덱스 근거", en: "Golden-set metrics over an immutable index record" } },
];

export function ArchitectureFlow({ locale }: { locale: "ko" | "en" }) {
  return <figure className="docs-demo docs-demo-static">
    <figcaption className="docs-demo-head">
      <strong>{locale === "ko" ? "질문까지 이어지는 처리 경로" : "Processing path behind each answer"}</strong>
      <span className="docs-demo-note">{locale === "ko" ? "단계마다 식별자·출처가 이어져 다시 검증할 수 있습니다" : "Identity and provenance carry through every stage for re-verification"}</span>
    </figcaption>
    <ol className="docs-flow">
      {STAGES.map((stage, index) => <li key={stage.label.en} className="docs-flow-stage">
        <code className="docs-flow-num">{index + 1}</code>
        <div className="docs-flow-body">
          <span className="docs-flow-label">{stage.label[locale]}</span>
          <small>{stage.detail[locale]}</small>
          {stage.lanes && <div className="docs-flow-lanes">
            {stage.lanes.map((lane) => <span key={lane.en}>{lane[locale]}</span>)}
          </div>}
        </div>
      </li>)}
    </ol>
  </figure>;
}
