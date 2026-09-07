import type { EvidenceHit } from "@/lib/types";

/** Candidates rendered per page; a 30-candidate list becomes six short pages. */
export const EVIDENCE_PAGE_SIZE = 5;

/** Saved conversations predate the `section_title` field, so a heading tolerates its absence. */
type HeadingSource = Pick<EvidenceHit, "citation"> & { section_title?: string | null };

/**
 * Heading for one evidence card: the registry's section label taken from the citation, followed
 * by the section title when the label does not already spell it. EDGAR gives
 * `Item 7 - (Management's Discussion and Analysis)`; a DART label such as `II. 사업의 내용`
 * already carries its title and is shown as is; a hit without a title keeps the bare label.
 */
export function evidenceHeading(hit: HeadingSource): string {
  const label = hit.citation.split(" · ").pop()?.trim() || hit.citation;
  const title = hit.section_title?.trim();
  return title && !label.includes(title) ? `${label} - (${title})` : label;
}

export interface EvidencePage<T> {
  items: T[];
  /** Zero-based page actually shown after clamping. */
  page: number;
  pages: number;
  /** One-based bounds of the shown slice; both 0 for an empty list. */
  from: number;
  to: number;
}

/** Slice one page out of `items`, clamping `page` so a shrinking list never shows an empty page. */
export function evidencePage<T>(items: readonly T[], page: number, size = EVIDENCE_PAGE_SIZE): EvidencePage<T> {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(page, 0), pages - 1);
  const start = current * size;
  const slice = items.slice(start, start + size);
  return { items: slice, page: current, pages, from: slice.length ? start + 1 : 0, to: start + slice.length };
}
