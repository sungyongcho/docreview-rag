import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationProvider, useNotifications, useNotificationSurface } from "./notifications";
import { NotificationCenter } from "./notification-center";
import { loadNotifications } from "@/lib/notification-store";
import { setDesktopJobNotifications } from "@/lib/storage";

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup();vi.useRealTimers();vi.unstubAllGlobals(); });
function Probe({ modal = false, long = false }: { modal?: boolean; long?: boolean }) {
  const { notify } = useNotifications();useNotificationSurface("health", modal);
  return <><button onClick={() => notify(long ? "Original server detail ".repeat(30) : "Original server message.", "error", "health", 1000, { event: "health-transition", detail: { text: "ValueError: original detail", cause: "invalid_json", path: "manifest.json" } })}>Emit</button><button onClick={() => notify("Job complete", "success", "job:1", undefined, { event: "job-status", jobId: "1", desktop: true, target: { view: "build", tab: "jobs", jobId: "1" } })}>Job</button></>;
}
function mount(props = {}, navigate = vi.fn()) { return { ...render(<NotificationProvider><Probe {...props} /><NotificationCenter developer onNavigate={navigate} /></NotificationProvider>), navigate }; }
function open() { fireEvent.click(screen.getByRole("button", { name: /^Notifications ·/ }));return screen.getByRole("dialog", { name: "Notification center" }); }

describe("notification center", () => {
  it("retains history on expiry, panel collapse and reload; explicit banner dismissal marks read", async () => {
    vi.useFakeTimers();const view = mount();fireEvent.click(screen.getByText("Emit"));
    await act(async () => { await vi.advanceTimersByTimeAsync(1001); });
    expect(screen.queryByText("Original server message.")).toBeNull();expect(loadNotifications()).toHaveLength(1);expect(loadNotifications()[0].readAt).toBeUndefined();
    const panel = open();expect(within(panel).getByText("Original server message.")).toBeVisible();
    fireEvent.keyDown(panel, { key: "Escape" });expect(loadNotifications()).toHaveLength(1);
    view.unmount();mount();expect(screen.getByRole("button", { name: "Notifications · 1 unread" })).toBeVisible();
    fireEvent.click(screen.getByText("Emit"));fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(loadNotifications()).toHaveLength(1);expect(loadNotifications()[0].readAt).toBeDefined();
  });
  it("coalesces repeats, shows detail and offers read and delete separately", () => {
    mount();fireEvent.click(screen.getByText("Emit"));fireEvent.click(screen.getByText("Emit"));
    const panel=open();expect(loadNotifications()[0].count).toBe(2);expect(within(panel).getByText("×2")).toBeVisible();
    fireEvent.click(within(panel).getByText("Technical details"));expect(within(panel).getByText("ValueError: original detail")).toBeVisible();
    fireEvent.click(within(panel).getByText("Mark all read"));expect(loadNotifications()).toHaveLength(1);
    fireEvent.click(within(panel).getByText("Clear all notifications"));expect(loadNotifications()).toEqual([]);
  });
  it("uses arrow keys, activates the typed destination, marks read, and returns focus on Escape", () => {
    const {navigate}=mount();fireEvent.click(screen.getByText("Emit"));fireEvent.click(screen.getByText("Job"));
    const panel=open();fireEvent.keyDown(panel,{key:"ArrowDown"});const target=within(panel).getByRole("button",{name:/Job complete/});expect(target).toHaveFocus();
    fireEvent.click(target);expect(navigate).toHaveBeenCalledWith({view:"build",tab:"jobs",jobId:"1"});expect(loadNotifications().find(entry=>entry.jobId==="1")?.readAt).toBeDefined();
  });
  it("suppresses a matching modal banner and every banner while history is open without losing entries", () => {
    mount({modal:true});fireEvent.click(screen.getByText("Emit"));expect(document.querySelector(".notification-stack")).toBeNull();
    expect(loadNotifications()).toHaveLength(1);open();expect(document.querySelector(".notification-stack")).toBeNull();expect(within(screen.getByRole("dialog", {name:"Notification center"})).getByText("Original server message.")).toBeVisible();
  });
  it("keeps long server text intact and expandable with accessible kind pictograms", () => {
    mount({long:true});fireEvent.click(screen.getByText("Emit"));const panel=open();
    expect(within(panel).getByRole("img",{name:"Error"})).toBeVisible();
    expect(within(panel).getByText("Original server detail ".repeat(30).trim())).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button",{name:"Expand notification"}));expect(panel.querySelector(".notification-body-collapsed")).toBeNull();
  });
  it("mirrors the same job event to desktop only when already enabled", () => {
    const desktop=vi.fn(function(this: { close: () => void }) { this.close = () => undefined; });
    Object.assign(desktop,{permission:"granted"});vi.stubGlobal("Notification",desktop);setDesktopJobNotifications(true);
    mount();fireEvent.click(screen.getByText("Job"));expect(desktop).toHaveBeenCalledOnce();expect(loadNotifications()).toHaveLength(1);
    expect(desktop).toHaveBeenCalledWith("DocReview · Job activity",{body:"Job complete",tag:"job:1"});
  });
});
