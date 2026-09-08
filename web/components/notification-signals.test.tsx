import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { loadNotifications } from "@/lib/notification-store";
import { NotificationProvider } from "./notifications";
import { NotificationSignals } from "./notification-signals";

const fixture = vi.hoisted(() => ({ catalog: { loaded: true, storageKind: "file", presets: [] as unknown[], builtins: [] as unknown[], fileErrors: [] as Array<{file: string;error: string}>, error: null as string | null }, receipts: vi.fn() }));
vi.mock("@/lib/use-saved-presets", () => ({ useSavedPresets: () => fixture.catalog }));
vi.mock("@/lib/operator-api", () => ({ getLifecycleReceipts: fixture.receipts }));
const props = { enabled: true, healthKind: "healthy" as const, checkedAt: null, operations: false, model: null, cpuSpeed: null, conversationId: "conversation-1", reviewVisible: false, jobsVisible: false, systemVisible: false };
beforeEach(() => { localStorage.clear();fixture.catalog = { loaded: true, storageKind: "file", presets: [], builtins: [], fileErrors: [], error: null };fixture.receipts.mockReset(); });
afterEach(cleanup);

it("notifies on actual preset changes, with no duplicate from unchanged callbacks or adapter reloading", () => {
  const { rerender } = render(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  fixture.catalog = { ...fixture.catalog, presets: [{ id: "preset", name: "Changed" }] };
  rerender(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  expect(loadNotifications().filter(entry => entry.key === "preset-sync")).toHaveLength(1);
  const first = loadNotifications();
  fixture.catalog = { ...fixture.catalog };rerender(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  fixture.catalog = { ...fixture.catalog, loaded: false, presets: [] };rerender(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  fixture.catalog = { ...fixture.catalog, loaded: true, presets: [{ id: "preset", name: "Changed" }] };rerender(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  expect(loadNotifications()).toEqual(first);
});

it("records health transitions once and preserves a server-provided degradation message", () => {
  const { rerender } = render(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  rerender(<NotificationProvider><NotificationSignals {...props} healthKind="db_degraded" healthMessage="Original server explanation." /></NotificationProvider>);
  expect(loadNotifications().at(-1)?.body).toBe("Original server explanation.");
  const count=loadNotifications().length;rerender(<NotificationProvider><NotificationSignals {...props} healthKind="db_degraded" healthMessage="Original server explanation." /></NotificationProvider>);
  expect(loadNotifications()).toHaveLength(count);
  rerender(<NotificationProvider><NotificationSignals {...props} /></NotificationProvider>);
  expect(loadNotifications().at(-1)?.body).toBe("API connection recovered.");
});

it("links an observed slow CPU measurement to its conversation", () => {
  render(<NotificationProvider><NotificationSignals {...props} model="local-model" cpuSpeed={8.5} /></NotificationProvider>);
  expect(loadNotifications().find(entry=>entry.key==="local-cpu:local-model")?.target).toEqual({view:"review",conversationId:"conversation-1"});
});

it("does not repeat the same completed fresh-start receipt on later health checks", async () => {
  fixture.receipts.mockResolvedValue([{command:"start-fresh",updated:1,status:"succeeded",completed:["files"]}]);
  const {rerender}=render(<NotificationProvider><NotificationSignals {...props} operations checkedAt="first" /></NotificationProvider>);
  await waitFor(()=>expect(loadNotifications().some(entry=>entry.key==="fresh-start:1")).toBe(true));
  const first=loadNotifications();
  rerender(<NotificationProvider><NotificationSignals {...props} operations checkedAt="second" /></NotificationProvider>);
  await act(async()=>{});expect(loadNotifications()).toEqual(first);
});


it("records a local server availability transition only once", () => {
  const {rerender}=render(<NotificationProvider><NotificationSignals {...props} local={{enabled:true,checked_at:"first"}} /></NotificationProvider>);
  rerender(<NotificationProvider><NotificationSignals {...props} local={{enabled:false,reason:"unreachable",checked_at:"second"}} /></NotificationProvider>);
  expect(loadNotifications().filter(entry=>entry.key==="local-connection")).toHaveLength(1);
  const first=loadNotifications();
  rerender(<NotificationProvider><NotificationSignals {...props} local={{enabled:false,reason:"unreachable",checked_at:"third"}} /></NotificationProvider>);
  expect(loadNotifications()).toEqual(first);
});
