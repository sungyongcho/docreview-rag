"use client";
import { Send } from "lucide-react";
import { useEffect, useRef, type RefObject } from "react";

import { useI18n } from "@/lib/i18n";

interface QuestionComposerProps {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  /** The caller's reasons to refuse a send; an empty question disables Send as well. */
  sendDisabled: boolean;
}

/** Question field: Enter sends, Shift+Enter adds a line, and the Enter that confirms an IME composition never sends. */
export function QuestionComposer({ inputRef, query, onQueryChange, onSubmit, sendDisabled }: QuestionComposerProps) {
  const { t } = useI18n();
  const composing = useRef(false);
  useEffect(() => {
    // Grow with the draft up to the CSS max-height; browsers without field-sizing need the measurement.
    const element = inputRef.current;
    if (!element || "fieldSizing" in element.style) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
  }, [query]);
  return (
    <label className="composer">
      <textarea ref={inputRef} data-help="review.composer" value={query} onChange={(event) => onQueryChange(event.target.value)} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { if (composing.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return; event.preventDefault(); onSubmit(); } }} placeholder={t("Ask a question about the filing corpus")} rows={1} />
      <button data-tour="send" data-help="review.send" type="button" aria-label={t("Send question")} disabled={sendDisabled || !query.trim()} onClick={onSubmit}><Send size={17} /></button>
    </label>
  );
}
