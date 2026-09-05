"use client";

import { browserStorage } from "@/lib/production-preview";

import { useEffect, useId, useRef, useState, type CSSProperties } from "react";

const MIN_LIST_WIDTH = 320;
const MAX_LIST_WIDTH = 600;
const MIN_DETAIL_WIDTH = 560;
const DIVIDER_WIDTH = 18;

export type MasterDetailResize = {
  value: number;
  min: number;
  max: number;
  onChange: (width: number) => void;
  onCommit: (width: number) => void;
  onReset: () => void;
};

/** Measure the actual workspace so a sidebar never forces a cramped split view. */
export function useMasterDetail({ storageKey, defaultListWidth = 360 }: { storageKey?: string; defaultListWidth?: number } = {}) {
  const workspaceRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const listPanelId = useId();
  const scrollPosition = useRef(0);
  const [workspaceWidth, setWorkspaceWidth] = useState(1100);
  const [preferredWidth, setPreferredWidth] = useState<number | null>(null);
  const [narrow, setNarrow] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const max = Math.max(MIN_LIST_WIDTH, Math.min(MAX_LIST_WIDTH, Math.floor(workspaceWidth - MIN_DETAIL_WIDTH - DIVIDER_WIDTH)));
  const value = Math.max(MIN_LIST_WIDTH, Math.min(max, preferredWidth ?? defaultListWidth));

  useEffect(() => {
    setPreferredWidth(null);
    if (!storageKey) return;
    try {
      const saved = browserStorage().getItem(storageKey);
      const width = saved === null ? NaN : Number(saved);
      if (Number.isFinite(width) && width > 0) setPreferredWidth(Math.max(MIN_LIST_WIDTH, Math.min(MAX_LIST_WIDTH, width)));
    } catch (error) {
      // Optional layout preferences must not disable the workspace when storage is blocked.
      if (!(error instanceof DOMException)) throw error;
    }
  }, [storageKey]);

  useEffect(() => {
    const element = workspaceRef.current;
    if (!element) return;
    let visible = element.getBoundingClientRect().width > 0;
    const measure = (width: number) => {
      if (width > 0) {
        setWorkspaceWidth(width);
        setNarrow(width < 1100);
        if (!visible && listRef.current) listRef.current.scrollTop = scrollPosition.current;
      }
      visible = width > 0;
    };
    measure(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => measure(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const rememberScroll = () => {
      if (list.getClientRects().length > 0) scrollPosition.current = list.scrollTop;
    };
    list.addEventListener("scroll", rememberScroll, { passive: true });
    return () => list.removeEventListener("scroll", rememberScroll);
  }, []);

  useEffect(() => {
    if ((!narrow || !detailOpen) && listRef.current) listRef.current.scrollTop = scrollPosition.current;
  }, [narrow, detailOpen]);

  function openDetail() {
    scrollPosition.current = listRef.current?.scrollTop ?? 0;
    setDetailOpen(true);
  }

  /** Persist only completed gestures; live pointer moves remain in memory. */
  function commitWidth(width: number) {
    const bounded = Math.max(MIN_LIST_WIDTH, Math.min(max, Math.round(width)));
    setPreferredWidth(bounded);
    if (!storageKey) return;
    try { browserStorage().setItem(storageKey, String(bounded)); }
    catch (error) {
      if (!(error instanceof DOMException)) throw error;
    }
  }

  /** Reset only this workspace's panel preference. */
  function resetWidth() {
    setPreferredWidth(null);
    if (!storageKey) return;
    try { browserStorage().removeItem(storageKey); }
    catch (error) {
      if (!(error instanceof DOMException)) throw error;
    }
  }

  return {
    workspaceRef, listRef, listPanelId, narrow, detailOpen, openDetail,
    closeDetail: () => setDetailOpen(false),
    splitStyle: { "--master-list-width": `${value}px` } as CSSProperties,
    resize: { value, min: MIN_LIST_WIDTH, max, onChange: setPreferredWidth, onCommit: commitWidth, onReset: resetWidth } satisfies MasterDetailResize,
  };
}
