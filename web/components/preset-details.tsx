"use client";
import { useId, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

/** Use the entire row as an explicit keyboard-operable disclosure, independent of neighboring rows. */
export function PresetDetails({ label, summary, source, selected = false, children }: { label: string; summary?: string; source?: string; selected?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <section className={`preset-list-entry${selected ? " selected" : ""}`} aria-label={label}>
    <button type="button" className="preset-list-row" aria-label={label} aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}><span className="preset-row-content"><strong>{label}</strong>{summary && <small>{summary}</small>}</span>{source && <span className="mode-badge">{source}</span>}{open ? <ChevronDown size={17} aria-hidden="true" /> : <ChevronRight size={17} aria-hidden="true" />}</button>
    <div id={id} className="preset-list-details" hidden={!open}>{children}</div>
  </section>;
}
