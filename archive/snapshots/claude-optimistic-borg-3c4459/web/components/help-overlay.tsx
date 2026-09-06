"use client";

import { X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { findHelpTopic, HELP_SCREEN_TITLES, HELP_TOPICS, type HelpScreen, type HelpTopic } from "@/lib/help-content";
import { sameRect, visibleRect, type TargetRect } from "@/lib/spotlight";

export interface HelpOverlayProps {
  screen: HelpScreen | null;
  open: boolean;
  /** False while a modal owns the screen, so Escape and the panel do not steal it. */
  keyboard?: boolean;
  onClose: () => void;
  /** The shell's committed workspace and tab; a change re-measures every topic once the shell has navigated. */
  location: string;
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

export function HelpOverlay({ screen, open, keyboard = true, onClose, location }: HelpOverlayProps) {
  const topics = screen ? HELP_TOPICS[screen] : NO_TOPICS;
  const [rects, setRects] = useState<Record<string, TargetRect>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
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

  const activate = useCallback((id: string) => {
    select(id);
    const item = items.current.get(id);
    if (!item) return;
    item.open = true;
    if (typeof item.scrollIntoView === "function") item.scrollIntoView({ block: "nearest" });
  }, [select]);

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
              aria-label={`Help ${index + 1}: ${topic.title}`}
              onClick={() => activate(topic.id)}
            >
              <span className="help-arrow" aria-hidden="true" />
              {index + 1}
            </button>
          );
        })}
      </div>
      <aside className="help-panel" role="complementary" aria-label="Help" tabIndex={-1} ref={panel}>
        <header className="help-panel-head">
          <div>
            <p className="eyebrow">Help</p>
            <h2>{screen ? HELP_SCREEN_TITLES[screen] : "This screen"}</h2>
          </div>
          <button className="icon-button" type="button" aria-label="Close help" onClick={onClose}><X size={17} /></button>
        </header>
        {screen === null && <p className="help-empty">No help topics for this screen yet.</p>}
        {topics.map((topic, index) => {
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
              <summary onClick={() => select(topic.id)}>{index + 1}. {topic.title}</summary>
              {!present && <p className="help-absent">Not on this screen right now</p>}
              {topic.body.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              {topic.tune && <p className="help-tune"><strong>How to tune</strong> {topic.tune}</p>}
              {topic.seeAlso && topic.seeAlso.length > 0 && (
                <p className="help-see-also">
                  <span>See also</span>
                  {topic.seeAlso.map((refId) => <SeeAlsoLink key={refId} id={refId} local={topics.some((item) => item.id === refId)} onActivate={activate} />)}
                </p>
              )}
            </details>
          );
        })}
      </aside>
    </>
  );
}

function SeeAlsoLink({ id, local, onActivate }: { id: string; local: boolean; onActivate: (id: string) => void }) {
  const topic = findHelpTopic(id);
  const label = topic?.title ?? id;
  if (!local) return <span className="help-ref" title={id}>{label}</span>;
  return <button type="button" className="inline-link help-ref" onClick={() => onActivate(id)}>{label}</button>;
}
