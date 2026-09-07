import { browserStorage, browserThemeBootstrap } from "./storage";

export type Theme = "light" | "dark" | "system";
export const THEME_KEY = "docreview:theme";

export function normalizeTheme(value: string | null | undefined): Theme {
  return value === "light" || value === "dark" ? value : "system";
}

export function readTheme(): Theme {
  try { return normalizeTheme(browserStorage().getItem(THEME_KEY)); }
  catch { return "system"; }
}

export function saveTheme(theme: Theme): void {
  try { browserStorage().setItem(THEME_KEY, theme); }
  catch { /* The current page can still use the selected theme when storage is unavailable. */ }
}

export function applyTheme(theme: Theme, systemDark: boolean): void {
  const resolved = theme === "system" ? systemDark ? "dark" : "light" : theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.colorMode = resolved;
  document.documentElement.style.colorScheme = resolved;
}

/** Run before first paint; only a validated display preference enters the DOM. */
export const THEME_BOOTSTRAP = browserThemeBootstrap(THEME_KEY);
