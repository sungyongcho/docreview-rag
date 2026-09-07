"use client";
import { ChevronDown, ChevronLeft, ChevronRight, CircleMinus, Pin as PinIcon } from "lucide-react";
import { useRef, useState } from "react";

import { evidenceHeading, evidencePage } from "@/lib/evidence";
import { useI18n } from "@/lib/i18n";
import type { ChatMessage, EvidenceHit } from "@/lib/types";

interface EvidenceCandidatesProps {
  message: ChatMessage;
  busy: boolean;
  onMark: (chunkId: number, mode: "pin" | "exclude") => void;
  onUseSelected: () => void;
}

/**
 * Candidate list under an answer: a sticky toolbar with the shown range, the selection counts,
 * expand/collapse and paging, then the selection guide and one collapsible card per hit.
 * Pinned cards start open and everything else starts closed, so thirty candidates read as
 * thirty headings. Mount it with `key={message.id}`: the expansion and page state belong to the
 * component, while pins and exclusions live on the message and survive paging and re-review.
 */
export function EvidenceCandidates({ message, busy, onMark, onUseSelected }: EvidenceCandidatesProps) {
  const { t } = useI18n();
  const hits = message.evidence ?? [];
  const pinned = message.pinnedChunkIds ?? [];
  const excluded = message.excludedChunkIds ?? [];
  const selectable = Boolean(message.candidateToken);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set(pinned));
  const [pageIndex, setPageIndex] = useState(0);
  const toolbar = useRef<HTMLDivElement>(null);
  const { items, page, pages, from, to } = evidencePage(hits, pageIndex);
  const guideId = `evidence-selection-${message.id}`;

  function toggle(chunkId: number) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(chunkId)) next.delete(chunkId);
      else next.add(chunkId);
      return next;
    });
  }

  function goTo(next: number) {
    setPageIndex(next);
    toolbar.current?.scrollIntoView?.({ block: "nearest" });
  }

  return (
    <div className="evidence-candidates">
      <div className="evidence-toolbar" ref={toolbar}>
        <span className="evidence-count">{t("Showing {from}–{to} of {total}", { from, to, total: hits.length })}</span>
        <span className="evidence-selection-summary">{t("{pinned} pinned · {excluded} excluded", { pinned: pinned.length, excluded: excluded.length })}</span>
        <div className="evidence-toolbar-actions">
          <button className="button" type="button" onClick={() => setExpanded(new Set(hits.map((hit) => hit.chunk_id)))}>{t("Expand all")}</button>
          <button className="button" type="button" onClick={() => setExpanded(new Set())}>{t("Collapse all")}</button>
          {pages > 1 && (
            <nav className="evidence-pager" aria-label={t("Evidence pages")}>
              <button className="button" type="button" disabled={page === 0} aria-label={t("Previous page")} onClick={() => goTo(page - 1)}><ChevronLeft size={16} aria-hidden="true" /></button>
              <span>{page + 1}/{pages}</span>
              <button className="button" type="button" disabled={page >= pages - 1} aria-label={t("Next page")} onClick={() => goTo(page + 1)}><ChevronRight size={16} aria-hidden="true" /></button>
            </nav>
          )}
          {selectable && pinned.length + excluded.length > 0 && <button className="button primary" type="button" disabled={busy} onClick={onUseSelected}>{t("Review again with selected evidence")}</button>}
        </div>
      </div>
      <div className="evidence-selection-guide" id={guideId}>
        <dl><div><dt><PinIcon size={13} aria-hidden="true" />{t("Pin")}</dt><dd>{t("Include this evidence first when reviewing the answer again.")}</dd></div><div><dt><CircleMinus size={13} aria-hidden="true" />{t("Exclude")}</dt><dd>{t("Leave this evidence out of the next review.")}</dd></div></dl>
        <p>{t("Pinning does not guarantee that the answer cites this evidence.")}</p>
        <p>{t("Selections apply when you review again. The current answer stays unchanged, and a new answer is added.")}</p>
        {!selectable && <p>{t("This saved result cannot change evidence. Run the question again to retrieve a fresh selection.")}</p>}
      </div>
      {items.map((hit) => (
        <EvidenceCard
          key={hit.chunk_id}
          hit={hit}
          bodyId={`evidence-${message.id}-${hit.chunk_id}`}
          guideId={guideId}
          expanded={expanded.has(hit.chunk_id)}
          pinned={pinned.includes(hit.chunk_id)}
          excluded={excluded.includes(hit.chunk_id)}
          selectable={selectable}
          onToggle={() => toggle(hit.chunk_id)}
          onMark={(mode) => onMark(hit.chunk_id, mode)}
        />
      ))}
    </div>
  );
}

interface EvidenceCardProps {
  hit: EvidenceHit;
  bodyId: string;
  guideId: string;
  expanded: boolean;
  pinned: boolean;
  excluded: boolean;
  selectable: boolean;
  onToggle: () => void;
  onMark: (mode: "pin" | "exclude") => void;
}

/** One candidate: a heading toggle plus badges and the Pin / Exclude actions in the header, the body only while open. */
function EvidenceCard({ hit, bodyId, guideId, expanded, pinned, excluded, selectable, onToggle, onMark }: EvidenceCardProps) {
  const { t } = useI18n();
  return (
    <article className={`evidence-hit${pinned ? " pinned" : ""}${excluded ? " excluded" : ""}`}>
      <div className="evidence-card-header">
        <button className="evidence-card-toggle" type="button" aria-expanded={expanded} aria-controls={expanded ? bodyId : undefined} title={hit.citation} onClick={onToggle}>
          {expanded ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
          <strong className="evidence-heading">{evidenceHeading(hit)}</strong>
        </button>
        <div className="evidence-meta">
          <span className="doc-chip">{hit.doc_id}</span>
          {hit.kind === "table" && <span className="kind-badge">{t("table")}</span>}
          <span>{t("chars")}{" "}{hit.start_char}–{hit.end_char}</span>
        </div>
        <div className="evidence-actions" aria-describedby={guideId}>
          <button type="button" disabled={!selectable} aria-pressed={pinned} data-action="pin" title={t("Include this evidence first when reviewing the answer again.")} onClick={() => onMark("pin")}><PinIcon size={13} aria-hidden="true" />{t("Pin")}</button>
          <button type="button" disabled={!selectable} aria-pressed={excluded} data-action="exclude" title={t("Leave this evidence out of the next review.")} onClick={() => onMark("exclude")}><CircleMinus size={13} aria-hidden="true" />{t("Exclude")}</button>
        </div>
      </div>
      {expanded && (
        <div className="evidence-card-body" id={bodyId}>
          <span className="evidence-citation">{hit.citation}</span>
          <p>{hit.body}</p>
        </div>
      )}
    </article>
  );
}
