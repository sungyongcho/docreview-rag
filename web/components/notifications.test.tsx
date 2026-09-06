import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NotificationProvider, useNotifications } from "./notifications";

function Probe() {
  const { notify, dismissNotice } = useNotifications();
  return <><button onClick={() => notify("Waiting for API", "info", "health-wait", 0)}>Wait</button><button onClick={() => { for (let i = 0; i < 4; i++) notify(`Job ${i}`); }}>Jobs</button><button onClick={() => dismissNotice("health-wait")}>Recover</button></>;
}
afterEach(() => { cleanup(); vi.useRealTimers(); });
it("keeps one persistent waiting notice through job updates and removes it on recovery", async () => {
  vi.useFakeTimers();
  render(<NotificationProvider><Probe /></NotificationProvider>);
  fireEvent.click(screen.getByText("Wait")); fireEvent.click(screen.getByText("Wait"));
  fireEvent.click(screen.getByText("Jobs"));
  await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
  expect(screen.getAllByText("Waiting for API")).toHaveLength(1);
  fireEvent.click(screen.getByText("Recover"));
  expect(screen.queryByText("Waiting for API")).toBeNull();
});
