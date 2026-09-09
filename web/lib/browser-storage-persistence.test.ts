import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { enterProductionPreview, exitProductionPreview } from "./production-preview";
import { browserStorage, configureBrowserStorage, exportBrowserSettings, importBrowserSettings, loadConversations, loadDefaultProfile, productionBrowserStorageEnabled, saveConversations, saveDefaultProfile, subscribeStorageWarnings, validateBrowserSettings } from "./storage";
import { DEFAULT_PROFILE, DEFAULT_SESSION_PROFILE } from "./types";

const conversations = [{ id: "saved-review", title: "Retained review", createdAt: "2026-09-07T00:00:00Z", updatedAt: "2026-09-07T00:00:00Z", messages: [{ id: "message-1", role: "user" as const, text: "한글 question" }], profile: DEFAULT_SESSION_PROFILE }];

/** Inspect actual origin bytes rather than the facade's decoded view. */
function physicalEntries() {
  return Object.fromEntries(Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)!).sort().map(key => [key, localStorage.getItem(key)]));
}

beforeEach(() => { vi.restoreAllMocks(); exitProductionPreview(); configureBrowserStorage("dev"); localStorage.clear(); });
afterEach(() => { vi.restoreAllMocks(); configureBrowserStorage(undefined); exitProductionPreview(); });

