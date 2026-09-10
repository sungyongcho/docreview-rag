import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeProvider } from "./theme-provider";
import { ThemeSwitch } from "./theme-switch";
import { browserStorage, configureBrowserStorage } from "@/lib/storage";
import { THEME_BOOTSTRAP, THEME_KEY } from "@/lib/theme";
import { runInNewContext } from "node:vm";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { transform } from "lightningcss";

let dark = false;
const changes = new Set<() => void>();
beforeEach(() => {
  configureBrowserStorage("dev");
  localStorage.clear();
  dark = false;
  changes.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ get matches() { return dark; }, addEventListener: (_event: string, listener: () => void) => changes.add(listener), removeEventListener: (_event: string, listener: () => void) => changes.delete(listener) })));
});
afterEach(() => {
  cleanup();
  configureBrowserStorage(undefined);
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.colorMode;
  document.documentElement.style.removeProperty("color-scheme");
});

it("persists a selected theme across app and document controls and returns keyboard focus", () => {
  const view = render(<ThemeProvider><ThemeSwitch locale="en" /></ThemeProvider>);
  const trigger = screen.getByRole("button", { name: "Theme: System" });
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  expect(screen.getByRole("menuitemradio", { name: "System" })).toHaveFocus();
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Dark" }));
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  expect(document.documentElement.dataset.colorMode).toBe("dark");
  expect(screen.getByRole("button", { name: "Theme: Dark" })).toHaveFocus();
  view.unmount();
  render(<ThemeProvider><ThemeSwitch locale="ko" /></ThemeProvider>);
  expect(screen.getByRole("button", { name: "테마: 다크" })).toBeInTheDocument();
});

it("follows OS changes in System mode but keeps an explicit Light choice", () => {
  render(<ThemeProvider><ThemeSwitch locale="en" /></ThemeProvider>);
  expect(document.documentElement.dataset.colorMode).toBe("light");
  act(() => { dark = true; changes.forEach((listener) => listener()); });
  expect(document.documentElement.dataset.colorMode).toBe("dark");
  fireEvent.click(screen.getByRole("button", { name: "Theme: System" }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "Light" }));
  act(() => { dark = false; changes.forEach((listener) => listener()); dark = true; changes.forEach((listener) => listener()); });
  expect(document.documentElement.dataset.colorMode).toBe("light");
  fireEvent(window, new StorageEvent("storage", { key: THEME_KEY, newValue: "dark" }));
  expect(screen.getByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();
});

it("persists PROD theme choices and receives versioned cross-tab changes", () => {
  configureBrowserStorage("prod");
  browserStorage().setItem(THEME_KEY, "light");
  expect(browserStorage().getItem(THEME_KEY)).toBe("light");
  render(<ThemeProvider><ThemeSwitch locale="en" /></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Theme: Light" }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "System" }));
  expect(browserStorage().getItem(THEME_KEY)).toBe("system");
  expect(JSON.parse(localStorage.getItem(`${THEME_KEY}:v1`)!)).toEqual({ version: 1, value: "system" });
  fireEvent(window, new StorageEvent("storage", { key: `${THEME_KEY}:v1`, newValue: JSON.stringify({ version: 1, value: "dark" }) }));
  expect(screen.getByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();
});

it.each(["dark", JSON.stringify({ version: 1, value: "dark" })])("applies saved theme %s before first paint", (saved) => {
  const html = { dataset: {} as Record<string, string>, style: {} as Record<string, string> };
  const key = saved === "dark" ? THEME_KEY : `${THEME_KEY}:v1`;
  const getItem = vi.fn((name: string) => name === key ? saved : null);
  const sandbox = { window: { matchMedia: () => ({ matches: false }) }, document: { documentElement: html }, localStorage: { getItem } };
  runInNewContext(THEME_BOOTSTRAP, sandbox);
  expect(html.style.colorScheme).toBe("dark");
  expect(html.dataset.theme).toBe("dark");
  expect(html.dataset.colorMode).toBe("dark");
  expect(getItem).toHaveBeenCalledWith(key);
});

it("closes the theme menu with Escape without changing the selection", () => {
  render(<ThemeProvider><ThemeSwitch locale="en" /></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Theme: System" }));
  fireEvent.keyDown(screen.getByRole("menuitemradio", { name: "System" }), { key: "Home" });
  expect(screen.getByRole("menuitemradio", { name: "Light" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menuitemradio", { name: "Light" }), { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
  expect(screen.getByRole("button", { name: "Theme: System" })).toHaveFocus();
  expect(localStorage.getItem(THEME_KEY)).toBeNull();
});

it("compiles manual theme selectors with the same palette state as the OS branches", () => {
  const compile = (code: Uint8Array) => transform({ filename: "theme.css", code, targets: { chrome: 109 << 16 } }).code.toString();
  const palette = compile(Buffer.from(":root {color-scheme:light dark;--probe:light-dark(white,black)}"));
  const theme = compile(readFileSync(resolve(process.cwd(), "components/theme-switch.css")));
  const properties = (body: string) => new Map([...body.matchAll(/(--[\w-]+):([^;]*);/g)].map((match) => [match[1], match[2].trim()]));
  const base = properties(palette.match(/:root\s*\{([^}]+)\}/)![1]);
  const systemDark = properties(palette.match(/@media[^{}]+\{\s*:root\s*\{([^}]+)\}/)![1]);
  const light = properties(theme.match(/html\[data-color-mode="light"\]\s*\{([^}]+)\}/)![1]);
  const dark = properties(theme.match(/html\[data-color-mode="dark"\]\s*\{([^}]+)\}/)![1]);
  expect(systemDark.size).toBeGreaterThan(0);
  for (const [name, value] of systemDark) {
    expect(light.get(name)).toBe(base.get(name));
    expect(dark.get(name)).toBe(value);
  }
});
