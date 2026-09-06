import { afterEach, expect, it, vi } from "vitest";
import { clearExtremeBrowserData } from "./reset-browser";

afterEach(() => { localStorage.clear(); sessionStorage.clear(); vi.restoreAllMocks(); });

it("clears conversation/preferences/session data and preserves unrelated sentinels", () => {
  localStorage.setItem("docreview:conversations:v2", "private conversation");
  localStorage.setItem("docreview.locale", "ko");
  localStorage.setItem("unrelated", "sentinel");
  sessionStorage.setItem("docreview:session", "private session");
  clearExtremeBrowserData(localStorage, sessionStorage);
  expect(localStorage.getItem("docreview:conversations:v2")).toBeNull();
  expect(localStorage.getItem("docreview.locale")).toBeNull();
  expect(sessionStorage.length).toBe(0);
  expect(localStorage.getItem("unrelated")).toBe("sentinel");
});

it("fails instead of acknowledging incomplete deletion", () => {
  localStorage.setItem("docreview:conversations:v2", "private conversation");
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {});
  expect(() => clearExtremeBrowserData(localStorage)).toThrow("incomplete");
});