describe("production browser persistence", () => {
  it("keeps DEV writes in their original raw format", () => {
    saveConversations(conversations);
    browserStorage().setItem("docreview:theme", "dark");
    expect(localStorage.getItem("docreview:conversations:v2")).toBe(JSON.stringify(conversations));
    expect(localStorage.getItem("docreview:theme")).toBe("dark");
    expect(localStorage.getItem("docreview:theme:v1")).toBeNull();
  });

  it("keeps preview session data in persistent isolated storage while sharing the theme preference", () => {
    localStorage.setItem("docreview:theme", "light");
    enterProductionPreview("document"); configureBrowserStorage("prod");
    browserStorage().setItem("docreview:theme", "dark"); saveConversations(conversations);
    expect(productionBrowserStorageEnabled()).toBe(true);
    expect(localStorage.getItem("docreview:preview:docreview:conversations:v2")).not.toBeNull();
    expect(browserStorage().getItem("docreview:theme")).toBe("dark");
    expect(localStorage.getItem("docreview:theme")).toBe("dark");
    expect(localStorage.getItem("docreview:conversations:v2")).toBeNull();
    exitProductionPreview(); configureBrowserStorage("dev");
    expect(browserStorage().getItem("docreview:theme")).toBe("dark");
  });

  it("migrates valid legacy conversations, theme and locale once", () => {
    localStorage.setItem("docreview:conversations:v1", JSON.stringify(conversations));
    localStorage.setItem("docreview:theme", "dark"); localStorage.setItem("docreview.locale", "ko");
    const set = vi.spyOn(Storage.prototype, "setItem");
    configureBrowserStorage("prod");
    expect(loadConversations()).toEqual(conversations);
    expect(browserStorage().getItem("docreview:theme")).toBe("dark");
    expect(browserStorage().getItem("docreview.locale")).toBe("ko");
    expect(localStorage.getItem("docreview:conversations:v1")).toBeNull();
    expect(localStorage.getItem("docreview:theme")).toBeNull();
    expect(localStorage.getItem("docreview.locale")).toBeNull();
    const snapshot = physicalEntries(); const writes = set.mock.calls.length;
    configureBrowserStorage("prod"); loadConversations(); browserStorage().getItem("docreview.locale");
    expect(set).toHaveBeenCalledTimes(writes); expect(physicalEntries()).toEqual(snapshot);
    expect(JSON.parse(localStorage.getItem("docreview:theme:v1")!)).toEqual({ version: 1, value: "dark" });
  });

  it("preserves malformed bytes and emits only one corruption warning", () => {
    const raw = "{broken json user's original bytes";
    localStorage.setItem("docreview:profile-defaults:v1", raw);
    localStorage.setItem("docreview:conversations:v2", "[broken");
    const warning = vi.fn(); const unsubscribe = subscribeStorageWarnings(warning);
    configureBrowserStorage("prod"); loadDefaultProfile(); loadConversations(); loadDefaultProfile();
    expect(localStorage.getItem("docreview:profile-defaults:v1")).toBe(raw);
    expect(loadDefaultProfile()).toEqual(DEFAULT_SESSION_PROFILE);
    expect(warning.mock.calls.filter(([entry]) => entry.reason === "corrupt")).toHaveLength(1);
    expect(exportBrowserSettings()).toContain("broken json user's original bytes");
    unsubscribe();
  });

  it("preserves a future envelope and warns once rather than guessing a migration", () => {
    const raw = JSON.stringify({ version: 99, value: "dark" });
    localStorage.setItem("docreview:theme:v1", raw);
    const warning = vi.fn(); const unsubscribe = subscribeStorageWarnings(warning);
    configureBrowserStorage("prod");
    expect(browserStorage().getItem("docreview:theme")).toBeNull();
    expect(browserStorage().getItem("docreview:theme")).toBeNull();
    expect(localStorage.getItem("docreview:theme:v1")).toBe(raw);
    expect(warning.mock.calls.filter(([entry]) => entry.reason === "version")).toHaveLength(1);
    unsubscribe();
  });

  it("does not rewrite future concern key versions", () => {
    const raw = JSON.stringify(conversations);
    localStorage.setItem("docreview:conversations:v99", raw);
    configureBrowserStorage("prod");
    expect(localStorage.getItem("docreview:conversations:v99")).toBe(raw);
    expect(loadConversations()).toEqual([]);
  });

  it.each(["QuotaExceededError", "SecurityError"])("keeps session writes and export usable after %s", name => {
    configureBrowserStorage("prod");
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Unavailable", name); });
    const warning = vi.fn(); const unsubscribe = subscribeStorageWarnings(warning);
    saveConversations(conversations); saveDefaultProfile(DEFAULT_SESSION_PROFILE);
    expect(loadConversations()).toEqual(conversations);
    expect(loadDefaultProfile()).toEqual(DEFAULT_SESSION_PROFILE);
    const backup = exportBrowserSettings();
    expect(validateBrowserSettings(backup).entries.some(entry => entry.key === "docreview:conversations:v2")).toBe(true);
    expect(warning).toHaveBeenCalledTimes(1);
    unsubscribe(); set.mockRestore(); configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
    expect(importBrowserSettings(backup, true)).toBe(true);
    expect(loadConversations()).toEqual(conversations);
  });

  it("survives a private browser throwing while obtaining localStorage", () => {
    const getter = vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new DOMException("Disabled", "SecurityError"); });
    expect(() => configureBrowserStorage("prod")).not.toThrow();
    saveConversations(conversations);
    expect(loadConversations()).toEqual(conversations);
    const backup = exportBrowserSettings();
    getter.mockRestore(); configureBrowserStorage("dev"); configureBrowserStorage("prod");
    expect(importBrowserSettings(backup, true)).toBe(true);
    expect(loadConversations()).toEqual(conversations);
  });

  it("validates without mutation and requires confirmation before any import", () => {
    configureBrowserStorage("prod"); saveConversations(conversations);
    const backup = exportBrowserSettings(); const snapshot = physicalEntries();
    const set = vi.spyOn(Storage.prototype, "setItem"); const remove = vi.spyOn(Storage.prototype, "removeItem");
    expect(validateBrowserSettings(backup).entries.length).toBeGreaterThan(0);
    expect(importBrowserSettings(backup, false)).toBe(false);
    expect(() => importBrowserSettings('{"format":"foreign"}', true)).toThrow();
    expect(set).not.toHaveBeenCalled(); expect(remove).not.toHaveBeenCalled(); expect(physicalEntries()).toEqual(snapshot);
  });

  it.each([
    { key: "another-app:session", version: 0, value: "{}" },
    { key: "docreview:profile-defaults:v1", version: 1, value: JSON.stringify({ prompt_policy: { additional_instructions: 42 } }) },
    { key: "docreview:theme:v1", version: 99, value: "dark" },
    { key: "docreview:theme:v1", version: 1, value: "unsupported-theme" },
  ])("rejects the entire import before writes for invalid entry $key/$version", invalid => {
    configureBrowserStorage("prod"); browserStorage().setItem("docreview:theme", "dark");
    const snapshot = physicalEntries();
    const text = JSON.stringify({ format: "docreview-browser-storage", version: 1, entries: [
      { key: "docreview:locale:v1", version: 1, value: JSON.stringify({ version: 1, value: "en" }) }, invalid,
    ] });
    const set = vi.spyOn(Storage.prototype, "setItem"); const remove = vi.spyOn(Storage.prototype, "removeItem");
    expect(() => importBrowserSettings(text, true)).toThrow();
    expect(set).not.toHaveBeenCalled(); expect(remove).not.toHaveBeenCalled();
    expect(physicalEntries()).toEqual(snapshot);
  });

  it("restores exact serialized bytes to fresh storage and preserves another application's keys", () => {
    configureBrowserStorage("prod"); saveConversations(conversations); saveDefaultProfile(DEFAULT_SESSION_PROFILE);
    browserStorage().setItem("docreview:theme", "dark");
    const snapshot = physicalEntries(); const backup = exportBrowserSettings();
    configureBrowserStorage("dev"); localStorage.clear(); localStorage.setItem("another-app:session", "untouched");
    configureBrowserStorage("prod");
    expect(importBrowserSettings(backup, true)).toBe(true);
    expect(physicalEntries()).toEqual({ ...snapshot, "another-app:session": "untouched" });
    expect(exportBrowserSettings()).not.toContain("another-app:session");
  });

  it("migrates and round-trips named retrieval presets with the established schema", () => {
    const presets = [{ id: "preset-1", name: "Korean research", retrieval: DEFAULT_PROFILE }];
    const raw = JSON.stringify(presets);
    localStorage.setItem("docreview:retrieval-presets:v1", raw);
    configureBrowserStorage("prod");
    expect(browserStorage().getItem("docreview:retrieval-presets:v1")).toBe(raw);
    const backup = exportBrowserSettings();
    configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
    importBrowserSettings(backup, true);
    expect(JSON.parse(browserStorage().getItem("docreview:retrieval-presets:v1")!)).toEqual(presets);
  });
});

