import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";

import { saveConversations } from "@/lib/storage";
import type { Conversation } from "@/lib/types";

/**
 * Keep each conversation's composer draft independent without serializing on every keystroke.
 *
 * Typing only marks the list dirty; a 300 ms pause saves it, and hiding or leaving the page flushes it.
 */
export function useConversationDraft(active: Conversation | undefined, conversations: Conversation[], setConversations: Dispatch<SetStateAction<Conversation[]>>) {
  const currentConversations = useRef(conversations);
  currentConversations.current = conversations;
  const draftSavePending = useRef(false);
  const query = active?.draft ?? "";

  function setQuery(value: string | ((current: string) => string)) {
    const targetId = active?.id;
    setConversations((current) => current.map((conversation) => {
      if (conversation.id !== targetId) return conversation;
      const draft = typeof value === "function" ? value(conversation.draft ?? "") : value;
      if (draft === (conversation.draft ?? "")) return conversation;
      draftSavePending.current = true;
      return { ...conversation, draft };
    }));
  }

  /** Flush the latest conversation state before leaving the page or unmounting. */
  const saveDraft = useCallback(() => {
    if (!draftSavePending.current) return;
    saveConversations(currentConversations.current);
    draftSavePending.current = false;
  }, []);
  useEffect(() => {
    if (!draftSavePending.current) return;
    const timer = window.setTimeout(saveDraft, 300);
    return () => window.clearTimeout(timer);
  }, [conversations, saveDraft]);
  useEffect(() => {
    /** Mobile browsers may hide a page without delivering pagehide before termination. */
    const saveWhenHidden = () => { if (document.visibilityState === "hidden") saveDraft(); };
    window.addEventListener("pagehide", saveDraft);
    document.addEventListener("visibilitychange", saveWhenHidden);
    return () => {
      window.removeEventListener("pagehide", saveDraft);
      document.removeEventListener("visibilitychange", saveWhenHidden);
      saveDraft();
    };
  }, [saveDraft]);
  return { query, setQuery };
}
