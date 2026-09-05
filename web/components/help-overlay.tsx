"use client";
import { useI18n } from "@/lib/i18n";


import { ArrowRight, Search, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { findHelpTopic, HELP_SCREEN_TITLES, HELP_TOPICS, type HelpScreen, type HelpTopic } from "@/lib/help-content";
import { sameRect, visibleRect, type TargetRect } from "@/lib/spotlight";
import { HELP_ENTRIES, helpDestinationScreen, helpTopicScreen, searchHelp } from "@/lib/help-search";

export interface HelpOverlayProps {
  screen: HelpScreen | null;
  open: boolean;
  /** False while a modal owns the screen, so Escape and the panel do not steal it. */
  keyboard?: boolean;
  onClose: () => void;
  /** The shell's committed workspace and tab; a change re-measures every topic once the shell has navigated. */
  location: string;
  onNavigateTopic?: (id: string) => void;
}

const NO_TOPICS: readonly HelpTopic[] = [];

/** An element inside a closed disclosure exists in the DOM but has no box to point at; the summary and the disclosure itself stay visible. */
function hiddenInDetails(element: HTMLElement): boolean {
  if (element.matches("summary, summary *")) return false;
  for (let details = element.parentElement?.closest("details") ?? null; details; details = details.parentElement?.closest("details") ?? null) {
    if (!details.open) return true;
  }
  return false;
}

function sameRects(left: Record<string, TargetRect>, right: Record<string, TargetRect>): boolean {
  const ids = Object.keys(left);
  if (ids.length !== Object.keys(right).length) return false;
  return ids.every((id) => id in right && sameRect(left[id], right[id]));
}

export function HelpOverlay({ screen, open, keyboard = true, onClose, location, onNavigateTopic }: HelpOverlayProps) {
  const { t, locale } = useI18n();
  const topics = screen ? HELP_TOPICS[screen] : NO_TOPICS;
  const [rects, setRects] = useState<Record<string, TargetRect>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [section, setSection] = useState<"current" | "all" | HelpScreen>("current");
  const listed = useMemo(() => {
    const entries = query.trim() || section === "all" ? HELP_ENTRIES : HELP_ENTRIES.filter((entry) => entry.screen === (section === "current" ? screen : section));
    return searchHelp(query, locale, entries);
  }, [query, section, screen, locale]);
  const items = useRef(new Map<string, HTMLDetailsElement>());
  const panel = useRef<HTMLElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    setActiveId(null);
  }, [screen]);

  useLayoutEffect(() => {
    if (!open || !screen) {
      setRects({});
      return;
    }
    const update = () => {
      const next: Record<string, TargetRect> = {};
      for (const topic of topics) {
        const element = document.querySelector<HTMLElement>(`[data-help="${topic.id}"]`);
        if (!element || hiddenInDetails(element)) continue;
        // A target scrolled out of its own pane gets no marker; a clamped one would point at unrelated UI.
        const rect = visibleRect(element);
        if (rect) next[topic.id] = rect;
      }
      setRects((current) => (sameRects(current, next) ? current : next));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    // Content arriving around a target (job progress, preview results, an opened disclosure) moves or reveals it.
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    observer?.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      observer?.disconnect();
    };
  }, [screen, open, location, topics]);

  useEffect(() => {
    if (!open || !keyboard) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof Element && event.target.closest('[role="dialog"][aria-modal="true"]')) return;
      if (event.key === "Escape" && !event.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, keyboard, onClose]);

  // C7: the panel is the last thing in the DOM, so opening moves focus there and closing gives it back.
  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.current?.focus({ preventScroll: true });
    return () => {
      const previous = opener.current ?? document.querySelector<HTMLElement>(".help-toggle");
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open]);

  /** Selecting a topic brings its control back into view, which is the only way to reach one scrolled away. */
  const select = useCallback((id: string) => {
    setActiveId(id);
    const target = document.querySelector<HTMLElement>(`[data-help="${id}"]`);
    if (target && typeof target.scrollIntoView === "function") target.scrollIntoView({ block: "center", inline: "nearest" });
  }, []);

  function goToTopic(id: string) {
    const target = document.querySelector<HTMLElement>(`[data-help="${id}"]`);
    if (target && !target.closest("[hidden]")) {
      for (let disclosure = target.closest("details"); disclosure; disclosure = disclosure.parentElement?.closest("details") ?? null) disclosure.open = true;
      target.scrollIntoView?.({ block: "center", inline: "nearest" });
      setActiveId(id);
      if (target.matches("button, input, select, textarea, a, summary")) target.focus({ preventScroll: true });
    } else onNavigateTopic?.(id);
  }

  const activate = useCallback((id: string) => {
    select(id);
    const item = items.current.get(id);
    if (!item) return;
    item.open = true;
    if (typeof item.scrollIntoView === "function") item.scrollIntoView({ block: "nearest" });
  }, [select]);

  useEffect(() => {
    if (activeId) {
      const item = items.current.get(activeId);
      if (item) item.open = true;
    }
  }, [activeId, listed]);

  if (!open) return null;

  return (
    <>
      <div className="help-layer" role="presentation">
        {topics.map((topic, index) => {
          const rect = rects[topic.id];
          if (!rect) return null;
          return (
            <button
              key={topic.id}
              type="button"
              className={`help-marker${activeId === topic.id ? " active" : ""}`}
              style={{ left: rect.right, top: rect.top }}
              aria-label={t("Help {p0}: {p1}", { p0: index + 1, p1: t(topic.title) })}
              onClick={() => activate(topic.id)}
            >
              <span className="help-arrow" aria-hidden="true" />
              {index + 1}
            </button>
          );
        })}
      </div>
      <aside className="help-panel" role="complementary" aria-label={t("Help")} tabIndex={-1} ref={panel}>
        <header className="help-panel-head">
          <div>
            <p className="eyebrow">{t("Help")}</p>
            <h2>{screen ? t(HELP_SCREEN_TITLES[screen]) : t("This screen")}</h2>
          </div>
          <button className="icon-button" type="button" aria-label={t("Close help")} onClick={onClose}><X size={17} /></button>
        </header>
        <div className="help-search-tools">
          <label className="help-search"><Search size={16} aria-hidden="true" /><input aria-label={t("Search all help")} placeholder={t("Search topics or keywords")} value={query} onChange={(event) => setQuery(event.target.value)} />{query && <button type="button" className="icon-button" aria-label={t("Clear help search")} onClick={() => setQuery("")}><X size={14} /></button>}</label>
          <select aria-label={t("Help section")} value={section} onChange={(event) => { setSection(event.target.value as typeof section); setQuery(""); }}><option value="current">{t("Current screen")}</option><option value="all">{t("All sections")}</option>{Object.entries(HELP_SCREEN_TITLES).map(([id, title]) => <option key={id} value={id}>{t(title)}</option>)}</select>
        </div>
        {!query.trim() && <section className="help-recommended" aria-label={t("Recommended")}><h3>{t("Recommended")}</h3><p>{t("Help for controls visible on your current screen.")}</p><div>{topics.filter((topic) => topic.id in rects).slice(0, 6).map((topic) => <button type="button" key={topic.id} onClick={() => { setSection("current"); activate(topic.id); }}>{t(topic.title)}<ArrowRight size={13} /></button>)}</div>{!Object.keys(rects).length && <p>{t("Open a workspace to see relevant help here.")}</p>}</section>}
        {query.trim() && <p className="helper" role="status">{t("{count} matching help topics", { count: listed.length })}</p>}
        {screen === null && <p className="help-empty">{t("No help topics for this screen yet.")}</p>}
        {listed.map(({ topic, index, screen: topicScreen }) => {
          const present = topic.id in rects;
          return (
            <details
              key={topic.id}
              className={`help-item${activeId === topic.id ? " active" : ""}${present ? "" : " absent"}`}
              data-help-item={topic.id}
              ref={(node) => {
                if (node) items.current.set(topic.id, node);
                else items.current.delete(topic.id);
              }}
            >
              <summary onClick={() => select(topic.id)}>{index + 1}. {t(topic.title)}</summary>
              {topicScreen !== screen && <p className="help-topic-section">{t(HELP_SCREEN_TITLES[topicScreen])}</p>}
              {!present && <div className="help-jump"><p className="help-absent">{t("Not on this screen right now")}</p>{onNavigateTopic && <button type="button" className="button ghost" onClick={() => goToTopic(topic.id)}>{t("Go to {screen}", { screen: t(HELP_SCREEN_TITLES[helpDestinationScreen(topic.id) ?? topicScreen]) })}<ArrowRight size={14} /></button>}</div>}
              {topic.body.map((paragraph) => <p key={t(paragraph)}>{t(paragraph)}</p>)}
              {topic.tune && <p className="help-tune"><strong>{t("How to tune")}</strong> {t(topic.tune)}</p>}
              {topic.seeAlso && topic.seeAlso.length > 0 && (
                <p className="help-see-also">
                  <span>{t("See also")}</span>
                  {topic.seeAlso.map((refId) => <SeeAlsoLink key={refId} id={refId} local={topics.some((item) => item.id === refId)} onActivate={activate} onNavigate={onNavigateTopic ? goToTopic : undefined} />)}
                </p>
              )}
            </details>
          );
        })}
      </aside>
    </>
  );
}

function SeeAlsoLink({ id, local, onActivate, onNavigate }: { id: string; local: boolean; onActivate: (id: string) => void; onNavigate?: (id: string) => void }) {
  const { t, locale } = useI18n();
  const topic = findHelpTopic(id);
  const label = topic?.title ?? id;
  if (!local) return onNavigate && helpTopicScreen(id) ? <button className="inline-link help-ref" type="button" onClick={() => onNavigate(id)}>{t(label)} ↗</button> : <span className="help-ref" title={id}>{t(label)}</span>;
  return <button type="button" className="inline-link help-ref" onClick={() => onActivate(id)}>{t(label)}</button>;
}
