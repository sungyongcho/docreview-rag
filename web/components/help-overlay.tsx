"use client";

import { ArrowLeft, ArrowRight, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { developmentHelpTopic, HELP_SCREEN_TITLES, type HelpScreen, type HelpTopic } from "@/lib/help-content";
import { HELP_GROUPS, getHelpPrimer } from "@/lib/help-primer";
import { helpEntriesForAccess, helpDestinationScreen, helpTopicScreen, searchHelp, type HelpSearchEntry } from "@/lib/help-search";
import { DevelopmentBadge } from "@/components/development-badge";
import type { Capabilities } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { documentationDocument } from "@/lib/documentation-registry.mjs";
import { sameRect, visibleRect, type TargetRect } from "@/lib/spotlight";
import "./help-overlay.css";

export interface HelpOverlayProps {
  screen: HelpScreen | null;
  open: boolean;
  /** Suspend keyboard ownership while another dialog is active. */
  keyboard?: boolean;
  onClose: () => void;
  location: string;
  onNavigateTopic?: (id: string) => void;
  capabilities?: Capabilities | null;
}

type HelpPage = { kind: "home" } | { kind: "topic"; topicId: string };
type HelpScope = "current" | "all";
interface HelpHomeState { query: string; scope: HelpScope; groupId: string; scroll: number; focus: string | null }
const NO_TOPICS: readonly HelpTopic[] = [];

/** Closed disclosures and retained workspaces cannot own visible callouts. */
function hiddenTarget(element: HTMLElement): boolean {
  if (element.closest("[hidden], [inert]")) return true;
  for (let details = element.parentElement?.closest("details") ?? null; details; details = details.parentElement?.closest("details") ?? null) {
    if (!details.open && !details.querySelector("summary")?.contains(element)) return true;
  }
  return false;
}

/** Reuse measured target state when only unrelated page content changed. */
function sameRects(left: Record<string, TargetRect>, right: Record<string, TargetRect>): boolean {
  const ids = Object.keys(left);
  return ids.length === Object.keys(right).length && ids.every((id) => id in right && sameRect(left[id], right[id]));
}

/** Consolidate identical explanations while favoring their visible control context. */
function uniqueTopics(entries: HelpSearchEntry[], current: HelpScreen | null, rects: Record<string, TargetRect>) {
  const unique = new Map<string, HelpSearchEntry>();
  const priority = (entry: HelpSearchEntry) => Number(entry.topic.id in rects) * 2 + Number(entry.screen === current);
  for (const entry of entries) {
    const key = JSON.stringify([entry.topic.title, entry.topic.body, entry.topic.tune]);
    const previous = unique.get(key);
    if (!previous || priority(entry) > priority(previous)) unique.set(key, entry);
  }
  return [...unique.values()];
}

/** Check actual modal ownership as some dialogs belong to retained child workspaces. */
function modalOwnsFocus() {
  return [...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')].some((dialog) => !dialog.closest("[hidden], [inert]"));
}

export function HelpOverlay({ screen, open, keyboard = true, onClose, location, onNavigateTopic, capabilities }: HelpOverlayProps) {
  const { t, locale } = useI18n();
  const allowed = useMemo(() => helpEntriesForAccess({ capabilities }), [capabilities]);
  const byId = useMemo(() => new Map(allowed.map((entry) => [entry.topic.id, entry.topic])), [allowed]);
  const topics = useMemo(() => screen ? allowed.filter((entry) => entry.screen === screen).map((entry) => entry.topic) : NO_TOPICS, [allowed, screen]);
  const [rects, setRects] = useState<Record<string, TargetRect>>({});
  const [page, setPage] = useState<HelpPage>({ kind: "home" });
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<HelpScope>("all");
  const [groupId, setGroupId] = useState<string>(HELP_GROUPS[0].id);
  const [homeOrigin, setHomeOrigin] = useState<HelpHomeState | null>(null);
  const panel = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const skipFocusReturn = useRef(false);
  const pendingView = useRef<{ scroll: number; focus: string | null } | null>(null);
  const entries = useMemo(() => scope === "all" ? allowed : allowed.filter((entry) => entry.screen === screen), [scope, screen, allowed]);
  const results = useMemo(() => uniqueTopics(searchHelp(query, locale, entries), screen, rects), [query, locale, entries, screen, rects]);
  const searching = page.kind !== "topic" && !!query.trim();
  const selected = page.kind === "topic" ? byId.get(page.topicId) : null;
  const activeId = selected?.id ?? null;
  const groups = HELP_GROUPS.map((item) => ({ ...item, clusters: item.clusters.filter((cluster) => cluster.topicIds.some((id) => byId.has(id))) })).filter((item) => item.clusters.length);
  const group = groups.find((item) => item.id === groupId) ?? groups[0];
  const clusterEntries = (ids: readonly string[]) => uniqueTopics(entries.filter((entry) => ids.includes(entry.topic.id)), screen, rects);
  const heading = selected ? t(selected.title) : t("Choose a topic");

  useLayoutEffect(() => {
    if (!open || !screen) { setRects({}); return; }
    const update = () => {
      const next: Record<string, TargetRect> = {};
      for (const topic of keyboard && !modalOwnsFocus() ? topics : NO_TOPICS) {
        const element = [...document.querySelectorAll<HTMLElement>(`[data-help="${topic.id}"]`)].find((candidate) => !hiddenTarget(candidate));
        if (!element) continue;
        const rect = visibleRect(element);
        if (rect) next[topic.id] = rect;
      }
      setRects((current) => sameRects(current, next) ? current : next);
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const observer = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    observer?.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
    return () => { window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); observer?.disconnect(); };
  }, [screen, open, location, topics, keyboard]);

  useEffect(() => {
    if (!open || !keyboard || modalOwnsFocus()) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    skipFocusReturn.current = false;
    panel.current?.focus({ preventScroll: true });
    return () => {
      if (skipFocusReturn.current) return;
      const previous = opener.current ?? document.querySelector<HTMLElement>(".help-toggle");
      if (previous?.isConnected && !previous.closest("[hidden], [inert]") && !modalOwnsFocus()) previous.focus({ preventScroll: true });
    };
  }, [open, keyboard]);

  useEffect(() => {
    if (!open || !keyboard) return;
    /** A conversation click dismisses help without stealing focus from the clicked control. */
    const outside = (event: PointerEvent) => {
      const target = event.target;
      if (modalOwnsFocus() || !(target instanceof Element) || !target.closest(".messages, .composer-wrap")) return;
      skipFocusReturn.current = true;
      onClose();
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, keyboard, onClose]);

  /** Save a single home origin; related topics replace the same detail view. */
  function navigate(next: HelpPage) {
    if (next.kind !== "topic" || (page.kind === "topic" && next.topicId === page.topicId)) return;
    if (!byId.has(next.topicId)) return;
    if (page.kind === "home") {
      const focused = document.activeElement instanceof HTMLElement ? document.activeElement.closest<HTMLElement>("[data-help-row]")?.dataset.helpRow ?? null : null;
      setHomeOrigin({ query, scope, groupId, scroll: content.current?.scrollTop ?? 0, focus: focused });
    }
    pendingView.current = { scroll: 0, focus: null };
    setPage(next);
  }

  function back() {
    if (page.kind !== "topic") return;
    pendingView.current = { scroll: homeOrigin?.scroll ?? 0, focus: homeOrigin?.focus ?? null };
    if (homeOrigin) { setQuery(homeOrigin.query); setScope(homeOrigin.scope); setGroupId(homeOrigin.groupId); }
    setPage({ kind: "home" });
    setHomeOrigin(null);
  }

  useEffect(() => {
    if (page.kind === "topic" && !byId.has(page.topicId)) back();
  }, [page, byId]);

  useLayoutEffect(() => {
    const pending = pendingView.current;
    if (!pending || !open) return;
    pendingView.current = null;
    const focused = pending.focus ? [...(panel.current?.querySelectorAll<HTMLElement>("[data-help-row]") ?? [])].find((row) => row.dataset.helpRow === pending.focus) : null;
    if (keyboard && !modalOwnsFocus()) (focused ?? title.current)?.focus({ preventScroll: true });
    if (content.current) content.current.scrollTop = pending.scroll;
  }, [page, query, scope, groupId, homeOrigin, open, keyboard]);

  useEffect(() => {
    if (!open || !keyboard) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || modalOwnsFocus()) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('input, textarea, select, [contenteditable="true"], [role="dialog"]')) return;
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (!panel.current?.contains(target)) return;
      if (event.key === "ArrowLeft" && page.kind === "topic") { event.preventDefault(); back(); return; }
      const rows = [...panel.current.querySelectorAll<HTMLButtonElement>("button[data-help-row]")];
      const current = rows.findIndex((row) => row === document.activeElement);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!rows.length) return;
        event.preventDefault();
        const index = current < 0 ? event.key === "ArrowDown" ? 0 : rows.length - 1 : Math.max(0, Math.min(rows.length - 1, current + (event.key === "ArrowDown" ? 1 : -1)));
        rows[index].focus(); rows[index].scrollIntoView?.({ block: "nearest" });
      } else if ((event.key === "ArrowRight" || event.key === "Enter") && current >= 0) { event.preventDefault(); rows[current].click(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, keyboard, onClose, homeOrigin, page, query, scope]);

  /** Leaving Help is explicit; selecting a topic never runs or changes the explained control. */
  function goToTopic(id: string) {
    if (!byId.has(id)) return;
    const target = [...document.querySelectorAll<HTMLElement>(`[data-help="${id}"]`)].find((element) => !element.closest("[hidden], [inert]"));
    if (target) {
      for (let disclosure = target.closest("details"); disclosure; disclosure = disclosure.parentElement?.closest("details") ?? null) disclosure.open = true;
      const focus = target.matches("button, input, select, textarea, a, summary") ? target : target.querySelector<HTMLElement>("button, input, select, textarea, a, summary") ?? target;
      if (!focus.matches("button, input, select, textarea, a, summary, [tabindex]")) focus.tabIndex = -1;
      opener.current = focus;
      target.scrollIntoView?.({ block: "center", inline: "nearest" });
      onClose(); focus.focus({ preventScroll: true });
    } else if (onNavigateTopic) {
      skipFocusReturn.current = true;
      onNavigateTopic(id); onClose();
    }
  }

  function topicRow(topic: HelpTopic, key = topic.id, origin?: HelpScreen) {
    const primer = getHelpPrimer(topic);
    return <button className="help-topic-row" type="button" data-help-row={key} data-help-item={topic.id} key={key} aria-label={t(topic.title)} onClick={() => navigate({ kind: "topic", topicId: topic.id })}>
      <span><strong>{t(topic.title)}{developmentHelpTopic(topic) && <DevelopmentBadge locale={locale} compact />}</strong><span className="help-row-summary">{origin && origin !== screen ? `${t(HELP_SCREEN_TITLES[origin])} · ` : ""}{t(primer.summary)}</span></span><ChevronRight size={20} aria-hidden="true" />
    </button>;
  }

  if (!open) return null;
  const primer = selected ? getHelpPrimer(selected) : null;
  const guide = primer?.documentId ? documentationDocument(primer.documentId, locale) : null;
  const destination = selected ? helpDestinationScreen(selected.id) ?? helpTopicScreen(selected.id) : null;
  const targetExists = selected ? [...document.querySelectorAll<HTMLElement>(`[data-help="${selected.id}"]`)].some((element) => !element.closest("[hidden], [inert]")) : false;
  const highlight = activeId ? rects[activeId] : null;

  return <>
    {selected && highlight && <div className="help-target-highlight" data-help-highlight={selected.id} aria-hidden="true" style={{ left: highlight.left, top: highlight.top, width: highlight.width, height: highlight.height, pointerEvents: "none" }}><span className="help-target-label" data-below={highlight.top < 28} style={{ maxWidth: Math.max(0, Math.min(220, window.innerWidth - highlight.left - 8)) }}>{t(selected.title)}</span></div>}
    <aside className="help-panel help-browser" role="complementary" aria-label={t("Help")} tabIndex={-1} ref={panel}>
      <header className="help-browser-header"><div className="help-browser-toolbar"><div>
        {page.kind === "topic" && <button className="help-back-button" type="button" aria-label={t("Back in help")} onClick={back}><ArrowLeft size={18} aria-hidden="true" />{t("Back")}</button>}
      </div><button className="help-close-button" type="button" aria-label={t("Close help")} onClick={onClose}><X size={21} /></button></div>
        <p className="help-context">{selected && destination ? t(HELP_SCREEN_TITLES[destination]) : t("Help")}</p>
        <h2 tabIndex={-1} ref={title}>{heading}</h2>
        {page.kind !== "topic" && <div className="help-browser-search-tools"><label className="help-browser-search"><Search size={19} aria-hidden="true" /><input aria-label={t("Search help")} placeholder={t("Search topics or keywords")} value={query} onChange={(event) => { setQuery(event.target.value); if (content.current) content.current.scrollTop = 0; }} />{query && <button type="button" aria-label={t("Clear help search")} onClick={() => setQuery("")}><X size={17} /></button>}</label>
          <div className="help-scope" role="group" aria-label={t("Help section")}>{(["current", "all"] as const).map((value) => <button type="button" key={value} aria-pressed={scope === value} onClick={() => { setScope(value); if (content.current) content.current.scrollTop = 0; }}>{t(value === "current" ? "Current screen" : "All sections")}</button>)}</div>
          <div className="help-task-filters" role="group" aria-label={t("Browse help")}>{groups.map((item) => <button type="button" key={item.id} aria-pressed={group?.id === item.id} onClick={() => { setGroupId(item.id); setQuery(""); if (content.current) content.current.scrollTop = 0; }}>{t(item.clusters.length === 1 ? item.clusters[0].title : item.title)}</button>)}</div>
        </div>}
      </header>
      <div className="help-browser-content" ref={content}>
        {searching ? <section className="help-topic-list" aria-label={t("Search results")}><p className="help-result-count" role="status">{t("{count} matching help topics", { count: results.length })}</p>{results.map(({ topic, screen: origin }) => topicRow(topic, topic.id, origin))}{!results.length && <div className="help-browser-empty"><h3>{t("No matching help topics.")}</h3><p>{t("Try a shorter keyword or browse all sections.")}</p><button type="button" className="button" onClick={() => { setQuery(""); setScope("all"); setPage({ kind: "home" }); }}>{t("Browse all topics")}</button></div>}</section>
        : selected && primer ? <article className="help-topic-detail" data-help-item={selected.id}>{developmentHelpTopic(selected) && <DevelopmentBadge locale={locale} />}<p className="help-topic-lead">{t(primer.summary)}</p>
          {primer.steps.length > 0 && <section className="help-steps"><h3>{t("What to do")}</h3><ol>{primer.steps.slice(0, 3).map((step, index) => <li key={index}><span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><p>{t(step)}</p></li>)}</ol></section>}
          {(targetExists || onNavigateTopic) && <button className="help-go-button" type="button" onClick={() => goToTopic(selected.id)}>{targetExists ? t("Go to this control") : t("Go to {screen}", { screen: destination ? t(HELP_SCREEN_TITLES[destination]) : t("This screen") })}<ArrowRight size={19} aria-hidden="true" /></button>}
          {!targetExists && <p className="help-context-note">{t("Not on this screen right now")}</p>}
          {guide && <a className="help-guide-link" href={guide.href} target="_blank" rel="noreferrer noopener">{t("Read the full guide")}<ArrowRight size={16} aria-hidden="true" /></a>}
          <details className="help-reference"><summary>{t("Reference")}</summary>{selected.body.map((paragraph, index) => <p key={index}>{t(paragraph)}</p>)}{selected.tune && <p><strong>{t("How to tune")}</strong> {t(selected.tune)}</p>}</details>
          {selected.seeAlso?.some((id) => byId.has(id)) && <section className="help-related"><h3>{t("Related topics")}</h3>{selected.seeAlso.map((id) => { const topic = byId.get(id); return topic ? topicRow(topic, `related:${id}`) : null; })}</section>}
        </article>
        : <>
          <section className="help-home-recommended" aria-label={t("Recommended")}><h3>{t("Recommended")}</h3><p>{t("Help for controls visible on your current screen.")}</p><div className="help-topic-list">{topics.filter((topic) => topic.id in rects).slice(0, 4).map((topic) => topicRow(topic, `recommended:${topic.id}`))}</div>{!Object.keys(rects).length && <p className="help-context-note">{t(screen ? "Open a workspace to see relevant help here." : "No help topics for this screen yet.")}</p>}</section>
          {group && <section className="help-home-topics" aria-label={t(group.clusters.length === 1 ? group.clusters[0].title : group.title)}><p className="help-list-lead">{group.clusters.map((cluster) => t(cluster.title)).join(" · ")}</p>{group.clusters.map((cluster) => {
            const listed = clusterEntries(cluster.topicIds);
            return listed.length > 0 ? <section className="help-inline-cluster" key={cluster.id} aria-label={t(cluster.title)}><h3>{t(cluster.title)}</h3><div className="help-topic-list">{listed.map(({ topic }) => topicRow(topic))}</div></section> : null;
          })}{!group.clusters.some((cluster) => clusterEntries(cluster.topicIds).length) && <p className="help-context-note">{t("No topics in this section for the current screen.")}</p>}</section>}
        </>}

      </div>
    </aside>
  </>;
}
