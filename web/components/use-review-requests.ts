import { useRef, useState, type Dispatch, type RefObject, type SetStateAction } from "react";

import { useNotifications } from "@/components/notifications";
import { candidateProgress, finishReviewProgress, initialReviewProgress, resolvedScopeFromServer, reviewProgressFromEvent } from "@/components/review-progress";
import { extractTrace, runDiagnostics, terminalAnswer, terminalCitationCount, terminalEvidenceLabel, terminalFailureFix } from "@/components/review-response";
import { ApiError, getReleaseLimits, retrieveEvidence, streamReview } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { NavigationTarget } from "@/lib/navigation";
import { notificationErrorDetail, notificationErrorMessage, type NotificationDetail } from "@/lib/notification-registry";
import { reviewLimitationMessage, scopeFailurePatch, scopeFailureProgress } from "@/lib/scope-failure";
import { saveConversations } from "@/lib/storage";
import type { ChatMessage, Conversation, EvidenceHit, ReviewSessionDraft } from "@/lib/types";
import type { useRuntimeHealth } from "@/lib/use-runtime-health";

/** The assistant message a running request writes into, and the conversation that owns it. */
export interface ReviewTarget {
  conversationId: string;
  messageId: string;
}

interface ReviewRequestOptions {
  active: Conversation | undefined;
  activeId: string;
  /** Session draft used while the conversation has not stored a profile of its own. */
  fallbackProfile: ReviewSessionDraft;
  sessionProfile: ReviewSessionDraft;
  localModel: string | null;
  sendBlocked: boolean;
  developer: boolean;
  view: NavigationTarget["view"];
  query: string;
  setQuery: (value: string | ((current: string) => string)) => void;
  setConversations: Dispatch<SetStateAction<Conversation[]>>;
  /** Owned by the shell so a fresh start, a deletion or unmounting can cancel the running request. */
  reviewAbort: RefObject<AbortController | null>;
  /** Called when a request reserves its assistant message, so the transcript can follow it. */
  onReviewStarted: (target: ReviewTarget) => void;
  setDailyBudgetResetAt: (resetAt: string | null) => void;
  checkRuntimeHealth: ReturnType<typeof useRuntimeHealth>["check"];
}

/**
 * Send questions and selected-evidence reruns, streaming progress into a reserved assistant message.
 *
 * Every write goes to the conversation that started the request, so switching conversations or
 * workspaces while a review streams never redirects its answer.
 */
