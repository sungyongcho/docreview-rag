"use client";

import { ArrowLeft, ArrowRight, Pointer, X } from "lucide-react";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from "react";

interface TourStep {
  title: string;
  description: string;
  targets: readonly string[];
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
  { title: "Start a new review", description: "Create a clean review thread from the sidebar.", targets: ["new-review"] },
  { title: "Ask or adjust the session", description: "Open Session profile to choose engine, corpus, companies, and retrieval preset, then type in the composer.", targets: ["composer"] },
  { title: "Verify and reuse evidence", description: "Expand candidates, pin or exclude chunks, and re-run citation validation with the selected set.", targets: ["evidence-toggle", "evidence-fallback"] },
  { title: "Continue earlier reviews", description: "Recent reviews and retrieval profiles stay in this browser.", targets: ["recent-reviews"] },
  { title: "Experiment in Corpus Lab", description: "Inspect documents, run golden evaluations, and compare retrieval profiles.", targets: ["corpus-lab"] },
  { title: "Check runtime health", description: "See API, database, corpus, and active model policy state.", targets: ["system-status"] },
  { title: "Run local operations", description: "Use allowlisted local verification and service commands without exposing a shell.", targets: ["operations"], optional: "operations" },
  { title: "Open the documentation", description: "Read architecture, local build, deployment, and operating guidance.", targets: ["documentation"] },
] as const;

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
}: {
  onClose: () => void;
  includeOperations?: boolean;
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
    const update = () => setRect(targetRect(target as HTMLElement));
    const onClick = () => advance();
    update();
    target.addEventListener("click", onClick);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(target);
    return () => {
      target?.removeEventListener("click", onClick);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      observer?.disconnect();
    };
  }, [active, advance]);

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
