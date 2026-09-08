import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { applyFreshStartReset, loadDefaultProfile, configureBrowserStorage, FRESH_START_RECEIPT_KEY } from "./storage";
import { DEFAULT_SESSION_PROFILE } from "./types";
import { loadAcquisitionDraft, saveAcquisitionDraft, acquisitionDraft } from "./source-selection";

const first = "01234567-1234-4123-8123-012345678901";
const second = "01234567-1234-4123-8123-012345678902";
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); configureBrowserStorage("dev"); });
afterEach(() => { localStorage.clear(); sessionStorage.clear(); configureBrowserStorage(); });

it("leaves existing settings alone without an explicit server reset", () => {
  localStorage.setItem("docreview:theme", "dark");
  expect(applyFreshStartReset(null)).toBe(false);
  expect(applyFreshStartReset("invalid")).toBe(false);
  expect(localStorage.getItem("docreview:theme")).toBe("dark");
});

it("clears only DocReview local and session keys and acknowledges each reset once", () => {
  for (const store of [localStorage, sessionStorage]) {
    store.setItem("docreview:conversations:v2", "old conversations");
    store.setItem("docreview:acquisition-draft:v1", "old basket");
    store.setItem("docreview.locale", "en");
    store.setItem("unrelated-app", "keep");
  }
  expect(applyFreshStartReset(first)).toBe(true);
  for (const store of [localStorage, sessionStorage]) {
    expect(store.getItem("docreview:conversations:v2")).toBeNull();
    expect(store.getItem("docreview:acquisition-draft:v1")).toBeNull();
    expect(store.getItem("docreview.locale")).toBeNull();
    expect(store.getItem("unrelated-app")).toBe("keep");
    expect(store.getItem(FRESH_START_RECEIPT_KEY)).toBe(first);
  }
  localStorage.setItem("docreview:theme", "light");
  expect(applyFreshStartReset(first)).toBe(false);
  expect(localStorage.getItem("docreview:theme")).toBe("light");
  expect(applyFreshStartReset(second)).toBe(true);
  expect(localStorage.getItem("docreview:theme")).toBeNull();
});

it("clears a stale tab's session without erasing settings created after another tab reset", () => {
  localStorage.setItem(FRESH_START_RECEIPT_KEY, second);
  localStorage.setItem("docreview:theme", "light");
  sessionStorage.setItem(FRESH_START_RECEIPT_KEY, first);
  sessionStorage.setItem("docreview:cached", "old");
  expect(applyFreshStartReset(second)).toBe(true);
  expect(sessionStorage.getItem("docreview:cached")).toBeNull();
  expect(localStorage.getItem("docreview:theme")).toBe("light");
});


it("returns the basket and conversation defaults to their unsaved state", () => {
  saveAcquisitionDraft("default-v1", acquisitionDraft([{ registry: "dart", issuer: "000660", year: 2025 }]));
  expect(loadAcquisitionDraft("default-v1")?.pairs).toHaveLength(1);
  applyFreshStartReset(first);
  expect(loadAcquisitionDraft("default-v1")).toBeNull();
  expect(loadDefaultProfile()).toEqual(DEFAULT_SESSION_PROFILE);
});

it("does not acknowledge a reset when deleting stored preferences fails", () => {
  localStorage.setItem("docreview:theme", "dark");
  const remove = vi.spyOn(Storage.prototype, "removeItem").mockImplementationOnce(() => { throw new Error("Storage blocked"); });
  try {
    expect(() => applyFreshStartReset(first)).toThrow("Storage blocked");
    expect(localStorage.getItem(FRESH_START_RECEIPT_KEY)).toBeNull();
  } finally { remove.mockRestore(); }
  expect(applyFreshStartReset(first)).toBe(true);
});
