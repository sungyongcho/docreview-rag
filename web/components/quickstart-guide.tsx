"use client";

import { createContext, useContext, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { DocumentationOutline } from "@/components/documentation-navigation";
import { initialQuickStartMode, latestReadingState, linkedQuickStartMode } from "@/lib/documentation-reading";
import type { TutorialHeading } from "@/lib/tutorial-markdown.mjs";

type Mode = "cli" | "web";
const ModeContext = createContext<{ mode: Mode; select: (mode: Mode) => void }>({ mode: "web", select: () => {} });

/** Preserve a linked step when changing interface or switching document language. */
export function QuickStartProvider({ children }: { children: ReactNode }) {
  // The server and first client render agree; apply browser-only hints before paint.
  const [mode, setMode] = useState<Mode>("web");
  const hinted = linkedQuickStartMode() ?? latestReadingState()?.quickstart;
  useLayoutEffect(() => {
    if (hinted && hinted !== mode) setMode(hinted);
  }, [hinted, mode]);
  useLayoutEffect(() => {
    setMode(initialQuickStartMode());
    const followHash = () => { if (window.location.hash.startsWith("#qs-cli")) setMode("cli"); else if (window.location.hash.startsWith("#qs-web")) setMode("web"); };
    followHash();
    window.addEventListener("hashchange", followHash);
    return () => window.removeEventListener("hashchange", followHash);
  }, []);
  useLayoutEffect(() => {
    window.dispatchEvent(new Event("docreview:quickstart-ready"));
  }, [mode]);
  function select(next: Mode) {
    setMode(next);
    const hash = window.location.hash.replace(/^#qs-(cli|web)/, `#qs-${next}`);
    window.history.replaceState(null, "", hash || `#qs-${next}`);
  }
  return <ModeContext.Provider value={{ mode, select }}>{children}</ModeContext.Provider>;
}

/** Present equivalent procedures with keyboard-operable tabs and distinct heading anchors. */
export function QuickStartPanels({ cli, web, locale }: { cli: ReactNode; web: ReactNode; locale: "ko" | "en" }) {
  const { mode, select } = useContext(ModeContext);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const modes: Mode[] = ["cli", "web"];
  return <div className="quickstart-guide">
    <div className="quickstart-tabs" role="tablist" aria-label={locale === "ko" ? "실행 방법" : "Choose your interface"}>
      {modes.map((item, index) => <button key={item} ref={(element) => { buttons.current[index] = element; }} id={`quickstart-${item}-tab`} type="button" role="tab" aria-selected={mode === item} aria-controls={`quickstart-${item}-panel`} tabIndex={mode === item ? 0 : -1} onClick={() => select(item)} onKeyDown={(event) => {
        const target = event.key === "Home" ? 0 : event.key === "End" ? 1 : ["ArrowLeft", "ArrowRight"].includes(event.key) ? 1 - index : null;
        if (target !== null) { event.preventDefault(); select(modes[target]); buttons.current[target]?.focus(); }
      }}>{item === "cli" ? "CLI" : "Web"}</button>)}
    </div>
    {modes.map((item) => <section key={item} id={`quickstart-${item}-panel`} role="tabpanel" aria-labelledby={`quickstart-${item}-tab`} hidden={mode !== item} tabIndex={0}>{item === "cli" ? cli : web}</section>)}
  </div>;
}

/** Hide the inactive procedure from the document outline without renumbering existing guides. */
export function QuickStartOutline({ headings, locale }: { headings: TutorialHeading[]; locale: "ko" | "en" }) {
  const { mode } = useContext(ModeContext);
  return <DocumentationOutline headings={headings.filter((heading) => !heading.id.startsWith(`qs-${mode === "cli" ? "web" : "cli"}`)).map((heading) => heading.id.startsWith(`qs-${mode}-`) ? { ...heading, depth: 2 } : heading)} locale={locale} />;
}
