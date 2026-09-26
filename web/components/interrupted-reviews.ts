import { finishReviewProgress } from "@/components/review-progress";
import type { Conversation } from "@/lib/types";

// Application status text, not a generated answer. It is stored as this canonical English source and
// translated when rendered, so a conversation saved in one language reads correctly in the other.
export const INTERRUPTION_NOTICE = "The request was interrupted. Send the question again.";

/** Identify the app's own interruption notice by its exact stored text; nothing else is matched. */
export function isInterruptionNotice(message: { role: string; text?: string }): boolean {
  return message.role === "assistant" && message.text?.trim() === INTERRUPTION_NOTICE;
}

/** Restored requests cannot resume themselves after a reload or browser import. */
export function restoreInterruptedConversations(saved: Conversation[]): Conversation[] {
  return saved.map((conversation) => ({ ...conversation, messages: conversation.messages.map((message) => message.pending ? { ...message, pending: false, text: INTERRUPTION_NOTICE, execution: message.execution ? finishReviewProgress(message.execution, "failed", Math.max(0, Date.now() - (message.execution.startedAt ?? Date.now()))) : undefined } : message) }));
}
