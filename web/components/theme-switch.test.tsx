import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeProvider } from "./theme-provider";
import { ThemeSwitch } from "./theme-switch";
import { browserStorage, enterProductionPreview, exitProductionPreview } from "@/lib/production-preview";
import { THEME_BOOTSTRAP, THEME_KEY } from "@/lib/theme";
import { runInNewContext } from "node:vm";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { transform } from "lightningcss";

let dark = false;
const changes = new Set<() => void>();
beforeEach(() => {
  exitProductionPreview();
  localStorage.clear();
  dark = false;
  changes.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ get matches() { return dark; }, addEventListener: (_event: string, listener: () => void) => changes.add(listener), removeEventListener: (_event: string, listener: () => void) => changes.delete(listener) })));
});
afterEach(() => {
  cleanup();
  exitProductionPreview();
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

it("shares theme choices between a preview document and its DEV host", () => {
  localStorage.setItem(THEME_KEY, "light");
  enterProductionPreview("document");
  expect(browserStorage().getItem(THEME_KEY)).toBe("light");
  render(<ThemeProvider><ThemeSwitch locale="en" /></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Theme: Light" }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: "System" }));
  expect(browserStorage().getItem(THEME_KEY)).toBe("system");
  expect(localStorage.getItem(THEME_KEY)).toBe("system");
  fireEvent(window, new StorageEvent("storage", { key: THEME_KEY, newValue: "dark" }));
  expect(screen.getByRole("button", { name: "Theme: Dark" })).toBeInTheDocument();
});

it("applies the same first-paint preference inside preview frames", () => {
  const html = { dataset: {} as Record<string, string>, style: {} as Record<string, string> };
  const getItem = vi.fn(() => "dark");
  const sandbox = { window: { name: "", matchMedia: () => ({ matches: false }) }, document: { documentElement: html }, localStorage: { getItem }, URLSearchParams, location: { search: "" } };
  runInNewContext(THEME_BOOTSTRAP, sandbox);
  expect(html.style.colorScheme).toBe("dark");
  expect(html.dataset.theme).toBe("dark");
  getItem.mockClear();
  sandbox.window.name = "docreview-production-preview";
  runInNewContext(THEME_BOOTSTRAP, sandbox);
  expect(html.style.colorScheme).toBe("dark");
  expect(getItem).toHaveBeenCalledWith(THEME_KEY);
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
