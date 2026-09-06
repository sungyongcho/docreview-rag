import type { CSSProperties } from "react";

/** Viewport rectangle of a spotlighted element, padded and clamped to the window. */
export interface TargetRect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

/** True when two measurements describe the same box; lets a poller skip a no-op state update. */
export function sameRect(left: TargetRect, right: TargetRect): boolean {
  return left.top === right.top && left.left === right.left && left.right === right.right && left.bottom === right.bottom;
}

/** Measure an element for a spotlight or callout, keeping a 7px halo inside the viewport. */
export function targetRect(element: HTMLElement): TargetRect {
  const value = element.getBoundingClientRect();
  const padding = 7;
  const top = Math.max(6, value.top - padding);
  const left = Math.max(6, value.left - padding);
  const right = Math.min(window.innerWidth - 6, value.right + padding);
  const bottom = Math.min(window.innerHeight - 6, value.bottom + padding);
  return {
    top,
    left,
    right,
    bottom,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  };
}

/** jsdom measures nothing, so visibility filtering only applies where the document actually has layout. */
function hasLayout(): boolean {
  return document.documentElement.getBoundingClientRect().height > 0;
}

/**
 * Measure an element for a marker: the part of its box that is actually on screen, or null when the
 * element is hidden or scrolled out of the viewport or of a scrolling ancestor. Unlike `targetRect`
 * the result never extends past what the reader can see, so a callout always sits on its own target.
 */
export function visibleRect(element: HTMLElement): TargetRect | null {
  const box = element.getBoundingClientRect();
  let top = 0;
  let left = 0;
  let right = window.innerWidth;
  let bottom = window.innerHeight;
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    const style = window.getComputedStyle(parent);
    if (!/(auto|scroll|hidden)/.test(`${style.overflowY} ${style.overflowX}`)) continue;
    // Clip per axis: a grid child can report a zero-width box while still painting its children,
    // and such a box says nothing about what the reader can see on that axis.
    const pane = parent.getBoundingClientRect();
    if (pane.height > 0) {
      top = Math.max(top, pane.top);
      bottom = Math.min(bottom, pane.bottom);
    }
    if (pane.width > 0) {
      left = Math.max(left, pane.left);
      right = Math.min(right, pane.right);
    }
  }
  if (!hasLayout()) {
    return { top: box.top, left: box.left, right: box.right, bottom: box.bottom, width: box.width, height: box.height };
  }
  // The visible part of the target: empty means display:none, detached, or scrolled out of its pane.
  const visibleTop = Math.max(box.top, top);
  const visibleLeft = Math.max(box.left, left);
  const visibleRight = Math.min(box.right, right);
  const visibleBottom = Math.min(box.bottom, bottom);
  if (visibleRight <= visibleLeft || visibleBottom <= visibleTop) return null;
  return {
    top: visibleTop,
    left: visibleLeft,
    right: visibleRight,
    bottom: visibleBottom,
    width: visibleRight - visibleLeft,
    height: visibleBottom - visibleTop,
  };
}

/** Place a 380px card beside the rect: right of it, else left, else below or above; centred without a rect. */
export function cardPosition(rect: TargetRect | null): CSSProperties {
  if (!rect) return { left: "50%", top: "50%", transform: "translate(-50%, -50%)" };
  const width = Math.min(380, window.innerWidth - 32);
  const gap = 18;
  let left = rect.right + gap;
  let top = rect.top;
  if (left + width > window.innerWidth - 16) left = rect.left - width - gap;
  if (left < 16) {
    left = Math.min(Math.max(16, rect.left), window.innerWidth - width - 16);
    top = rect.bottom + gap;
    if (top + 270 > window.innerHeight) top = Math.max(16, rect.top - 270 - gap);
  }
  return {
    left,
    top: Math.min(Math.max(16, top), Math.max(16, window.innerHeight - 286)),
    width,
  };
}
