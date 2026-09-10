import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { allowancePercent, UsageAvailabilityDashboard } from "./usage-availability-dashboard";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("does not turn unknown, malformed or zero-ceiling values into full allowance", () => {
  expect(allowancePercent(undefined, undefined)).toBeNull();
  expect(allowancePercent("", "1")).toBeNull();
  expect(allowancePercent("broken", "1")).toBeNull();
  expect(allowancePercent("0", "0")).toBeNull();
  expect(allowancePercent("-1", "1")).toBeNull();
  expect(allowancePercent("0.8", "1")).toBe(80);
  expect(allowancePercent("0", "1")).toBe(0);
});

it("renders only actual server state without preview controls or provider calls", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<UsageAvailabilityDashboard limits={null} readiness={null} />);
  expect(screen.getByText("Status unavailable")).toBeInTheDocument();
  expect(screen.queryByText("100%")).not.toBeInTheDocument();
  expect(screen.queryByText("Preview limit states")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});
