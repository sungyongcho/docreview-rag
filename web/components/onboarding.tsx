"use client";

import { ArrowLeft, ArrowRight, Pointer, X } from "lucide-react";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

/** Workspace the shell must show before a step's target can be spotlighted. */
export type TourView = "build" | "review" | "measure" | "system";

interface TourStep {
  title: string;
  description: string;
  targets: readonly string[];
  view: TourView;
  tab?: string;
  optional?: "operations";
}

interface TargetRect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

const STEPS: readonly TourStep[] = [
  { title: "Start with Build", description: "The pipeline runs top to bottom: filings, chunks, embeddings, BM25 index, then asking, answering and evaluating.", targets: ["build"], view: "build" },
  { title: "Seven steps, in order", description: "Each card shows real numbers, its status, and one action. Blocked steps tell you which step to finish first.", targets: ["stage-list"], view: "build", tab: "pipeline" },
  { title: "One obvious next action", description: "This callout always points at the first step that needs you.", targets: ["next-step"], view: "build", tab: "pipeline" },
  { title: "Start a new review", description: "Create a clean review thread from the sidebar.", targets: ["new-review"], view: "review" },
  { title: "Ask or adjust the session", description: "Pick scope and preset inline, then type. The readiness chip tells you what the corpus can do right now.", targets: ["composer"], view: "review" },
  { title: "Verify and reuse evidence", description: "Expand citations, pin or exclude chunks, and re-run the citation check with your selection.", targets: ["evidence-toggle", "evidence-fallback"], view: "review" },
  { title: "Measure before trusting", description: "Golden questions, runs, comparisons and snapshots live here.", targets: ["measure"], view: "measure" },
  { title: "Run local operations", description: "System › Operations runs allowlisted verification and service commands without a shell.", targets: ["operations"], view: "system", tab: "operations", optional: "operations" },
] as const;

/** Every `data-tour` name a step can spotlight, so a test can assert the shell renders each one. */
export const TOUR_TARGETS: readonly string[] = [...new Set(STEPS.flatMap((item) => item.targets))];

function sameRect(left: TargetRect, right: TargetRect): boolean {
  return left.top === right.top && left.left === right.left && left.right === right.right && left.bottom === right.bottom;
}

function targetRect(element: HTMLElement): TargetRect {
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

function cardPosition(rect: TargetRect | null): CSSProperties {
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

export function Onboarding({
  onClose,
  includeOperations = false,
  onStepChange,
  location,
}: {
  onClose: () => void;
  includeOperations?: boolean;
  /** Lets the shell switch workspace and tab before the step's target is measured. */
  onStepChange?: (step: { view: TourView; tab?: string }) => void;
  /** The shell's committed workspace and tab; a change re-measures the step's target once the shell has navigated. */
  location?: string;
}) {
  const steps = useMemo(
    () => STEPS.filter((item) => item.optional !== "operations" || includeOperations),
    [includeOperations],
  );
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<TargetRect | null>(null);
  const active = steps[step];

  const advance = useCallback(() => {
    if (step === steps.length - 1) onClose();
    else setStep((value) => value + 1);
  }, [onClose, step, steps.length]);

  // Refs carry the latest callbacks so the effects below run on step or location changes only,
  // never because the shell re-rendered with a new inline function.
  const stepChange = useRef(onStepChange);
  const advanceRef = useRef(advance);
  useLayoutEffect(() => {
    stepChange.current = onStepChange;
    advanceRef.current = advance;
  });
  // Before paint: the shell navigates first, then the measurement below runs again with the new `location`.
  useLayoutEffect(() => {
    stepChange.current?.(active.tab === undefined ? { view: active.view } : { view: active.view, tab: active.tab });
  }, [active]);

  useLayoutEffect(() => {
    let target: HTMLElement | null = null;
    for (const name of active.targets) {
      target = document.querySelector<HTMLElement>(`[data-tour="${name}"]`);
      if (target) break;
    }
    if (!target) {
      setRect(null);
      return;
    }
    if (typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    const update = () => {
      const next = targetRect(target as HTMLElement);
      setRect((current) => (current && sameRect(current, next) ? current : next));
    };
    const onClick = () => advanceRef.current();
    update();
    target.addEventListener("click", onClick);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    resizeObserver?.observe(target);
    // Content arriving next to the target (job progress, corpus numbers) moves it without resizing it.
    const mutationObserver = typeof MutationObserver === "undefined" ? null : new MutationObserver(update);
    mutationObserver?.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
    return () => {
      target?.removeEventListener("click", onClick);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, [active, location]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pointerStyle: CSSProperties | undefined = rect
    ? { left: Math.min(rect.right - 16, window.innerWidth - 42), top: Math.min(rect.bottom - 8, window.innerHeight - 42) }
    : undefined;

  return (
    <div className="tour-layer" role="presentation">
      {rect ? <>
        <div className="tour-shade" style={{ inset: "0 0 auto 0", height: rect.top }} />
        <div className="tour-shade" style={{ top: rect.top, left: 0, width: rect.left, height: rect.height }} />
        <div className="tour-shade" style={{ top: rect.top, left: rect.right, right: 0, height: rect.height }} />
        <div className="tour-shade" style={{ top: rect.bottom, right: 0, bottom: 0, left: 0 }} />
        <div className="tour-spotlight" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
        <Pointer className="tour-pointer" style={pointerStyle} aria-hidden="true" />
      </> : <div className="tour-shade tour-shade-full" />}
      <section className="tour-dialog" style={cardPosition(rect)} role="dialog" aria-labelledby="tour-title">
        <button className="icon-button tour-x" type="button" onClick={onClose} aria-label="Close tutorial"><X size={17} /></button>
        <p className="eyebrow">Step {step + 1} of {steps.length}</p>
        <h2 id="tour-title">{active.title}</h2>
        <p>{active.description}</p>
        <p className="tour-target-hint">Click the highlighted control or use Next.</p>
        <div className="tour-progress" aria-label={`Tutorial step ${step + 1} of ${steps.length}`} style={{ gridTemplateColumns: `repeat(${steps.length}, 1fr)` }}>
          {steps.map((item, index) => <span key={item.title} className={index <= step ? "done" : ""} />)}
        </div>
        <div className="tour-actions">
          <button className="button ghost" type="button" onClick={onClose}>Skip</button>
          <div>
            <button className="button ghost" type="button" disabled={step === 0} onClick={() => setStep((value) => value - 1)}><ArrowLeft size={15} /> Back</button>
            <button className="button primary" type="button" onClick={advance}>{step === steps.length - 1 ? "Finish" : "Next"} <ArrowRight size={15} /></button>
          </div>
        </div>
      </section>
    </div>
  );
}
