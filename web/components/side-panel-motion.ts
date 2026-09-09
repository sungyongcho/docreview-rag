/** Match the run-details panel's 36px, 180ms exit before dismissing the surface. */
export function closeSidePanel(panel: HTMLElement | null, close: () => void) {
  if (!panel || typeof panel.animate !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) { close(); return; }
  if (panel.dataset.closing === "true") return;
  panel.dataset.closing = "true";
  const motion = panel.animate([{ opacity: 1, transform: "translateX(0)" }, { opacity: 0, transform: "translateX(36px)" }], { duration: 180, easing: "ease-in", fill: "forwards" });
  motion.finished.then(() => { delete panel.dataset.closing; close(); motion.cancel(); }, () => { delete panel.dataset.closing; });
}
