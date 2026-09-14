import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { browserStorage, configureBrowserStorage, exportBrowserSettings, STORAGE_NOTICE_KEY } from "@/lib/storage";
import { BrowserStorageSettings, BrowserStorageSupport } from "./browser-storage";
import { NotificationProvider } from "./notifications";

beforeEach(() => { vi.restoreAllMocks(); configureBrowserStorage("dev"); localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); configureBrowserStorage(undefined); });

it("hides the support notice and settings in DEV", () => {
  render(<><BrowserStorageSupport enabled={false} /><BrowserStorageSettings /></>);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Browser storage" })).not.toBeInTheDocument();
});

it("preserves notice dismissal and shows the settings reminder in an anchored bubble", () => {
  configureBrowserStorage("prod");
  const view = render(<><BrowserStorageSupport enabled /><BrowserStorageSettings /></>);
  expect(screen.getByRole("status", { name: "Browser storage" })).toHaveTextContent("Settings and conversations are saved only in this browser");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Learn more" })).toHaveAttribute("href", "/docreview-rag/docs/en/settings/#browser-storage");
  fireEvent.click(screen.getByRole("button", { name: "Got it" }));
  expect(browserStorage().getItem(STORAGE_NOTICE_KEY)).toBe("done");
  expect(screen.queryByRole("status", { name: "Browser storage" })).not.toBeInTheDocument();
  view.unmount();
  render(<><BrowserStorageSupport enabled /><BrowserStorageSettings /></>);
  expect(screen.queryByRole("status", { name: "Browser storage" })).not.toBeInTheDocument();
  const trigger = screen.getByRole("button", { name: "Show browser storage notice" });
  fireEvent.mouseEnter(trigger.parentElement!);
  expect(screen.getByRole("tooltip", { name: "Browser storage" })).toHaveTextContent("Settings and conversations are saved only in this browser");
  fireEvent.click(trigger);
  expect(screen.getByRole("dialog", { name: "Browser storage" })).toBeVisible();
  expect(screen.queryByRole("status", { name: "Browser storage" })).toBeNull();
  expect(browserStorage().getItem(STORAGE_NOTICE_KEY)).toBe("done");
});

it("dismisses explicitly with Escape without a modal", () => {
  configureBrowserStorage("prod"); render(<BrowserStorageSupport enabled />);
  fireEvent.keyDown(screen.getByRole("status", { name: "Browser storage" }), { key: "Escape" });
  expect(browserStorage().getItem(STORAGE_NOTICE_KEY)).toBe("done");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("provides Korean notice copy and the matching localized tutorial link", () => {
  configureBrowserStorage("prod"); browserStorage().setItem("docreview.locale", "ko");
  render(<I18nProvider><BrowserStorageSupport enabled /></I18nProvider>);
  const notice = screen.getByRole("status");
  expect(notice).not.toHaveTextContent("Settings and conversations are saved only in this browser");
  expect(notice.textContent).toMatch(/[가-힣]/);
  expect(screen.getByRole("link")).toHaveAttribute("href", "/docreview-rag/docs/ko/settings/#browser-storage");
});

it("switches the entire storage notice from Korean to English", () => {
  configureBrowserStorage("prod"); browserStorage().setItem("docreview.locale", "ko");
  render(<I18nProvider><BrowserStorageSupport enabled /></I18nProvider>);
  expect(screen.getByRole("status").textContent).toMatch(/[가-힣]/);
  fireEvent(window, new StorageEvent("storage", { key: "docreview.locale", newValue: "en" }));
  const notice = screen.getByRole("status", { name: "Browser storage" });
  expect(notice).toHaveTextContent("Settings and conversations are saved only in this browser");
  expect(notice).toHaveTextContent("They are not synced and can be removed when you clear browser data.");
  expect(notice.textContent).not.toMatch(/[가-힣]/);
  expect(screen.getByRole("link", { name: "Learn more" })).toHaveAttribute("href", "/docreview-rag/docs/en/settings/#browser-storage");
  expect(screen.getByRole("button", { name: "Got it" })).toBeVisible();
});

/** File.text is unavailable in some jsdom versions; supply the real browser's file contract. */
function upload(text: string) {
  const file = new File([text], "settings.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: () => Promise.resolve(text) });
  fireEvent.change(screen.getByLabelText("Browser settings file"), { target: { files: [file] } });
}

it("rejects invalid imports before confirmation and preserves existing settings", async () => {
  configureBrowserStorage("prod"); browserStorage().setItem("docreview:theme", "dark");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<NotificationProvider><BrowserStorageSettings /></NotificationProvider>);
  upload("{broken JSON");
  await screen.findByRole("alert");
  expect(confirm).not.toHaveBeenCalled(); expect(browserStorage().getItem("docreview:theme")).toBe("dark");
});

it("leaves valid imports unchanged when confirmation is declined, then restores after consent", async () => {
  configureBrowserStorage("prod"); browserStorage().setItem("docreview:theme", "light");
  const backup = exportBrowserSettings(); browserStorage().setItem("docreview:theme", "dark");
  render(<NotificationProvider><BrowserStorageSettings /></NotificationProvider>);
  upload(backup);
  await screen.findByRole("dialog");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(browserStorage().getItem("docreview:theme")).toBe("dark");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  upload(backup);
  fireEvent.click(await screen.findByRole("button", { name: "Continue" }));
  await waitFor(() => expect(browserStorage().getItem("docreview:theme")).toBe("light"));
  expect(screen.getByRole("status")).toHaveTextContent("Browser settings imported.");
});
