"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { useI18n } from "@/lib/i18n";
import type { MasterDetailResize } from "./use-master-detail";
import styles from "./master-detail.module.css";

/** Resize the list pane with captured pointer gestures or accessible keyboard controls. */
export function MasterDetailDivider({ label, controls, resize }: { label: string; controls: string; resize: MasterDetailResize }) {
  const { t } = useI18n();
  const descriptionId = useId();
  const gesture = useRef<{ pointerId: number; startX: number; startWidth: number; width: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const instructions = t("Drag or use arrow keys to resize. Hold Shift for larger steps. Double-click to reset.");

  useEffect(() => {
    if (!dragging) return;
    const { userSelect, cursor } = document.body.style;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    return () => {
      document.body.style.userSelect = userSelect;
      document.body.style.cursor = cursor;
    };
  }, [dragging]);

  /** Restrict every gesture to the current measured workspace bounds. */
  function bounded(width: number) {
    return Math.max(resize.min, Math.min(resize.max, Math.round(width)));
  }

  /** Capture the primary pointer without taking ownership of page scrolling. */
  function start(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !event.isPrimary || gesture.current) return;
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: resize.value, width: resize.value };
    setDragging(true);
  }

  /** Update the live width from the original grab point to avoid cumulative rounding drift. */
  function move(event: PointerEvent<HTMLDivElement>) {
    const active = gesture.current;
    if (!active || active.pointerId !== event.pointerId) return;
    active.width = bounded(active.startWidth + event.clientX - active.startX);
    resize.onChange(active.width);
  }

  /** Complete or cancel a captured gesture and release all temporary interaction state. */
  function finish(event: PointerEvent<HTMLDivElement>, cancelled = false) {
    const active = gesture.current;
    if (!active || active.pointerId !== event.pointerId) return;
    gesture.current = null;
    setDragging(false);
    if (cancelled) resize.onChange(active.startWidth);
    else resize.onCommit(bounded(active.width));
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  /** Follow the separator keyboard convention, with larger optional Shift steps. */
  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 64 : 16;
    let width: number;
    switch (event.key) {
      case "ArrowLeft": case "-": width = resize.value - step; break;
      case "ArrowRight": case "+": case "=": width = resize.value + step; break;
      case "Home": width = resize.min; break;
      case "End": width = resize.max; break;
      default: return;
    }
    event.preventDefault();
    resize.onCommit(bounded(width));
  }

  return <div
    className={styles.divider}
    role="separator"
    tabIndex={0}
    aria-label={label}
    aria-controls={controls}
    aria-describedby={descriptionId}
    aria-orientation="vertical"
    aria-valuemin={resize.min}
    aria-valuemax={resize.max}
    aria-valuenow={resize.value}
    aria-valuetext={t("{width} pixels", { width: resize.value })}
    title={instructions}
    data-dragging={dragging}
    onPointerDown={start}
    onPointerMove={move}
    onPointerUp={(event) => finish(event)}
    onPointerCancel={(event) => finish(event, true)}
    onLostPointerCapture={(event) => finish(event, true)}
    onKeyDown={keyDown}
    onDoubleClick={resize.onReset}
  ><span className={styles.dividerGrip} aria-hidden="true" /><span className={styles.dividerDescription} id={descriptionId}>{instructions}</span></div>;
}
