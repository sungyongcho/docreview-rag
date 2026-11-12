"use client";
import { CircleAlert } from "lucide-react";

import { evidenceHoldSentence, reportPeriodLabel } from "@/lib/evidence-holds";
import { useI18n } from "@/lib/i18n";
import type { EvidenceHold } from "@/lib/types";
import "./evidence-hold-notice.css";

/**
 * Say which report periods a search or an answer could not use, and why.
 *
 * Shown with retrieval results and with an answer, so an empty or short result reads as
 * evidence on hold instead of as absence. Renders nothing when nothing is held.
 */
export function EvidenceHoldNotice({ holds }: { holds: readonly EvidenceHold[] | undefined }) {
  const { t } = useI18n();
  if (!holds?.length) return null;
  return (
    <aside className="evidence-hold-notice" role="note" aria-label={t("Evidence on hold")}>
      <strong className="evidence-hold-title"><CircleAlert size={14} aria-hidden="true" />{t("Evidence on hold")}</strong>
      <p>{t("A later filing keeps the text below out of evidence. An empty or short result can mean the evidence is on hold, not that the filings never said it.")}</p>
      <ul>
        {holds.map((hold) => (
          <li key={`${hold.registry}:${hold.issuer}:${hold.fiscal_year}:${hold.reason}`}>
            <span className="evidence-hold-period">{reportPeriodLabel(hold, t)}</span>
            <span>{evidenceHoldSentence(hold, t)}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}