export function useReviewRequests({
  active, activeId, fallbackProfile, sessionProfile, localModel, sendBlocked, developer, view, query, setQuery,
  setConversations, reviewAbort, onReviewStarted, setDailyBudgetResetAt, checkRuntimeHealth,
}: ReviewRequestOptions) {
  const { t } = useI18n();
  const { notify } = useNotifications();
  const [busy, setBusy] = useState(false);
  const [activeReview, setActiveReview] = useState<ReviewTarget | null>(null);
  // A request settles after an await, when the user may have moved to another conversation or workspace.
  const currentConversationId = useRef(activeId);
  currentConversationId.current = activeId;
  const currentView = useRef(view);
  currentView.current = view;

  function conversationTitle(messages: ChatMessage[]): string {
    return (messages.find((message) => message.role === "user")?.text ?? "New review").slice(0, 52);
  }

  /**
   * Replace the active conversation's messages. Reads the current list at update time
   * so a change made while a review streams (a toolbar edit, a pin) is not reverted.
   */
  function updateActive(messages: ChatMessage[]) {
    const targetId = activeId;
    setConversations((current) => saveConversations(current.map((conversation) =>
      conversation.id === targetId
        ? {
            ...conversation,
            title: conversationTitle(messages),
            updatedAt: new Date().toISOString(),
            messages,
          }
        : conversation,
    )));
  }

  /** Append submitted messages atomically to their original conversation. */
  function appendMessage(conversationId: string, added: ChatMessage | ChatMessage[]) {
    setConversations((current) => saveConversations(current.map((conversation) => {
      if (conversation.id !== conversationId) return conversation;
      const messages = [...conversation.messages, ...(Array.isArray(added) ? added : [added])];
      return { ...conversation, title: conversationTitle(messages), updatedAt: new Date().toISOString(), messages };
    })));
  }

  /** Update one reserved assistant identity without overwriting concurrent profile or evidence edits. */
  function updateMessage(conversationId: string, messageId: string, patch: Partial<Omit<ChatMessage, "id" | "role">>, notificationDetail?: NotificationDetail) {
    if (patch.pending === false && currentView.current !== "review") {
      const failed = patch.execution?.outcome === "failed";
      const cancelled = patch.execution?.outcome === "cancelled";
      const limited = patch.execution?.outcome === "limited";
      notify(limited && patch.execution?.pathDecision ? reviewLimitationMessage(patch.execution.pathDecision, t) : failed ? patch.text ?? t("Review failed.") : t(cancelled ? "Review cancelled." : "Review completed."), failed ? "error" : cancelled || limited ? "warning" : "success", `review:${conversationId}:${messageId}`, undefined, { event: "review-result", target: { view: "review", conversationId }, title: limited ? "Request scope guidance" : failed ? "Review failed" : cancelled ? "Review cancelled" : "Review completed", detail: limited ? undefined : notificationDetail });
    }
    setConversations((current) => saveConversations(current.map((conversation) => conversation.id === conversationId ? { ...conversation, updatedAt: new Date().toISOString(), messages: conversation.messages.map((message) => message.id === messageId ? { ...message, ...patch } : message) } : conversation)));
  }

  /** One-off read of the reset time after a `daily_cost_limit` error so the banner can say when answers resume. */
  function noteDailyBudget(reason: unknown) {
    if (reason instanceof ApiError && reason.code === "daily_cost_limit") {
      void getReleaseLimits().then((limits) => setDailyBudgetResetAt(limits.daily_cost_reset_at_utc)).catch(() => undefined);
    }
  }

  async function submit() {
    const question = query.trim();
    if (!question || busy || !active || sendBlocked) return;
    setQuery("");
    setBusy(true);
    const requestStarted = Date.now();
    let execution = initialReviewProgress(false, 0, (active.profile ?? fallbackProfile).corpus_scope);

    reviewAbort.current?.abort();
    const controller = new AbortController();
    reviewAbort.current = controller;
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", text: question };
    const conversationId = active.id;
    const assistantId = crypto.randomUUID();
    const pending = [...active.messages, userMessage];
    const target = { conversationId, messageId: assistantId };
    onReviewStarted(target);
    setActiveReview(target);
    let preparedEvidence: EvidenceHit[] = [];
    const selectedProfile = { ...sessionProfile, local_model: localModel };
    appendMessage(conversationId, [userMessage, { id: assistantId, role: "assistant", text: "", pending: true, execution, question }]);
    try {
      let evidence: EvidenceHit[] = [];
      let candidateToken: string | undefined;
      const history = pending
        .slice(0, -1)
        .filter((message) => !message.pending && message.text.trim() && (message.role === "user" || message.role === "assistant"))
        .map((message) => ({ role: message.role, text: message.text }));
      const response = await streamReview(
        question,
        selectedProfile,
        null,
        history,
        (event) => { if (controller.signal.aborted) return; execution = reviewProgressFromEvent(event, execution); updateMessage(conversationId, assistantId, { execution }); },
        controller.signal,
        (payload) => {
          if (controller.signal.aborted) return;
          evidence = payload.candidates.length ? payload.candidates : payload.results;
          preparedEvidence = evidence;
          candidateToken = payload.candidate_token ?? undefined;
          execution = candidateProgress(execution, evidence.length, payload.resolved_scope, payload.path_decision);
          updateMessage(conversationId, assistantId, { execution });
        },
      );
      if (controller.signal.aborted) throw new DOMException("Request cancelled", "AbortError");
      const answer = terminalAnswer(response);
      const terminal = (response.run ?? response) as Record<string, unknown>;
      execution = finishReviewProgress(execution, terminal.failure ? "failed" : "completed", Date.now() - requestStarted, terminal.execution, terminal.report);
      setDailyBudgetResetAt(null);
      const assistant: Partial<ChatMessage> = {
        pending: false,
        text: answer,
        execution,
        performance: terminal.execution as Record<string, unknown> | undefined,
        evidence,
        evidenceLabel: terminalEvidenceLabel(response),
        citations: terminalCitationCount(response),
        trace: extractTrace(response),
        diagnostics: runDiagnostics(response),
        failureFix: terminalFailureFix(response),
        question,
        candidateToken,
        pinnedChunkIds: [],
        excludedChunkIds: [],
      };
      updateMessage(conversationId, assistantId, assistant, notificationErrorDetail(terminal.failure));
    } catch (reason) {
      execution = scopeFailureProgress(reason, execution);
      execution = finishReviewProgress(execution, controller.signal.aborted ? "cancelled" : "failed", Date.now() - requestStarted);
      const scopeFailure = scopeFailurePatch(reason, developer);
      if (scopeFailure && !controller.signal.aborted) {
        updateMessage(conversationId, assistantId, { ...scopeFailure, pending: false, execution }, notificationErrorDetail(reason));
        return;
      }
      if (isInfrastructureFailure(reason)) {
        updateMessage(conversationId, assistantId, { pending: false, execution, text: reason instanceof Error ? reason.message : t("The review could not be completed.") }, notificationErrorDetail(reason));
        if (currentConversationId.current === conversationId) setQuery((current) => current || question);
        await checkRuntimeHealth();
        return;
      }
      let evidence = preparedEvidence;
      // The provider gate and the daily cost limiter both reject before retrieval runs,
      // so fetch the evidence separately for the evidence-only reply.
      if (reason instanceof ApiError && reason.code === "provider_unavailable" && !evidence.length) {
        try {
          const retrieved = await retrieveEvidence(question, selectedProfile);
          evidence = retrieved.candidates.length ? retrieved.candidates : retrieved.results;
          execution = { ...execution, resolvedScope: resolvedScopeFromServer(retrieved.resolved_scope) ?? execution.resolvedScope };
        } catch {
          // Preserve the original provider error when retrieval is also unavailable.
        }
      }
      noteDailyBudget(reason);
      const message =
        controller.signal.aborted ? t("Request cancelled") :
        reason instanceof ApiError && reason.code === "daily_cost_limit"
          ? notificationErrorMessage(reason)
          : reason instanceof ApiError && reason.code === "provider_unavailable" && evidence.length
            ? "No answer model is configured. Retrieved filing evidence is shown below without a generated answer. See Build › step 6."
          : reason instanceof Error
            ? reason.message
            : "The review could not be completed.";
      updateMessage(conversationId, assistantId, {
        pending: false,
        text: message,
        execution,
        evidence,
        evidenceLabel: "Retrieved candidates — answer not generated",
      }, notificationErrorDetail(reason));
    } finally {
      if ((active.profile ?? fallbackProfile).engine === "local") void checkRuntimeHealth(true);
      setBusy(false);
      setActiveReview(null);
      if (reviewAbort.current === controller) reviewAbort.current = null;
    }
  }

  function markEvidence(messageId: string, chunkId: number, mode: "pin" | "exclude") {
    if (!active) return;
    const messages = active.messages.map((message) => {
      if (message.id !== messageId) return message;
      const pins = new Set(message.pinnedChunkIds ?? []);
      const excludes = new Set(message.excludedChunkIds ?? []);
      if (mode === "pin") {
        excludes.delete(chunkId);
        pins.has(chunkId) ? pins.delete(chunkId) : pins.add(chunkId);
      } else {
        pins.delete(chunkId);
        excludes.has(chunkId) ? excludes.delete(chunkId) : excludes.add(chunkId);
      }
      return { ...message, pinnedChunkIds: [...pins], excludedChunkIds: [...excludes] };
    });
    updateActive(messages);
  }

  async function reviewSelectedEvidence(message: ChatMessage) {
    if (!active || !message.question || !message.candidateToken || busy || sendBlocked) return;
    setBusy(true);
    const conversationId = active.id;
    const selected = (message.evidence ?? []).filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)).length;
    const requestStarted = Date.now();
    let execution = initialReviewProgress(true, selected, (active.profile ?? fallbackProfile).corpus_scope);
    const assistantId = crypto.randomUUID();
    const target = { conversationId, messageId: assistantId };
    onReviewStarted(target);
    setActiveReview(target);
    appendMessage(conversationId, { id: assistantId, role: "assistant", text: "", pending: true, execution, question: message.question });
    const controller = new AbortController();
    reviewAbort.current = controller;
    try {
      // Reuse the context that produced this candidate snapshot, excluding its question and later turns.
      const messageIndex = active.messages.findIndex((item) => item.id === message.id);
      const questionIndex = active.messages.slice(0, Math.max(0, messageIndex)).findLastIndex((item) => item.role === "user" && item.text === message.question);
      const historyTurns = sessionProfile.prompt_policy.history_turns;
      const originalHistory = active.messages.slice(0, Math.max(0, questionIndex))
        .filter((item) => !item.pending && item.text.trim() && (item.role === "user" || item.role === "assistant"))
        .map((item) => ({ role: item.role, text: item.text }));
      const response = await streamReview(
        message.question,
        sessionProfile,
        {
          candidateToken: message.candidateToken,
          pinned: message.pinnedChunkIds ?? [],
          excluded: message.excludedChunkIds ?? [],
        },
        historyTurns > 0 ? originalHistory.slice(-historyTurns) : [],
        (event) => { if (controller.signal.aborted) return; execution = reviewProgressFromEvent(event, execution); updateMessage(conversationId, assistantId, { execution }); },
        controller.signal,
      );
      if (controller.signal.aborted) throw new DOMException("Request cancelled", "AbortError");
      setDailyBudgetResetAt(null);
      const terminal = (response.run ?? response) as Record<string, unknown>;
      execution = finishReviewProgress(execution, terminal.failure ? "failed" : "completed", Date.now() - requestStarted, terminal.execution, terminal.report);
      updateMessage(conversationId, assistantId, {
        pending: false,
        execution,
        performance: terminal.execution as Record<string, unknown> | undefined,
        text: terminalAnswer(response),
        evidence: message.evidence?.filter((hit) => !(message.excludedChunkIds ?? []).includes(hit.chunk_id)),
        evidenceLabel: terminalEvidenceLabel(response),
        citations: terminalCitationCount(response),
        trace: extractTrace(response),
        diagnostics: runDiagnostics(response),
        failureFix: terminalFailureFix(response),
      }, notificationErrorDetail(terminal.failure));
    } catch (reason) {
      execution = scopeFailureProgress(reason, execution);
      execution = finishReviewProgress(execution, controller.signal.aborted ? "cancelled" : "failed", Date.now() - requestStarted);
      const scopeFailure = scopeFailurePatch(reason, developer);
      if (scopeFailure && !controller.signal.aborted) {
        updateMessage(conversationId, assistantId, { ...scopeFailure, pending: false, execution }, notificationErrorDetail(reason));
        return;
      }
      updateMessage(conversationId, assistantId, { pending: false, text: controller.signal.aborted ? t("Request cancelled") : reason instanceof Error ? reason.message : t("Selected evidence review failed."), execution }, notificationErrorDetail(reason));
      noteDailyBudget(reason);
      notify(reason instanceof Error ? notificationErrorMessage(reason) : t("Selected evidence review failed."), "error", "evidence-review", undefined, { event: "evidence-review-error", detail: notificationErrorDetail(reason) });
    } finally {
      if ((active.profile ?? fallbackProfile).engine === "local") void checkRuntimeHealth(true);
      setBusy(false);
      setActiveReview(null);
      if (reviewAbort.current === controller) reviewAbort.current = null;
    }
  }

  return { busy, activeReview, submit, reviewSelectedEvidence, markEvidence };
}

function isInfrastructureFailure(reason: unknown): boolean {
  return reason instanceof TypeError || (
    reason instanceof ApiError
    && ["database_unavailable", "service_unavailable"].includes(reason.code)
  );
}
