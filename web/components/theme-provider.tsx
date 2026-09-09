"use client";

import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { applyTheme, normalizeTheme, readTheme, saveTheme, THEME_KEY, type Theme } from "@/lib/theme";
import { subscribeStorageRestored, storageEventValue } from "@/lib/storage";

const ThemeContext = createContext<{ theme: Theme; setTheme: (theme: Theme) => void }>({ theme: "system", setTheme: () => undefined });

/** App, documentation and production previews share one preference. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, updateTheme] = useState<Theme>("system");
  const current = useRef<Theme>("system");
  useLayoutEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = (value: Theme) => { current.current = value; updateTheme(value); applyTheme(value, media?.matches ?? false); };
    apply(readTheme());
    const restored = subscribeStorageRestored(() => apply(readTheme()));
    const systemChanged = () => { if (current.current === "system") applyTheme("system", media?.matches ?? false); };
    const stored = (event: StorageEvent) => { const value = storageEventValue(event, THEME_KEY); if (value !== undefined) apply(normalizeTheme(value)); };
    media?.addEventListener("change", systemChanged);
    window.addEventListener("storage", stored);
    return () => { restored(); media?.removeEventListener("change", systemChanged); window.removeEventListener("storage", stored); };
  }, []);
  const setTheme = useCallback((value: Theme) => {
    saveTheme(value);
    current.current = value;
    updateTheme(value);
    applyTheme(value, window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  }, []);
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() { return useContext(ThemeContext); }
