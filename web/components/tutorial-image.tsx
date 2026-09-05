"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, Maximize, Minus, Plus, X } from "lucide-react";
import type { TutorialImageSource } from "@/lib/tutorial-markdown.mjs";
import "./tutorial-image.css";

/** Show the original screenshot with portfolio-style wheel zoom and its authored caption. */
export function TutorialImage({ src, alt, title, caption, locale }: TutorialImageSource) {
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [naturalWidth, setNaturalWidth] = useState(0);
  const [availableWidth, setAvailableWidth] = useState(0);
  const zoomValue = useRef(1);
  const trigger = useRef<HTMLAnchorElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const picture = useRef<HTMLImageElement>(null);
  const anchor = useRef<{ x: number; y: number; horizontal: number; vertical: number } | null>(null);
  const captionId = useId();
  const labels = locale === "ko"
    ? { expand: "이미지 크게 보기", viewer: "이미지 보기", close: "이미지 닫기", original: "원본 열기", increase: "이미지 확대", decrease: "이미지 축소", fit: "너비에 맞추기", area: "스크롤할 수 있는 이미지", hint: "이미지 위에서 휠로 확대·축소하고, 스크롤 막대로 이동하세요." }
    : { expand: "Expand image", viewer: "Image viewer", close: "Close image", original: "Open original", increase: "Zoom in", decrease: "Zoom out", fit: "Fit width", area: "Scrollable image", hint: "Scroll over the image to zoom; use the scrollbars to move through it." };

  function changeZoom(next: number, point?: { x: number; y: number }) {
    const value = Math.min(4, Math.max(1, next));
    if (value === zoomValue.current) return;
    const rect = picture.current?.getBoundingClientRect();
    anchor.current = rect && point && rect.width && rect.height
      ? { ...point, horizontal: (point.x - rect.left) / rect.width, vertical: (point.y - rect.top) / rect.height }
      : null;
    zoomValue.current = value;
    setZoom(value);
  }

  function expand() {
    zoomValue.current = 1;
    setZoom(1);
    anchor.current = null;
    setOpen(true);
  }

  useEffect(() => { setOpen(false); setNaturalWidth(0); }, [src]);

  useLayoutEffect(() => {
    if (!open || !stage.current) return;
    const point = anchor.current;
    const rect = picture.current?.getBoundingClientRect();
    if (point && rect) {
      stage.current.scrollLeft += rect.left + point.horizontal * rect.width - point.x;
      stage.current.scrollTop += rect.top + point.vertical * rect.height - point.y;
    } else if (zoom === 1) {
      stage.current.scrollLeft = 0;
      stage.current.scrollTop = 0;
    }
    anchor.current = null;
  }, [open, zoom, availableWidth, naturalWidth]);

  useEffect(() => {
    if (!open || !dialog.current || !stage.current || !picture.current) return;
    const overlay = dialog.current.parentElement;
    const background = [...document.body.children].filter((child) => child !== overlay);
    const previousInert = background.map((child) => child.hasAttribute("inert"));
    const previousOverflow = document.body.style.overflow;
    background.forEach((child) => child.setAttribute("inert", ""));
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const scrollArea = stage.current;
    const image = picture.current;
    function measure() { setAvailableWidth(scrollArea.clientWidth); }
    function wheel(event: WheelEvent) {
      if (window.matchMedia && !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
      event.preventDefault();
      changeZoom(zoomValue.current * Math.exp(-event.deltaY * 0.002), { x: event.clientX, y: event.clientY });
    }
    function controls() {
      return [...(dialog.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex="0"]') ?? [])];
    }
    function key(event: KeyboardEvent) {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); return; }
      if (event.key !== "Tab") return;
      const elements = controls();
      const first = elements[0];
      const last = elements.at(-1);
      const outside = !dialog.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || outside)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || outside)) { event.preventDefault(); first?.focus(); }
    }
    function containFocus(event: FocusEvent) {
      if (!dialog.current?.contains(event.target as Node)) closeButton.current?.focus();
    }
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(scrollArea);
    window.addEventListener("resize", measure);
    image.addEventListener("wheel", wheel, { passive: false });
    document.addEventListener("keydown", key);
    document.addEventListener("focusin", containFocus);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      image.removeEventListener("wheel", wheel);
      document.removeEventListener("keydown", key);
      document.removeEventListener("focusin", containFocus);
      background.forEach((child, index) => { if (!previousInert[index]) child.removeAttribute("inert"); });
      document.body.style.overflow = previousOverflow;
      if (trigger.current?.isConnected && !trigger.current.closest("[hidden], [inert]")) trigger.current.focus({ preventScroll: true });
    };
  }, [open]);

  const fittedWidth = naturalWidth && availableWidth ? Math.min(naturalWidth, availableWidth) : availableWidth;
  const width = fittedWidth ? fittedWidth * zoom : undefined;
  return <>
    <a ref={trigger} className="tutorial-image-trigger" href={src} target="_blank" rel="noopener noreferrer" aria-label={`${alt} · ${labels.expand}`} aria-haspopup="dialog" aria-expanded={open}
      onClick={(event) => { if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); expand(); }}
      onKeyDown={(event) => { if (event.key === " ") { event.preventDefault(); expand(); } }}>
      <img src={src} alt={alt} title={title} loading="lazy" />
    </a>
    {open && createPortal(<div className="tutorial-image-overlay" onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <div ref={dialog} className="tutorial-image-dialog" role="dialog" aria-modal="true" aria-label={labels.viewer} aria-describedby={captionId} lang={locale}>
        <div className="tutorial-image-controls">
          <div className="tutorial-image-zoom">
            <button type="button" aria-label={labels.decrease} title={labels.decrease} disabled={zoom <= 1} onClick={() => changeZoom(zoom / 1.25)}><Minus size={18} aria-hidden="true" /></button>
            <output aria-live="polite">{Math.round(zoom * 100)}%</output>
            <button type="button" aria-label={labels.increase} title={labels.increase} disabled={zoom >= 4} onClick={() => changeZoom(zoom * 1.25)}><Plus size={18} aria-hidden="true" /></button>
            <button type="button" aria-label={labels.fit} title={labels.fit} disabled={zoom === 1} onClick={() => changeZoom(1)}><Maximize size={18} aria-hidden="true" /></button>
          </div>
          <a href={src} target="_blank" rel="noopener noreferrer">{labels.original}<ExternalLink size={15} aria-hidden="true" /></a>
          <button ref={closeButton} type="button" className="tutorial-image-close" aria-label={labels.close} title={labels.close} onClick={() => setOpen(false)}><X size={24} aria-hidden="true" /></button>
        </div>
        <div ref={stage} className="tutorial-image-stage" tabIndex={0} role="region" aria-label={labels.area}>
          <div className="tutorial-image-canvas" style={{ width }} onClick={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
            <img ref={picture} src={src} alt={alt} draggable={false} style={{ width, maxWidth: zoom === 1 ? "100%" : "none" }} onLoad={(event) => setNaturalWidth(event.currentTarget.naturalWidth)} />
          </div>
        </div>
        <footer className="tutorial-image-footer"><p id={captionId}>{caption}</p><small className="tutorial-image-wheel-hint">{labels.hint}</small></footer>
      </div>
    </div>, document.body)}
  </>;
}
