"use client";

import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useI18n, type Locale } from "@/lib/i18n";
import type { Theme } from "@/lib/theme";
import { useRetainedPanelActive } from "./retained-panel";
import { useTheme } from "./theme-provider";
import "./theme-switch.css";

const OPTIONS: Array<{ value: Theme; Icon: typeof Sun }> = [{ value: "light", Icon: Sun }, { value: "dark", Icon: Moon }, { value: "system", Icon: Monitor }];
const LABELS = {
  en: { theme: "Theme", light: "Light", dark: "Dark", system: "System" },
  ko: { theme: "테마", light: "라이트", dark: "다크", system: "시스템" },
};

/** One compact icon opens the same accessible theme choices in either header. */
export function ThemeSwitch({ locale: documentLocale }: { locale?: Locale } = {}) {
  const { locale } = useI18n();
  const labels = LABELS[documentLocale ?? locale];
  const { theme, setTheme } = useTheme();
  const active = useRetainedPanelActive();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const visible = open && active;
  const Icon = OPTIONS.find((option) => option.value === theme)!.Icon;
  useLayoutEffect(() => {
    if (!visible) return;
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) setPosition({ top: Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 160)), left: Math.max(8, Math.min(rect.right - 168, window.innerWidth - 176)) });
    menu.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus();
    const outside = (event: PointerEvent) => { if (!trigger.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false); };
    const dismiss = () => setOpen(false);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("resize", dismiss);
    return () => { document.removeEventListener("pointerdown", outside); window.removeEventListener("resize", dismiss); };
  }, [visible]);
  function close() { setOpen(false); trigger.current?.focus(); }
  return <>
    <button ref={trigger} className="icon-button theme-switch-trigger" type="button" aria-label={`${labels.theme}: ${labels[theme]}`} title={`${labels.theme}: ${labels[theme]}`} aria-haspopup="menu" aria-expanded={visible} onClick={() => setOpen(!open)} onKeyDown={(event) => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); } }}><Icon size={18} aria-hidden="true" /></button>
    {visible && createPortal(<div ref={menu} className="theme-switch-menu" role="menu" aria-label={labels.theme} style={position} onKeyDown={(event) => {
      const controls = [...(menu.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
      const index = controls.indexOf(document.activeElement as HTMLButtonElement);
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
      else if (event.key === "Tab") close();
      else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? controls.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + controls.length) % controls.length;
        controls[next]?.focus();
      }
    }}>{OPTIONS.map(({ value, Icon: ChoiceIcon }) => <button type="button" key={value} role="menuitemradio" aria-checked={theme === value} onClick={() => { setTheme(value); close(); }}><ChoiceIcon size={16} aria-hidden="true" /><span>{labels[value]}</span>{theme === value && <Check size={15} aria-hidden="true" />}</button>)}</div>, document.body)}
  </>;
}
