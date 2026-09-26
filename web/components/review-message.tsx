"use client";
import { ArrowUpRight } from "lucide-react";
import { useRef, useState } from "react";

import { EvidenceCandidates } from "@/components/evidence-candidates";
import { INTERRUPTION_NOTICE, isInterruptionNotice } from "@/components/interrupted-reviews";
import { MarkdownMessage } from "@/components/markdown-message";
import { PathDecisionBadge, ReviewProgressSteps } from "@/components/review-progress";
import type { DisclosureStage } from "@/components/review-stage-details";
import { ScopeFailureSummary } from "@/components/scope-failure-summary";
import { useI18n } from "@/lib/i18n";
import { isReviewLimitation, reviewLimitationMessage } from "@/lib/scope-failure";
import type { ChatMessage } from "@/lib/types";

interface ReviewMessageProps {
  onOpenFix?: (category: NonNullable<ChatMessage["failureFix"]>["category"]) => void;
  message: ChatMessage;
  catalogMode?: "live" | "published";
  onStop?: () => void;
  onSwitchScope?: () => void;
  onOpenDetails?: (stage?: DisclosureStage) => void;
  /** The newest message carrying evidence; only that one gets the `review.evidence` help hook. */
  latestEvidence: boolean;
  busy: boolean;
  onMark: (chunkId: number, mode: "pin" | "exclude") => void;
  onUseSelected: () => void;
}

/** Verdict pill derived from the terminal label; conversation replies carry no label and get no pill. */
function verdictPill(message: ChatMessage): { className: string; text: string } | null {
  if (message.evidenceLabel === "Cited evidence") {
    const count = message.citations ?? message.evidence?.length ?? 0;
    return { className: "supported", text: `Supported · ${count} citation${count === 1 ? "" : "s"}` };
  }
  if (message.evidenceLabel === "Related evidence — not direct support") return { className: "not-in-docs", text: "Not in documents" };
  if (message.evidenceLabel === "Retrieved candidates — answer not generated") return { className: "failed", text: "Answer not generated" };
  const decision = message.execution?.pathDecision;
  if (isReviewLimitation(decision) && decision?.stopping_reason === "unsupported_request") return { className: "unsupported-request", text: "Unsupported request" };
  return null;
}

export function ReviewMessage({ message, catalogMode, latestEvidence, busy, onStop, onSwitchScope, onMark, onUseSelected, onOpenDetails, onOpenFix }: ReviewMessageProps) {
  const { t } = useI18n();
  const [summaryOpen, setSummaryOpen] = useState(Boolean(message.pending));
  const pill = message.role === "assistant" ? verdictPill(message) : null;
  const article = useRef<HTMLElement>(null);
  /** Reveal only this message's evidence list when its report stage links to candidates. */
  function showEvidence() {
    const evidence = article.current?.querySelector<HTMLDetailsElement>("details.evidence");
    if (!evidence) return;
    evidence.open = true;
    evidence.querySelector<HTMLElement>("summary")?.focus({ preventScroll: true });
    evidence.scrollIntoView?.({ block: "nearest" });
  }
  return (
    <article ref={article} className={`message ${message.role}${message.pending ? " pending" : ""}`} data-message-id={message.id} aria-busy={message.pending || undefined}>
      <div className="message-role">{message.role === "user" ? t("You") : t("DocReview RAG")}</div>
      <div className="message-body">
        {pill && <span className={`verdict ${pill.className}`}>{t(pill.text)}</span>}
        {message.execution?.pathDecision && <PathDecisionBadge decision={message.execution.pathDecision} catalogMode={catalogMode} />}
        {message.role === "assistant" ? (message.text ? <MarkdownMessage>{isReviewLimitation(message.execution?.pathDecision) ? reviewLimitationMessage(message.execution!.pathDecision!, t) : message.scopeFailure ? t("Query scope metadata is unavailable.") : isInterruptionNotice(message) ? t(INTERRUPTION_NOTICE) : message.evidenceLabel === "Retrieved candidates — answer not generated" ? t(message.text) : message.text}</MarkdownMessage> : null) : <p>{message.text}</p>}
        {message.scopeFailure && <ScopeFailureSummary message={message} developer={catalogMode === "live"} onOpenFix={onOpenFix} />}
        {message.execution && <div className="review-execution-wrap"><details className="review-execution-summary" open={summaryOpen} onToggle={(event) => setSummaryOpen(event.currentTarget.open)}><summary>{t("Execution summary")}</summary><ReviewProgressSteps showDetailsAction={false} catalogMode={catalogMode} state={message.execution} performance={message.performance} finalLabel={message.evidenceLabel === "Cited evidence" ? "Supported" : message.evidenceLabel === "Related evidence — not direct support" ? "Not in documents" : message.evidenceLabel === "Retrieved candidates — answer not generated" ? "Answer not generated" : undefined} onSwitchScope={onSwitchScope} onOpenDetails={onOpenDetails} onShowEvidence={message.evidence?.length ? showEvidence : undefined} />{message.pending && onStop && <button className="button ghost" type="button" onClick={onStop}>{t("Stop request")}</button>}</details>{onOpenDetails && <div className="review-stage-actions"><button className="button review-summary-action" type="button" data-run-details-open onClick={() => onOpenDetails()}>{t("Open run details")}<ArrowUpRight size={14} aria-hidden="true" /></button></div>}</div>}
        {message.evidence?.length ? (
          <>
            <details className="evidence" data-help={latestEvidence ? "review.evidence" : undefined}>
              <summary data-tour="evidence-toggle">{t(message.evidenceLabel === "Cited evidence" ? "Retrieved evidence candidates" : message.evidenceLabel ?? "Retrieved candidates")} · {message.evidence.length}</summary>
              <EvidenceCandidates key={message.id} message={message} busy={busy} onMark={onMark} onUseSelected={onUseSelected} />
            </details>
          </>
        ) : null}
        {message.role === "assistant" && !message.execution && (message.performance || message.diagnostics?.length || message.trace) && onOpenDetails && <button className="button ghost" type="button" data-run-details-open data-help="review.run-trace" onClick={() => onOpenDetails()}>{t("Run details")}</button>}
      </div>
    </article>
  );
}
