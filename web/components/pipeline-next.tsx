"use client";

import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { useRetainedPanelActive } from "./retained-panel";

/** Show the navigation countdown inside the button; leaving the workspace cancels it. */
export function PipelineNext({ onNext, completed = false }: { onNext: () => void; completed?: boolean }) {
  const { t } = useI18n();
  const active = useRetainedPanelActive();
  const [phase, setPhase] = useState<"idle" | "countdown">("idle");
  const [seconds, setSeconds] = useState(3);
  const finished = useRef(false);
  const next = useRef(onNext);
  next.current = onNext;
  useEffect(() => {
    if (!active) { setPhase("idle"); setSeconds(3); finished.current = false; return; }
    if (phase !== "countdown") return;
    let remaining = 3;
    const timer = window.setInterval(() => {
      remaining -= 1;
      if (remaining === 0) { window.clearInterval(timer); if (!finished.current) { finished.current = true; next.current(); } }
      else setSeconds(remaining);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [active, phase]);
  return <div className="pipeline-next">
    <button type="button" className={`button primary${completed || phase === "countdown" ? " pipeline-confirmed" : ""}`} onClick={() => { if (completed || phase === "countdown") { if (!finished.current) { finished.current = true; next.current(); } } else { finished.current = false; setSeconds(3); setPhase("countdown"); } }}>
      {completed && <Check size={15} aria-hidden="true" />}{t(completed ? "Complete" : phase === "countdown" ? "Continue?" : "Next step")}
      {!completed && phase === "countdown" && <span className="pipeline-countdown-inline" role="status" aria-label={t("Moving in {seconds} seconds", { seconds })}><svg viewBox="0 0 32 32" aria-hidden="true"><rect x="2" y="2" width="28" height="28" rx="7" pathLength="100" /></svg>{seconds}</span>}
    </button>
  </div>;
}
