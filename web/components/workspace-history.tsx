"use client";

import { ArrowLeft, ArrowRight, Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import "./workspace-history.css";

interface WorkspaceHistoryProps {
  entries: Array<{ id: string; label: string }>;
  currentIndex: number;
  onJump: (index: number) => void;
  onBack: () => void;
  onForward: () => void;
}

/** Present one browser-history cursor without owning or duplicating browser navigation state. */
export function WorkspaceHistory({ entries, currentIndex, onJump, onBack, onForward }: WorkspaceHistoryProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(currentIndex);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<Array<HTMLButtonElement | null>>([]);
  const listId = useId();
  const current = entries[currentIndex];
  const back = entries[currentIndex - 1];
  const forward = entries[currentIndex + 1];

  /** Return focus to the title whenever the history picker is dismissed. */
  function close() { setOpen(false); trigger.current?.focus(); }
  /** Rove focus through existing options without changing the current history entry. */
  function focusOption(index: number) {
    const next = Math.max(0, Math.min(entries.length - 1, index));
    setFocused(next); options.current[next]?.focus();
  }
  useEffect(() => {
    if (!open) return;
    options.current[currentIndex]?.focus();
    setFocused(currentIndex);
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, currentIndex]);

  return <div className="workspace-history" ref={root}>
    <button className="workspace-history-arrow" type="button" aria-label={t("Back")} title={back ? `${t("Back")}: ${back.label}` : t("Back")} disabled={!back} onClick={onBack}><ArrowLeft size={17} /></button>
    <button className="workspace-history-title" type="button" ref={trigger} aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} disabled={!current} onClick={() => open ? close() : setOpen(true)} onKeyDown={(event) => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); } }}>
      <strong>{current?.label ?? t("Navigation history")}</strong><ChevronDown size={13} aria-hidden="true" />
    </button>
    <button className="workspace-history-arrow" type="button" aria-label={t("Forward")} title={forward ? `${t("Forward")}: ${forward.label}` : t("Forward")} disabled={!forward} onClick={onForward}><ArrowRight size={17} /></button>
    <div id={listId} role="listbox" aria-label={t("Navigation history")} className="workspace-history-list" hidden={!open} onKeyDown={(event) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
      else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault(); focusOption(event.key === "Home" ? 0 : event.key === "End" ? entries.length - 1 : focused + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault(); if (entries[focused]) onJump(focused); close();
      } else if (event.key === "Tab") setOpen(false);
    }}>
      {entries.map((entry, index) => <button key={entry.id} ref={(element) => { options.current[index] = element; }} type="button" role="option" aria-selected={index === currentIndex} tabIndex={open && index === focused ? 0 : -1} onFocus={() => setFocused(index)} onClick={() => { onJump(index); close(); }}>
        <span>{entry.label}</span>{index === currentIndex && <Check size={14} aria-hidden="true" />}
      </button>)}
    </div>
  </div>;
}
