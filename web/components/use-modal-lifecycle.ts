"use client";

import { useEffect, type KeyboardEvent, type RefObject } from "react";

interface ModalOptions {
  active?: boolean;
  onDismiss: () => void;
  initialFocus?: "first" | "panel";
  restoreFocus?: RefObject<HTMLElement | null>;
  lockScroll?: boolean;
  inertBackground?: boolean;
}

/** Exclude controls hidden by retained panels, disabled fieldsets, or closed details. */
function canFocus(element: HTMLElement): boolean {
  if (
    !element.isConnected
    || element.closest("[hidden], [inert]")
    || element.matches(":disabled, input[type=hidden]")
  ) return false;
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (
      parent instanceof HTMLDetailsElement
      && !parent.open
      && !parent.querySelector("summary")?.contains(element)
    ) return false;
  }
  return true;
}

/** Return the active controls in DOM order, including summaries but excluding negative tab stops. */
function focusableControls(panel: HTMLElement): HTMLElement[] {
  return [...panel.querySelectorAll<HTMLElement>("button, input, select, textarea, a[href], summary, [tabindex]")]
    .filter(element => element.tabIndex >= 0 && canFocus(element));
}

/** Manage modal focus and cleanup; attach the returned keyboard handler to the modal element. */
export function useModalLifecycle(
  panelRef: RefObject<HTMLElement | null>,
  {
    active = true,
    onDismiss,
    initialFocus = "first",
    restoreFocus,
    lockScroll = false,
    inertBackground = false,
  }: ModalOptions,
) {
  useEffect(() => {
    const panel = panelRef.current;
    if (!active || !panel) return;
    const previousFocus = restoreFocus?.current ?? (document.activeElement as HTMLElement | null);
    const previousOverflow = document.body.style.overflow;
    const background = inertBackground
      ? [...document.body.children].filter(element => !element.contains(panel) && !element.hasAttribute("inert"))
      : [];
    background.forEach(element => element.setAttribute("inert", ""));
    if (lockScroll) document.body.style.overflow = "hidden";
    const nativeDialog = panel instanceof HTMLDialogElement ? panel : null;
    nativeDialog?.showModal();
    (initialFocus === "panel" ? panel : focusableControls(panel)[0] ?? panel).focus();

    return () => {
      nativeDialog?.close();
      background.forEach(element => element.removeAttribute("inert"));
      if (lockScroll) document.body.style.overflow = previousOverflow;
      if (previousFocus && canFocus(previousFocus)) {
        previousFocus.focus({ preventScroll: true });
      }
    };
  }, [active, panelRef, initialFocus, restoreFocus, lockScroll, inertBackground]);

  /** Let child controls handle keys first, then contain dismissal and focus within this modal. */
  return (event: KeyboardEvent<HTMLElement>) => {
    const panel = panelRef.current;
    if (!active || !panel || event.defaultPrevented) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onDismiss();
      return;
    }
    if (event.key !== "Tab") return;
    event.stopPropagation();
    const controls = focusableControls(panel);
    const first = controls[0];
    const last = controls.at(-1);
    const focused = document.activeElement as HTMLElement | null;
    if (!focused || !controls.includes(focused)) {
      event.preventDefault();
      (event.shiftKey ? last ?? panel : first ?? panel).focus();
    } else if (event.shiftKey && focused === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && focused === last) {
      event.preventDefault();
      first?.focus();
    }
  };
}