// Switching runtime modes at one origin must not turn stored conversations into an empty app.
it("reads prior PROD envelopes in DEV without migrating DEV writes", () => {
  configureBrowserStorage("prod"); saveConversations(conversations);
  const raw = localStorage.getItem("docreview:conversations:v2");
  configureBrowserStorage("dev");
  expect(loadConversations()).toEqual(conversations);
  expect(localStorage.getItem("docreview:conversations:v2")).toBe(raw);
  saveConversations(conversations);
  expect(localStorage.getItem("docreview:conversations:v2")).toBe(JSON.stringify(conversations));
});

it("exports known settings when persistent storage becomes unavailable", () => {
  configureBrowserStorage("prod"); saveConversations(conversations);
  const getter = vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new DOMException("blocked", "SecurityError"); });
  browserStorage().setItem("docreview:theme", "dark");
  const backup = exportBrowserSettings();
  getter.mockRestore(); configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
  expect(importBrowserSettings(backup, true)).toBe(true);
  expect(loadConversations()).toEqual(conversations);
  expect(browserStorage().getItem("docreview:theme")).toBe("dark");
});

it("keeps unreadable original bytes in a restorable recovery export", () => {
  localStorage.setItem("docreview:profile-defaults:v1", "{broken");
  configureBrowserStorage("prod");
  const backup = exportBrowserSettings();
  expect(() => validateBrowserSettings(backup)).not.toThrow();
  configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
  importBrowserSettings(backup, true);
  expect(browserStorage().getItem("docreview:storage-recovery:v1")).toContain("{broken");
  expect(loadDefaultProfile()).toEqual(DEFAULT_SESSION_PROFILE);
});

it("exports the new session overlay as well as damaged originals when recovery cannot persist", () => {
  localStorage.setItem("docreview:conversations:v2", "{broken"); configureBrowserStorage("prod");
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
  saveConversations(conversations);
  const backup = exportBrowserSettings();
  set.mockRestore(); configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
  importBrowserSettings(backup, true);
  expect(loadConversations()).toEqual(conversations);
  expect(browserStorage().getItem("docreview:storage-recovery:v1")).toContain("{broken");
});

it("never deletes the legacy conversation record when its replacement cannot persist", () => {
  localStorage.setItem("docreview:conversations:v1", JSON.stringify(conversations)); configureBrowserStorage("prod");
  const original = localStorage.getItem("docreview:conversations:v1");
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
  expect(loadConversations()).toEqual(conversations);
  expect(localStorage.getItem("docreview:conversations:v1")).toBe(original);
  set.mockRestore(); configureBrowserStorage(undefined); configureBrowserStorage("prod");
  expect(loadConversations()).toEqual(conversations);
});

it.each([{ fiscal_years: 42 }, { issuers: [12] }, { prompt_policy: { history_turns: "many" } }, { custom_retrieval: { k: "lots" } }])("rejects malformed profile fields before importing %j", patch => {
  configureBrowserStorage("prod"); saveConversations(conversations);
  const prior = physicalEntries();
  const payload = JSON.stringify({ format: "docreview-browser-storage", version: 1, entries: [{ key: "docreview:profile-defaults:v1", version: 1, value: JSON.stringify({ version: 1, value: JSON.stringify({ ...DEFAULT_SESSION_PROFILE, ...patch }) }) }] });
  expect(() => importBrowserSettings(payload, true)).toThrow();
  expect(physicalEntries()).toEqual(prior);
});

it("preserves the normal unsectioned filter through persistence and import", () => {
  configureBrowserStorage("prod");
  const profile = { ...DEFAULT_SESSION_PROFILE, sections: [null, "7"] };
  saveDefaultProfile(profile);
  const backup = exportBrowserSettings();
  configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
  importBrowserSettings(backup, true);
  expect(loadDefaultProfile().sections).toEqual([null, "7"]);
});

it("round-trips vector-only retrieval with its intentionally absent lexical ranker", () => {
  configureBrowserStorage("prod");
  const profile = { ...DEFAULT_SESSION_PROFILE, retrieval_preset: "custom" as const, custom_retrieval: { ...DEFAULT_PROFILE, strategy: "vector" as const, lexical_ranker: null } };
  saveDefaultProfile(profile);
  const backup = exportBrowserSettings();
  configureBrowserStorage("dev"); localStorage.clear(); configureBrowserStorage("prod");
  importBrowserSettings(backup, true);
  expect(loadDefaultProfile().custom_retrieval).toEqual(profile.custom_retrieval);
});
