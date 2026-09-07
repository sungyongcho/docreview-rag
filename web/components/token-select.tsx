"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Plus, X } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import "./token-select.css";

export interface TokenOption {
  value: string;
  label: string;
  badge?: { label: string; tone: "blue" | "amber" };
}

interface Props {
  label: string;
  values: string[];
  options: TokenOption[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  hint?: string;
  disabled?: boolean;
  /** Custom parsing is available only for fields that accept values outside the corpus. */
  parseCustom?: (value: string) => string[] | null;
  invalidMessage?: string;
  invalidValues?: string[];
  quickOptions?: TokenOption[];
  onValidityChange?: (valid: boolean) => void;
  overlayOptions?: boolean;
  /** Checkable choices remain visible for repeated multi-selection. */
  checkable?: boolean;
  hideValues?: boolean;
  commitOnBlur?: boolean;
  autoFocus?: boolean;
}

/** Keep editing text separate from committed filters and expose keyboard-friendly choices. */
export function TokenSelect({ label, values, options, onChange, placeholder, hint, disabled, parseCustom, invalidMessage, invalidValues = [], quickOptions, onValidityChange, overlayOptions = false, checkable = false, hideValues = false, commitOnBlur = true, autoFocus = false }: Props) {
  const { t } = useI18n();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const choices = useRef<HTMLDivElement>(null);
  const focusChoicesAfterOpen = useRef(false);
  const [draft, setDraft] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const query = draft.trim().toLocaleLowerCase();
  const suggestions = options.filter((option) => (checkable || !values.includes(option.value)) && `${option.value} ${option.label}`.toLocaleLowerCase().includes(query));

  /** Prefer actual labels and codes before parsing independent pasted tokens. */
  function resolve(text: string): string[] | null {
    const trimmed = text.trim();
    if (!trimmed) return [];
    const exact = options.find((option) => [option.value, option.label].some((part) => part.toLocaleLowerCase() === trimmed.toLocaleLowerCase()));
    if (exact) return [exact.value];
    const parts = trimmed.split(/[\s,;]+/).filter(Boolean);
    const result: string[] = [];
    for (const part of parts) {
      const option = options.find((candidate) => candidate.value.toLocaleLowerCase() === part.toLocaleLowerCase());
      const parsed = option ? [option.value] : parseCustom?.(part);
      if (!parsed?.length) return null;
      result.push(...parsed);
    }
    return result;
  }

  const parsed = resolve(draft);
  const valid = parsed !== null && invalidValues.length === 0;
  useEffect(() => { onValidityChange?.(valid); }, [valid, onValidityChange]);
  useEffect(() => {
    if (!expanded || !focusChoicesAfterOpen.current) return;
    focusChoicesAfterOpen.current = false;
    choices.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [expanded]);

  /** Commit the whole draft atomically so invalid entries remain visible for correction. */
  function commit(text = draft) {
    const next = resolve(text);
    if (next === null) { setAttempted(true); return; }
    if (next.length) onChange([...new Set([...values, ...next])]);
    setDraft("");
    setAttempted(false);
  }

  /** Add a known choice and return focus for another search. */
  function choose(option: TokenOption) {
    onChange(checkable && values.includes(option.value) ? values.filter((value) => value !== option.value) : [...new Set([...values, option.value])]);
    setDraft("");
    setAttempted(false);
    setExpanded(true);
    input.current?.focus();
  }

  const showError = (attempted || draft.trim().length > 0) && parsed === null;
  const suggestionPanel = (expanded && !disabled && <div id={`${id}-choices`} className="token-options" ref={choices} role="group" aria-label={t("{field} suggestions", { field: label })} onKeyDown={(event) => {
      if (!["ArrowDown", "ArrowUp", "Escape"].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
      const index = buttons.indexOf(event.target as HTMLButtonElement);
      if (event.key === "Escape" || (event.key === "ArrowUp" && index === 0)) { input.current?.focus(); if (event.key === "Escape") setExpanded(false); }
      else buttons[(index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length]?.focus();
    }}>
      {suggestions.length ? suggestions.map((option) => <button type="button" key={option.value} role={checkable ? "checkbox" : undefined} aria-checked={checkable ? values.includes(option.value) : undefined} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(option)}><span className="token-option-label">{option.label}{" "}{option.badge && <span className={`token-badge token-badge-${option.badge.tone}`}>{option.badge.label}</span>}</span><span aria-hidden="true">{checkable ? (values.includes(option.value) ? "☑" : "☐") : <Plus size={13} />}</span></button>) : <p className="token-hint">{t("No matching choices in this scope.")}</p>}
    </div>);

  return <div className={`token-select${overlayOptions ? " token-select-overlay" : ""}`} onBlur={(event) => {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setExpanded(false);
    if (commitOnBlur) commit();
  }}>
    <label className="token-select-label" htmlFor={id}>{label}</label>
    {!hideValues && values.length > 0 && <ul className="token-selection" aria-label={t("Selected {field}", { field: label })}>
      {values.map((value) => {
        const option = options.find((option) => option.value === value);
        const caption = option?.label ?? value;
        const invalid = invalidValues.includes(value);
        return <li className={`token-chip${invalid ? " token-chip-invalid" : ""}`} key={value}>
          <span>{caption}{invalid && <small>{t("Outside this scope")}</small>}</span>
          {option?.badge && <span className={`token-badge token-badge-${option.badge.tone}`}>{option.badge.label}</span>}
          <button type="button" disabled={disabled} aria-label={t("Remove {value}", { value: caption })} onClick={() => { onChange(values.filter((item) => item !== value)); input.current?.focus(); }}><X size={13} aria-hidden="true" /></button>
        </li>;
      })}
    </ul>}
    <div className="token-search-row">
      <input ref={input} id={id} value={draft} autoFocus={autoFocus} aria-expanded={expanded && !disabled} aria-controls={expanded && !disabled ? `${id}-choices` : undefined} placeholder={placeholder} disabled={disabled} autoComplete="off"
        aria-invalid={showError || invalidValues.length > 0}
        aria-describedby={`${id}-hint${showError ? ` ${id}-error` : ""}`}
        onFocus={() => setExpanded(true)}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          setAttempted(false);
          setExpanded(true);
          if (/[,;\n]$/.test(text)) commit(text);
        }}
        onPaste={(event) => {
          const text = event.clipboardData.getData("text");
          if (!text.trim()) return;
          event.preventDefault();
          const start = event.currentTarget.selectionStart ?? draft.length;
          const end = event.currentTarget.selectionEnd ?? start;
          const next = `${draft.slice(0, start)}${text}${draft.slice(end)}`;
          setDraft(next);
          commit(next);
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "Enter" || event.key === "," || event.key === ";") { event.preventDefault(); commit(); }
          if (event.key === "ArrowDown") {
            event.preventDefault();
            if (expanded) choices.current?.querySelector<HTMLButtonElement>("button")?.focus();
            else { focusChoicesAfterOpen.current = true; setExpanded(true); }
          }
          if (event.key === "Escape" && expanded) { event.preventDefault(); event.stopPropagation(); setExpanded(false); }
        }} />
      {parseCustom && <button className="token-add" type="button" disabled={disabled || !draft.trim() || parsed === null} aria-label={t("Add {field}", { field: label })} onClick={() => { commit(); input.current?.focus(); }}><Plus size={16} aria-hidden="true" /></button>}
      {overlayOptions && suggestionPanel}
    </div>
    <p className="token-hint" id={`${id}-hint`}>{hint ?? t("Search and choose. Remove a chip to undo.")}</p>
    {showError && <p className="token-error" id={`${id}-error`} role="alert">{invalidMessage ?? t("Choose a matching option before leaving this field.")}</p>}
    {invalidValues.length > 0 && <p className="token-error">{t("Some selections are unavailable in this scope. Remove them to change the filter.")}</p>}
    {!overlayOptions && suggestionPanel}
    {quickOptions && quickOptions.some((option) => !values.includes(option.value)) && <div className="token-quick" role="group" aria-label={t("Quick add {field}", { field: label })}>
      {quickOptions.filter((option) => !values.includes(option.value)).map((option) => <button className="chip" type="button" key={option.value} disabled={disabled} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(option)}><Plus size={12} aria-hidden="true" />{option.label}</button>)}
    </div>}
  </div>;
}
