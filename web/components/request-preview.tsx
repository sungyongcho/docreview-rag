"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import "./review-controls.css";
import { useI18n } from "@/lib/i18n";
import { DEFAULT_SESSION_PROFILE, resolvedRetrievalProfile, type ReviewSessionProfile, type RetrievalPreset } from "@/lib/types";

const PRESETS: Array<[RetrievalPreset, string]> = [["balanced", "Balanced"], ["korean", "Korean"], ["accuracy", "Accuracy"], ["custom", "Custom"]];

/** Compare effective values, so preset descriptions cannot drift from request settings. */
export function presetChanges(profile: ReviewSessionProfile, preset: RetrievalPreset) {
  const baseline = resolvedRetrievalProfile(DEFAULT_SESSION_PROFILE);
  const effective = resolvedRetrievalProfile({ ...profile, retrieval_preset: preset });
  return Object.entries(effective).filter(([key, value]) => value !== baseline[key as keyof typeof baseline]);
}

/** One description shared by the visible control and the full comparison. */
export function presetDescription(profile: ReviewSessionProfile, preset: RetrievalPreset) {
  const effective = resolvedRetrievalProfile({ ...profile, retrieval_preset: preset });
  const changes = presetChanges(profile, preset);
  return {
    purpose: preset === "custom" ? "Uses your explicit retrieval settings." : preset === "accuracy" ? "Ranks a wider candidate pool by relevance." : preset === "korean" ? "Retrieves Korean evidence with language-aware routing." : "Uses the default retrieval balance.",
    settings: changes.length ? changes.map(([key, value]) => `${key}: ${String(value)}`).join(" · ") : `strategy: ${effective.strategy} · k: ${effective.k} · candidate_k: ${effective.candidate_k}`,
  };
}

export function RequestPreview({ profile, query }: { profile: ReviewSessionProfile; query: string }) {
  const { t } = useI18n();
  const effective = resolvedRetrievalProfile(profile);
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const panelId = useId();
  useEffect(() => {
    if (!open || !panel.current) return;
    const overlay = panel.current.parentElement;
    const background = Array.from(document.body.children).filter((child) => child !== overlay);
    const inertBefore = background.map((child) => child.hasAttribute("inert"));
    background.forEach((child) => child.setAttribute("inert", ""));
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const focusables = () => Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex="0"]') ?? []).filter((element) => {
      if (element.hidden) return false;
      const collapsed = element.closest("details:not([open])");
      return !collapsed || element === collapsed.querySelector("summary");
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
      if (event.key !== "Tab") return;
      const items = focusables();
      const first = items[0];
      const last = items.at(-1);
      if (event.shiftKey && (document.activeElement === first || !panel.current?.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !panel.current?.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    };
    const keepFocus = (event: FocusEvent) => { if (!panel.current?.contains(event.target as Node)) closeButton.current?.focus(); };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", keepFocus);
      background.forEach((child, index) => { if (!inertBefore[index]) child.removeAttribute("inert"); });
      document.body.style.overflow = previousOverflow;
      trigger.current?.focus();
    };
  }, [open]);
  const filters = { corpus_scope: profile.corpus_scope, issuers: profile.issuers, fiscal_years: profile.fiscal_years, forms: profile.forms, sections: profile.sections, languages: profile.languages, snapshot_id: profile.snapshot_id };
  return <>
    <button ref={trigger} className="chip request-inspector-trigger" type="button" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={() => setOpen(true)}>{t("Settings details / request preview")}</button>
    {open && createPortal(<div className="request-inspector-overlay" onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <div ref={panel} id={panelId} className="request-inspector-panel" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <header className="request-inspector-header"><h2 id={titleId}>{t("Settings details / request preview")}</h2><button ref={closeButton} type="button" className="button ghost" aria-label={t("Close request preview")} onClick={() => setOpen(false)}><X size={20} /></button></header>
    <div className="request-inspector-body">
      <h3>{t("Retrieval presets")}</h3>
      <div className="preset-comparison">{PRESETS.map(([id, label]) => {
        const description = presetDescription(profile, id);
        return <section key={id} aria-label={t(label)} className={profile.retrieval_preset === id ? "selected" : ""}>
          <strong>{t(label)}</strong>
          <p>{t(description.purpose)}</p>
          <code>{description.settings}</code>
        </section>;
      })}</div>
      <dl className="request-facts">
        <div><dt>{t("Retrieval")}</dt><dd>{effective.strategy} · k {effective.k} · {t("Candidates")} {effective.candidate_k}</dd></div>
        <div><dt>{t("Reranker")}</dt><dd>{effective.reranker ?? t("None")}</dd></div>
        <div><dt>{t("Language routing")}</dt><dd>{t(effective.route_by_language ? "Enabled" : "Disabled")}</dd></div>
        <div><dt>{t("Answer engine")}</dt><dd>{profile.engine}{profile.engine === "local" && profile.local_model ? ` · ${profile.local_model}` : ""}</dd></div>
      </dl>
      <details><summary>{t("Filters")}</summary><pre>{JSON.stringify(filters, null, 2)}</pre></details>
      <details><summary>{t("Prompt composition")}</summary><p className="helper">{t("Server policy + conversation history + question + retrieved evidence. The evidence is selected after execution begins.")}</p><pre>{JSON.stringify({ question: query, prompt_policy: profile.prompt_policy }, null, 2)}</pre></details>
      <details><summary>{t("Request payload")}</summary><pre>{JSON.stringify({ query, session_profile: profile }, null, 2)}</pre></details>
      <p className="helper">{t("Preview of this next request. Server-applied settings appear with the completed result.")}</p>
    </div>
    </div></div>, document.body)}
  </>;
}
