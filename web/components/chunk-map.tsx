import "./demos.css";

/** Static chunk-map diagram for the development log — aligned offset tracks, no interactivity. */

export function ChunkMap({ locale }: { locale: "ko" | "en" }) {
  const ko = locale === "ko";
  return <figure className="docs-demo docs-demo-static">
    <figcaption className="docs-demo-head">
      <strong>{ko ? "청크 배치 — 원문 오프셋 기준" : "Chunk layout on source offsets"}</strong>
      <span className="docs-demo-note">{ko ? "설명용 도식" : "Illustrative diagram"}</span>
    </figcaption>
    <div className="docs-map" role="img" aria-label={ko ? "원문 오프셋 위에 블록 span과 청크가 겹침 없이 배치되는 도식" : "Block spans and chunks laid on source offsets without overlap"}>
      <div className="docs-map-row docs-map-source">
        <span className="docs-map-label">source HTML</span>
        <i /><span className="docs-map-arrow">▶</span><span className="docs-map-unit">{ko ? "문자 오프셋" : "character offsets"}</span>
      </div>
      <div className="docs-map-row">
        <span className="docs-map-label">block spans</span>
        <div className="docs-map-track">
          <b style={{ flex: "0 0 18%" }}>heading</b>
          <b style={{ flex: "0 0 34%" }}>paragraph</b>
          <b style={{ flex: "0 0 44%" }}>table</b>
        </div>
      </div>
      <div className="docs-map-row">
        <span className="docs-map-label">chunks</span>
        <div className="docs-map-track">
          <b style={{ flex: "0 0 18%" }}>chunk 1</b>
          <b style={{ flex: "0 0 22%" }}>chunk 2</b>
          <b style={{ flex: "0 0 12%" }}>chunk 3</b>
          <b style={{ flex: "0 0 32%" }}>chunk 4</b>
        </div>
      </div>
      <p className="docs-map-note">
        {ko ? "표는 필요하면 row → cell → sentence 순으로 내려가며, 헤더·캡션을 모든 조각에 반복" : "Tables descend row → cell → sentence when needed, repeating the header/caption on every piece"}
      </p>
      <p className="docs-map-note">
        {ko ? "겹침 없음 — left.end ≤ right.start (같은 원문 span을 공유하는 표 조각만 예외)" : "No overlap — left.end ≤ right.start (except table pieces sharing one source span)"}
      </p>
    </div>
  </figure>;
}
