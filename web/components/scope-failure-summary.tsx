"use client";

import { useI18n } from "@/lib/i18n";
import type { ChatMessage } from "@/lib/types";

/** Add diagnosis to the existing failed-answer surface, with technical detail kept in Run details. */
export function ScopeFailureSummary({ message, developer, onOpenFix }: { message: ChatMessage; developer: boolean; onOpenFix?: (category: NonNullable<ChatMessage["failureFix"]>["category"]) => void }) {
  const { t } = useI18n();
  const failure = message.scopeFailure;
  if (!failure) return null;
  return <div className="notice" role="alert">
    <p>{t(developer ? failure.causeText : "Corpus metadata is unavailable. Try again later.")}</p>
    {developer && <>
      {failure.path && <p>{t("Manifest file")}: <code>{failure.path}</code></p>}
      {failure.jobId && <p>{t("Recent corpus job")}: <code>{failure.jobId}</code></p>}
      {failure.jobRunning && <p>{t("A corpus acquisition job is queued or running. Wait for it to finish, then retry.")}</p>}
      <p>{t("Terminal check")}: <code>rag-schema check</code> · <code>rag-corpus status</code></p>
      {message.failureFix && onOpenFix && <button type="button" className="button" onClick={() => onOpenFix(message.failureFix!.category)}>{t(message.failureFix.label)}</button>}
    </>}
  </div>;
}
