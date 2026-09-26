import { useEffect } from "react";

/**
 * Scroll a Help topic's `data-help` target into view, opening the disclosures around it.
 *
 * Lazy panels and evaluation dialogs can mount after the workspace navigation commits, so the
 * page is watched for up to two seconds; `screenKey` restarts the watch whenever the visible
 * workspace, tab or conversation settings tab changes.
 */
export function useHelpTargetReveal(pendingTarget: string | null, clearPendingTarget: () => void, screenKey: string) {
  useEffect(() => {
    if (!pendingTarget) return;
    let finished = false;
    const observer = new MutationObserver(revealTarget);
    function revealTarget() {
      if (finished) return;
      const target = Array.from(document.querySelectorAll<HTMLElement>(`[data-help="${pendingTarget}"]`)).find((element) => !element.closest("[hidden]"));
      if (!target) return;
      finished = true;
      observer.disconnect();
      for (let disclosure = target.closest("details"); disclosure; disclosure = disclosure.parentElement?.closest("details") ?? null) disclosure.open = true;
      target.scrollIntoView?.({ block: "center", inline: "nearest" });
      clearPendingTarget();
    }
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
    const frame = requestAnimationFrame(revealTarget);
    const timeout = window.setTimeout(() => { finished = true; observer.disconnect(); clearPendingTarget(); }, 2000);
    return () => { finished = true; cancelAnimationFrame(frame); window.clearTimeout(timeout); observer.disconnect(); };
  }, [pendingTarget, screenKey]);
}
