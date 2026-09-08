import { beforeEach, describe, expect, it } from "vitest";
import { appendNotification, loadNotifications, readNotification, saveNotifications, validNotificationTarget, type NotificationEntry } from "./notification-store";

beforeEach(() => localStorage.clear());
function entry(index: number, kind: NotificationEntry["kind"] = "info"): NotificationEntry {
  return { id: `id-${index}`, key: `key-${index}`, kind, title: "Notification", body: `Message ${index}`, createdAt: "2026-09-08T00:00:00Z", updatedAt: "2026-09-08T00:00:00Z", count: 1 };
}
describe("notification history", () => {
  it("caps at 100 while keeping the newest logical events and persists them", () => {
    let rows: NotificationEntry[] = [];
    for (let i = 0; i < 105; i++) rows = appendNotification(rows, entry(i));
    expect(rows).toHaveLength(100);expect(rows[0].id).toBe("id-5");
    saveNotifications(rows);expect(loadNotifications()).toEqual(rows);
  });
  it("coalesces identical errors and keeps the same identity across job status updates", () => {
    const first = entry(1, "error");
    let rows = appendNotification([], first);rows = readNotification(rows, first.id, "2026-09-08T01:00:00Z");
    rows = appendNotification(rows, { ...first, id: "new-id", updatedAt: "2026-09-08T02:00:00Z" });
    expect(rows).toHaveLength(1);expect(rows[0]).toMatchObject({ id: first.id, count: 2 });expect(rows[0].readAt).toBeUndefined();
    rows = appendNotification(rows, { ...first, kind: "success", body: "Recovered" });
    expect(rows[0]).toMatchObject({ id: first.id, count: 1, body: "Recovered" });
  });
  it("marks read without deleting and persists unread state through reload", () => {
    let rows = [entry(1), entry(2)];rows = readNotification(rows, rows[0].id, "2026-09-08T01:00:00Z");
    saveNotifications(rows);expect(loadNotifications().filter(row => !row.readAt)).toHaveLength(1);
    expect(readNotification(rows, null, "2026-09-08T02:00:00Z")).toHaveLength(2);
  });
  it("accepts internal destinations and rejects stored external navigation", () => {
    for (const target of [{ view: "build", tab: "jobs", jobId: "job-1" }, { view: "measure", tab: "compare", resultId: 5 }, { view: "review", conversationId: "conversation-1" }, { view: "settings", category: "local" }, { view: "system", tab: "status" }]) expect(validNotificationTarget(target)).toBe(true);
    expect(validNotificationTarget({ view: "external", url: "https://example.com" })).toBe(false);
    expect(validNotificationTarget({ view: "measure", resultId: -1 })).toBe(false);
  });
});
