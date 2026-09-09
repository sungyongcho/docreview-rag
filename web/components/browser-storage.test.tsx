import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { browserStorage, configureBrowserStorage, exportBrowserSettings, STORAGE_NOTICE_KEY } from "@/lib/storage";
import { exitProductionPreview } from "@/lib/production-preview";
import { BrowserStorageSettings, BrowserStorageSupport } from "./browser-storage";
import { NotificationProvider } from "./notifications";

beforeEach(() => { vi.restoreAllMocks(); exitProductionPreview(); configureBrowserStorage("dev"); localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); configureBrowserStorage(undefined); });

it("hides the support notice and settings in DEV", () => {
  render(<><BrowserStorageSupport enabled={false} /><BrowserStorageSettings /></>);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Browser storage" })).not.toBeInTheDocument();
});

it("shows a nonmodal PROD notice, persists dismissal, and reopens through the settings reminder", () => {
  configureBrowserStorage("prod");
  const view = render(<><BrowserStorageSupport enabled /><BrowserStorageSettings /></>);
  expect(screen.getByRole("status", { name: "Browser storage" })).toHaveTextContent("Settings and conversations are saved only in this browser");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Learn more" })).toHaveAttribute("href", "/docreview-rag-agent/docs/en/settings/#browser-storage");
  fireEvent.click(screen.getByRole("button", { name: "Got it" }));
  expect(browserStorage().getItem(STORAGE_NOTICE_KEY)).toBe("done");
  expect(screen.queryByRole("status", { name: "Browser storage" })).not.toBeInTheDocument();
  view.unmount();
  render(<><BrowserStorageSupport enabled /><BrowserStorageSettings /></>);
  expect(screen.queryByRole("status", { name: "Browser storage" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show browser storage notice" }));
  expect(screen.getByRole("status", { name: "Browser storage" })).toBeInTheDocument();
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
  expect(screen.getByRole("link")).toHaveAttribute("href", "/docreview-rag-agent/docs/ko/settings/#browser-storage");
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
